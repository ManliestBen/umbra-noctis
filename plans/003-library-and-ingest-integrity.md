# Plan 003: Fix library import corruption, add schema versioning, harden ingest parsing

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. On
> any STOP condition, stop and report. When done, update your row in
> `plans/README.md` unless the reviewer maintains the index.
>
> **Drift check (run first)**: `git diff --stat 07ab720..HEAD -- umbra_noctis/library/catalog.py umbra_noctis/ingest/session.py tests/test_ingest_library.py`
> On any mismatch with the excerpts below, STOP.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: plans/001-verification-baseline.md
- **Category**: bug
- **Planned at**: commit `07ab720`, 2026-07-25

## Why this matters

Re-importing an already-cataloged session folder silently attaches its
frames to the WRONG session id — `cursor.lastrowid` after an UPSERT that
takes the UPDATE branch returns the connection's last *insert* rowid (a
frame row), not the session's id. Separately: the user's long-lived catalog
(`~/.umbra-noctis/library.db`) has no schema version stamp, so the first
future `ALTER`-worthy change will crash every existing install; a
fingerprint collision silently drops a session from the catalog; and one
oddly-named folder on an SD card (`EXP_1.2.3`, or an `ms` exposure suffix,
or a latin-1 `shotsInfo.json`) either aborts the whole import walk or
records exposures 1000× too large — despite `parse_session`'s docstring
promising it "never raises on malformed metadata".

## Current state

- `umbra_noctis/library/catalog.py` — `import_session` (~line 86):
  ```python
  cur = self.conn.execute(
      """INSERT INTO sessions (...)
         VALUES (?,?,...)
         ON CONFLICT(path) DO UPDATE SET ...""", (...))
  sid = cur.lastrowid
  if not sid:
      sid = self.conn.execute(
          "SELECT id FROM sessions WHERE path = ?", (str(session.path),)
      ).fetchone()["id"]
  ```
  When the UPSERT updates, `lastrowid` is a stale-but-truthy insert rowid,
  so the fallback never runs. Frames are then inserted with the wrong
  `session_id`.
- Same function, a few lines above: a fingerprint match from a *different*
  path returns `existing["id"], False` and the new session is never
  inserted (silent drop). `_fingerprint` (~line 60) hashes frame_count +
  first 64 KiB of the first light only.
- `catalog.py` `_SCHEMA` (~lines 19-50) is `CREATE TABLE IF NOT EXISTS ...`
  executed via `executescript` on every `Library.__init__` (~line 80).
  `grep -n "user_version" umbra_noctis/library/catalog.py` → no matches.
- `umbra_noctis/ingest/session.py`:
  - Folder-name regex (~line 29): `_EXP_(?P<exp>[\d.]+)(?:s|ms)?` — the
    unit suffix is matched but NOT captured.
  - ~line 153: `s.exposure_s = float(m.group("exp"))` — raises `ValueError`
    on `1.2.3`; treats `500ms` as 500 seconds.
  - ~lines 98-100: `shotsInfo.json` read catches only
    `(json.JSONDecodeError, OSError)` — a non-UTF-8 file raises
    `UnicodeDecodeError` out of the parser.
  - Docstring (~lines 121-125) promises: never raises on malformed
    metadata; missing values stay None; a note goes to `parse_notes`.
  - `parse_notes` appends exist at ~157 (unrecognized folder name) and ~171.
- Conventions: tests in `tests/test_ingest_library.py` use
  `write_demo_session(tmp_path)` + `parse_session` + `Library(db_path=...)`;
  follow that file's style.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Env (if missing) | `python3 -m venv .venv && .venv/bin/pip install -e ".[dev,gui]"` | exit 0 |
| Tests | `.venv/bin/python -m pytest -q` | all pass |
| Focused | `.venv/bin/python -m pytest -q tests/test_ingest_library.py` | all pass |
| Lint | `.venv/bin/python -m ruff check .` | exit 0 |

## Scope

**In scope**: `umbra_noctis/library/catalog.py`,
`umbra_noctis/ingest/session.py`, `tests/test_ingest_library.py`.

**Out of scope**: `umbra_noctis/cli.py`, the GUI, `recipes/auto.py`
(their behavior changes only via these fixes), schema *content* changes
(no new columns in this plan — only the versioning mechanism).

## Git workflow

Branch as dispatched; commit per step.

## Steps

### Step 1: Always resolve the session id explicitly

> **NOTE (2026-07-25, reviewer)**: this fix was pulled forward into plan
> 001's execution as an approved deviation — plan 001's honest dedup
> assertion exposed the bug immediately. VERIFY it is present
> (`grep -n "lastrowid" umbra_noctis/library/catalog.py` → 0 matches); if
> so, skip the edit and just write the Step 5 regression test for it.

In `import_session`, replace the `sid = cur.lastrowid` + `if not sid`
fallback with an unconditional:

```python
sid = self.conn.execute(
    "SELECT id FROM sessions WHERE path = ?", (str(session.path),)
).fetchone()["id"]
```

**Verify**: new test (Step 5) `test_reimport_keeps_frames_attached` passes.

### Step 2: Log-don't-drop on fingerprint collision, and strengthen the fingerprint

