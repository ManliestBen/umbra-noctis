"""The image library: a persistent SQLite catalog of every imported session.

The database lives at ``~/.umbra-noctis/library.db`` by default (override with
the ``UMBRA_HOME`` environment variable or the ``db_path`` argument). Raw files
are never moved or modified — the library stores *references* plus metadata.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Callable
from pathlib import Path

from ..ingest.session import DwarfSession
from .targets import resolve_target

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    fingerprint TEXT,
    kind TEXT, lens TEXT,
    target_raw TEXT, target TEXT, target_display TEXT, target_kind TEXT,
    exposure_s REAL, gain INTEGER, timestamp TEXT, filter_hint TEXT,
    ra REAL, dec REAL,
    frame_count INTEGER, integration_s REAL,
    rating INTEGER DEFAULT 0, notes TEXT DEFAULT '', tags TEXT DEFAULT '[]',
    imported_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS frames (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    idx INTEGER,
    accepted INTEGER DEFAULT 1,
    quality TEXT DEFAULT '{}',
    UNIQUE(session_id, path)
);
CREATE TABLE IF NOT EXISTS outputs (
    id INTEGER PRIMARY KEY,
    session_id INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
    target TEXT, name TEXT, path TEXT,
    recipe TEXT DEFAULT '[]',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_sessions_target ON sessions(target);
CREATE INDEX IF NOT EXISTS idx_frames_session ON frames(session_id);
"""


_CURRENT_VERSION = 1
# Ordered (target_version, migrate_callable) pairs, applied in order to bring
# an older database up to _CURRENT_VERSION. Future schema changes must NEVER
# edit an existing table in _SCHEMA above — CREATE TABLE IF NOT EXISTS only
# runs on a fresh (or already-up-to-date) database, so altering it in place
# would silently no-op against every existing installed catalog. Instead:
# write a migration function here, append it to _MIGRATIONS, and bump
# _CURRENT_VERSION.
_MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = []


def default_db_path() -> Path:
    home = os.environ.get("UMBRA_HOME")
    base = Path(home) if home else Path.home() / ".umbra-noctis"
    base.mkdir(parents=True, exist_ok=True)
    return base / "library.db"


def _fingerprint(session: DwarfSession) -> str:
    """Cheap content fingerprint: frame count, first/last light's size + first
    64 KiB, and the session timestamp. Detects re-imports of the same data
    from a different path."""
    h = hashlib.sha256()
    h.update(str(len(session.lights)).encode())
    for light in session.lights[:1] + session.lights[-1:]:
        try:
            h.update(str(Path(light).stat().st_size).encode())
            with open(light, "rb") as f:
                h.update(f.read(65536))
        except OSError:
            pass
    h.update(str(session.timestamp or "").encode())
    return h.hexdigest()[:24]


