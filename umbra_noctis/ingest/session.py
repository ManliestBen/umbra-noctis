"""Dwarf 3 session discovery and parsing.

A "session" is one capture run on the telescope: a folder containing the
individual sub-exposure FITS files, the device's own stacked result, and a
``shotsInfo.json`` metadata file. Folder names follow DwarfLab conventions like

    DWARF_RAW_TELE_M 42_EXP_15_GAIN_80_2026-01-20-21-30-15-123
    DWARF_DARK_EXP_15_GAIN_80_2026-01-20-20-05-01-000

The parser is deliberately tolerant: it works from the folder name when it
matches, falls back to ``shotsInfo.json``, and finally to FITS headers — so a
firmware update that tweaks naming won't break imports.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from astropy.io import fits

# DWARF_<KIND>[_<LENS>]_<TARGET>_EXP_<exp>_GAIN_<gain>_<timestamp>
_NAME_RE = re.compile(
    r"^DWARF_(?P<kind>RAW|DARK|FLAT|BIAS|GOTO)"
    r"(?:_(?P<lens>TELE|WIDE))?"
    r"(?:_(?P<target>.+?))?"
    r"_EXP_(?P<exp>[\d.]+)(?:s|ms)?"
    r"_GAIN_(?P<gain>\d+)"
    r"_(?P<ts>\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}(?:-\d{1,6})?)$",
    re.IGNORECASE,
)

# shotsInfo.json keys vary slightly across firmware; map every spelling we know.
_SHOTSINFO_MAP = {
    "target": ("target", "object", "name"),
    "exposure_s": ("exp", "exposure", "expTime"),
    "gain": ("gain",),
    "filter": ("ir", "filter"),
    "binning": ("binning", "bin"),
    "ra": ("RA", "ra"),
    "dec": ("DEC", "dec"),
    "shots_taken": ("shotsTaken", "shots_taken"),
    "shots_stacked": ("shotsStacked", "shots_stacked"),
    "shots_to_take": ("shotsToTake", "shots_to_take"),
}

_STACKED_HINTS = ("stack", "stacked", "final")
_REJECT_DIR_HINTS = ("failed", "discard", "reject")


@dataclass
class DwarfSession:
    """Everything we know about one capture folder."""

    path: Path
    kind: str = "light"              # light | dark | flat | bias | unknown
    lens: str = "TELE"
    target: str = ""
    exposure_s: float | None = None
    gain: int | None = None
    timestamp: str = ""              # as written by the device
    filter_hint: str = ""            # e.g. VIS / ASTRO / DUAL-BAND / CUT / PASS
    ra: float | None = None
    dec: float | None = None
    lights: list = field(default_factory=list)          # sub-exposure FITS paths
    rejected_onboard: list = field(default_factory=list)
    stacked: list = field(default_factory=list)          # device-stacked outputs
    previews: list = field(default_factory=list)         # JPG/PNG the device wrote
    shots_info: dict = field(default_factory=dict)       # raw shotsInfo.json
    parse_notes: list = field(default_factory=list)

    @property
    def frame_count(self) -> int:
        return len(self.lights)

    @property
    def integration_s(self) -> float:
        if self.exposure_s is None:
            return 0.0
        return self.exposure_s * len(self.lights)

    def summary(self) -> str:
        mins, secs = divmod(int(self.integration_s), 60)
        return (
            f"{self.target or '(unknown target)'} [{self.kind}/{self.lens}] — "
            f"{self.frame_count} × {self.exposure_s or '?'}s @ gain {self.gain} "
            f"= {mins}m{secs:02d}s  ({self.path.name})"
        )


def _read_shots_info(folder: Path) -> dict:
    for candidate in ("shotsInfo.json", "shotsinfo.json", "ShotsInfo.json"):
        p = folder / candidate
        if p.exists():
            try:
                return json.loads(p.read_text())
            except (json.JSONDecodeError, OSError):
                return {}
    return {}


def _mapped(info: dict, keys: tuple[str, ...]):
    for k in keys:
        if k in info and info[k] not in (None, ""):
            return info[k]
    return None


def _first_light_header(lights: list[Path]) -> dict:
    if not lights:
        return {}
    try:
        return dict(fits.getheader(lights[0]))
    except Exception:
        return {}


def parse_session(folder: str | Path) -> DwarfSession:
    """Parse one session folder into a :class:`DwarfSession`.

    Never raises on malformed metadata — missing values stay ``None`` and a
    note is added to ``parse_notes`` instead.
    """
    folder = Path(folder)
    s = DwarfSession(path=folder)

    # --- classify files -------------------------------------------------
    for f in sorted(folder.iterdir()):
        if f.is_dir():
            if any(h in f.name.lower() for h in _REJECT_DIR_HINTS):
                s.rejected_onboard += sorted(f.glob("*.fits"))
            continue
        low = f.name.lower()
        if low.endswith((".fits", ".fit", ".fts")):
            if any(h in low for h in _STACKED_HINTS):
                s.stacked.append(f)
            else:
                s.lights.append(f)
        elif low.endswith((".jpg", ".jpeg", ".png", ".tif", ".tiff")):
            if any(h in low for h in _STACKED_HINTS) or low.endswith((".jpg", ".jpeg")):
                s.previews.append(f)

    # --- folder name ----------------------------------------------------
    m = _NAME_RE.match(folder.name)
    if m:
        kind = m.group("kind").upper()
        s.kind = {"RAW": "light", "DARK": "dark", "FLAT": "flat",
                  "BIAS": "bias"}.get(kind, "unknown")
        s.lens = (m.group("lens") or "TELE").upper()
        s.target = (m.group("target") or "").replace("_", " ").strip()
        s.exposure_s = float(m.group("exp"))
        s.gain = int(m.group("gain"))
        s.timestamp = m.group("ts")
    else:
        s.parse_notes.append("folder name did not match Dwarf conventions")

    # --- shotsInfo.json (authoritative when present) ---------------------
    info = _read_shots_info(folder)
    if info:
        s.shots_info = info
        tgt = _mapped(info, _SHOTSINFO_MAP["target"])
        if tgt:
            s.target = str(tgt).strip()
        exp = _mapped(info, _SHOTSINFO_MAP["exposure_s"])
        if exp is not None:
            try:
                s.exposure_s = float(exp)
            except (TypeError, ValueError):
                s.parse_notes.append(f"unparseable exposure in shotsInfo: {exp!r}")
        gain = _mapped(info, _SHOTSINFO_MAP["gain"])
        if gain is not None:
            try:
                s.gain = int(gain)
            except (TypeError, ValueError):
                pass
        filt = _mapped(info, _SHOTSINFO_MAP["filter"])
        if filt is not None:
            s.filter_hint = str(filt)
        for attr, keys in (("ra", _SHOTSINFO_MAP["ra"]), ("dec", _SHOTSINFO_MAP["dec"])):
            val = _mapped(info, keys)
            if val is not None:
                try:
                    setattr(s, attr, float(val))
                except (TypeError, ValueError):
                    pass

    # --- FITS header fallback --------------------------------------------
    if s.exposure_s is None or not s.target:
        hdr = _first_light_header(s.lights)
        if s.exposure_s is None:
            for k in ("EXPTIME", "EXPOSURE", "EXP"):
                if k in hdr:
                    try:
                        s.exposure_s = float(hdr[k])
                        break
                    except (TypeError, ValueError):
                        pass
        if not s.target and "OBJECT" in hdr:
            s.target = str(hdr["OBJECT"]).strip()
        if s.gain is None and "GAIN" in hdr:
            try:
                s.gain = int(hdr["GAIN"])
            except (TypeError, ValueError):
                pass

    if s.kind == "unknown" and s.lights and not s.target:
        s.kind = "light"
    return s


def discover_sessions(root: str | Path) -> list[DwarfSession]:
    """Walk a directory tree (e.g. a copied Dwarf 3 Astronomy folder or the
    whole SD card) and return every capture session found, sorted by time."""
    root = Path(root)
    if not root.exists():
        raise FileNotFoundError(root)

    candidates: set[Path] = set()
    if root.name.upper().startswith("DWARF_") or (root / "shotsInfo.json").exists():
        candidates.add(root)
    for p in root.rglob("shotsInfo.json"):
        candidates.add(p.parent)
    for p in root.rglob("DWARF_*"):
        if p.is_dir():
            candidates.add(p)
    # Any folder with 3+ FITS files counts, even without metadata.
    for p in root.rglob("*.fits"):
        parent = p.parent
        if parent not in candidates and len(list(parent.glob("*.fits"))) >= 3:
            candidates.add(parent)

    sessions = [parse_session(c) for c in sorted(candidates)]
    sessions = [s for s in sessions if s.lights or s.stacked]
    sessions.sort(key=lambda s: s.timestamp or s.path.name)
    return sessions