1. In `_fingerprint`, hash: frame count, the first light's size and first
   64 KiB, AND the last light's size and first 64 KiB, AND
   `session.timestamp or ""`. Keep the `[:24]` hex truncation.
2. In `import_session`, when a fingerprint matches but the path differs:
   still insert the new session (fall through), and record the suspicion —
   add `"possible duplicate of #<id>"` to a new `notes`-style mechanism:
   simplest is to print nothing here but return normally; instead add the
   session with its own row. Change the early-return branch to only
   short-circuit when `Path(existing["path"]) == session.path`.
   (The `(id, was_new)` contract is unchanged.)

**Verify**: `test_different_folder_same_data_both_kept` (Step 5) passes.

### Step 3: Schema versioning via PRAGMA user_version

In `Library.__init__` after `executescript(_SCHEMA)`:

```python
_CURRENT_VERSION = 1  # module level

ver = self.conn.execute("PRAGMA user_version").fetchone()[0]
if ver < _CURRENT_VERSION:
    for target, migrate in _MIGRATIONS:      # ordered list[(int, callable)]
        if ver < target:
            migrate(self.conn)
            ver = target
    self.conn.execute(f"PRAGMA user_version = {_CURRENT_VERSION}")
    self.conn.commit()
```

With `_MIGRATIONS: list = []` for now (v0 → v1 is just the stamp; today's
`CREATE IF NOT EXISTS` schema is v1). Add a short comment block explaining
the rule for future changes: never edit `_SCHEMA` for existing tables —
append a migration and bump `_CURRENT_VERSION`.

**Verify**: `test_schema_version_stamped` (Step 5) passes.

### Step 4: Harden ingest parsing

In `umbra_noctis/ingest/session.py`:

1. Change the regex exposure group to capture the unit:
   `_EXP_(?P<exp>[\d.]+)(?P<expunit>s|ms)?`.
2. Wrap the numeric conversions:
   ```python
   try:
       exp = float(m.group("exp"))
       if (m.group("expunit") or "s") == "ms":
           exp /= 1000.0
       s.exposure_s = exp
   except ValueError:
       s.parse_notes.append(f"unparseable exposure in folder name: {m.group('exp')!r}")
   ```
   Do the same try/except for `int(m.group("gain"))`.
3. Read `shotsInfo.json` with `encoding="utf-8", errors="replace"` and
   broaden the except to `(json.JSONDecodeError, OSError, ValueError)`.
4. Confirm nothing else in `parse_session` can raise on malformed metadata
   text (scan the function); anything found gets the same
   try/except → parse_notes treatment.

**Verify**: the three malformed-input tests in Step 5 pass.

## Test plan

Add to `tests/test_ingest_library.py` (model after its existing tests):

1. `test_reimport_keeps_frames_attached` — import a demo session, import it
   AGAIN, then `lib.frames(sid)` returns exactly `frame_count` rows and all
   have `session_id == sid`. (This fails before Step 1.)
2. `test_different_folder_same_data_both_kept` — copy the demo session dir
   (`shutil.copytree`) to a sibling name, import both, assert 2 session
   rows.
3. `test_schema_version_stamped` — open a `Library` on a fresh tmp db,
   assert `PRAGMA user_version` == 1; open the same file a second time,
   assert still 1 and data intact.
4. `test_malformed_folder_name_never_raises` — create
   `tmp_path/"DWARF_RAW_TELE_X_EXP_1.2.3_GAIN_80_2026-01-01-00-00-00-000"`
   with 3 tiny FITS files (`AstroImage(data=np.zeros((8,8),
   dtype=np.float32)).save_fits(...)`); `parse_session` returns with
   `exposure_s is None` and a non-empty `parse_notes`.
5. `test_ms_exposure_converted` — folder with `EXP_500ms` →
   `exposure_s == 0.5`.
6. `test_bad_encoding_shotsinfo` — write `shotsInfo.json` bytes
   `b"\xff\xfe{bad"`; `parse_session` does not raise.

**Verification**: `.venv/bin/python -m pytest -q` → all pass (≥6 new).

## Done criteria

- [ ] `.venv/bin/python -m pytest -q` exits 0 with the 6 new tests present
- [ ] `grep -n "lastrowid" umbra_noctis/library/catalog.py` → 0 matches
- [ ] `grep -n "user_version" umbra_noctis/library/catalog.py` → ≥2 matches
- [ ] `grep -n "expunit" umbra_noctis/ingest/session.py` → ≥2 matches
- [ ] `.venv/bin/python -m ruff check .` exits 0
- [ ] No files outside Scope modified

## STOP conditions

- The Current-state excerpts don't match (drift).
- `test_reimport_keeps_frames_attached` still fails after Step 1 — the bug
  is deeper than diagnosed; report what `frames()` returns.
- Any existing test breaks in a way not explained by an intentional
  behavior change above.

## Maintenance notes

- Future schema changes MUST go through `_MIGRATIONS` — reviewer should
  reject any PR editing `_SCHEMA`'s existing tables without a migration.
- The dedup relaxation (Step 2) means true byte-identical copies now create
  two rows; that is the intended lesser evil vs silently losing sessions.
  A future `umbra library dedupe` could reconcile.