class Library:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)

        ver = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if ver < _CURRENT_VERSION:
            for target, migrate in _MIGRATIONS:
                if ver < target:
                    migrate(self.conn)
                    ver = target
            self.conn.execute(f"PRAGMA user_version = {_CURRENT_VERSION}")
            self.conn.commit()

    def close(self):
        self.conn.close()

    # ------------------------------------------------------------- imports
    def import_session(self, session: DwarfSession) -> tuple[int, bool]:
        """Add a session to the catalog. Returns ``(session_id, was_new)``.

        Re-importing the same folder updates it in place. Identical data
        found under a *different* folder is no longer silently dropped —
        it's cataloged as its own session (two folders, two rows); only an
        unchanged re-import of the exact same path short-circuits here.
        """
        fp = _fingerprint(session)
        cur = self.conn.execute("SELECT id, path FROM sessions WHERE fingerprint = ?", (fp,))
        existing = cur.fetchone()
        if existing and Path(existing["path"]) == session.path:
            return existing["id"], False

        info = resolve_target(session.target)
        cur = self.conn.execute(
            """INSERT INTO sessions (path, fingerprint, kind, lens, target_raw, target,
                    target_display, target_kind, exposure_s, gain, timestamp, filter_hint,
                    ra, dec, frame_count, integration_s)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(path) DO UPDATE SET
                    fingerprint=excluded.fingerprint, frame_count=excluded.frame_count,
                    integration_s=excluded.integration_s, target=excluded.target,
                    target_display=excluded.target_display""",
            (str(session.path), fp, session.kind, session.lens, session.target,
             info["canonical"], info["display"], info["kind"], session.exposure_s,
             session.gain, session.timestamp, session.filter_hint, session.ra,
             session.dec, session.frame_count, session.integration_s),
        )
        sid = self.conn.execute(
            "SELECT id FROM sessions WHERE path = ?", (str(session.path),)
        ).fetchone()["id"]
        for i, light in enumerate(session.lights):
            self.conn.execute(
                """INSERT INTO frames (session_id, path, idx) VALUES (?,?,?)
                   ON CONFLICT(session_id, path) DO NOTHING""",
                (sid, str(light), i),
            )
        self.conn.commit()
        return sid, existing is None

    # ------------------------------------------------------------- queries
    def sessions(self, target: str | None = None, kind: str | None = None) -> list[sqlite3.Row]:
        q, args = "SELECT * FROM sessions", []
        clauses = []
        if target:
            clauses.append("target = ?")
            args.append(resolve_target(target)["canonical"])
        if kind:
            clauses.append("kind = ?")
            args.append(kind)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY timestamp"
        return self.conn.execute(q, args).fetchall()

    def session(self, session_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()

    def frames(self, session_id: int, accepted_only: bool = False) -> list[sqlite3.Row]:
        q = "SELECT * FROM frames WHERE session_id = ?"
        if accepted_only:
            q += " AND accepted = 1"
        return self.conn.execute(q + " ORDER BY idx", (session_id,)).fetchall()

    def targets_summary(self) -> list[sqlite3.Row]:
        """Per-target totals: sessions, frames, integration time."""
        return self.conn.execute(
            """SELECT target, target_display,
                      COUNT(*) AS sessions,
                      SUM(frame_count) AS frames,
                      SUM(integration_s) AS integration_s,
                      MIN(timestamp) AS first_night, MAX(timestamp) AS last_night
               FROM sessions WHERE kind = 'light'
               GROUP BY target ORDER BY integration_s DESC"""
        ).fetchall()

    # ------------------------------------------------------------ mutation
    def set_frame_quality(self, frame_id: int, quality: dict, accepted: bool):
        self.conn.execute(
            "UPDATE frames SET quality = ?, accepted = ? WHERE id = ?",
            (json.dumps(quality), int(accepted), frame_id),
        )
        self.conn.commit()

    def set_rating(self, session_id: int, rating: int):
        self.conn.execute("UPDATE sessions SET rating = ? WHERE id = ?",
                          (max(0, min(5, rating)), session_id))
        self.conn.commit()

    def set_notes(self, session_id: int, notes: str):
        self.conn.execute("UPDATE sessions SET notes = ? WHERE id = ?", (notes, session_id))
        self.conn.commit()

    def add_output(self, target: str, name: str, path: str | Path,
                   recipe: list | None = None, session_id: int | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO outputs (session_id, target, name, path, recipe) VALUES (?,?,?,?,?)",
            (session_id, target, name, str(path), json.dumps(recipe or [])),
        )
        self.conn.commit()
        return cur.lastrowid

    def outputs(self, target: str | None = None) -> list[sqlite3.Row]:
        if target:
            return self.conn.execute(
                "SELECT * FROM outputs WHERE target = ? ORDER BY created_at DESC",
                (resolve_target(target)["canonical"],),
            ).fetchall()
        return self.conn.execute("SELECT * FROM outputs ORDER BY created_at DESC").fetchall()
