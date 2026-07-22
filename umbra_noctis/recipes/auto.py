"""The one-click "Auto" pipeline: raw Dwarf 3 session folder -> shareable image.

Opinionated defaults tuned for Dwarf 3 data:
  master dark (if a dark session is available) -> grade & reject -> register
  -> stack -> gradient removal -> background neutralize -> auto white balance
  -> SCNR -> mild denoise -> GHS stretch -> vibrance -> export

Every decision it makes is logged and recorded in the output's history, so an
auto-processed image is a *starting point* you can inspect and reprocess, not
a black box.
"""

from __future__ import annotations

from pathlib import Path

from ..calib.masters import build_master
from ..core.image import AstroImage
from ..core.ops import apply_op
from ..export.writers import export_image
from ..ingest.session import DwarfSession, discover_sessions, parse_session
from ..stack.integrate import StackResult, integrate

AUTO_RECIPE_STEPS = [
    {"op": "background_extract", "params": {"degree": 2, "mode": "subtract"}},
    {"op": "background_neutralize", "params": {}},
    {"op": "white_balance", "params": {"auto": True}},
    {"op": "scnr", "params": {"amount": 0.8}},
    {"op": "denoise", "params": {"method": "wavelet", "strength": 1.0}},
    {"op": "ghs", "params": {"amount": 6.0, "focus": 0.08, "protect_highlights": 0.8}},
    {"op": "ghs", "params": {"amount": 2.5, "focus": 0.25, "protect_highlights": 0.9}},
    {"op": "saturation", "params": {"amount": 1.35, "vibrance": True}},
]


def find_matching_darks(session: DwarfSession, search_root: Path | None = None) -> DwarfSession | None:
    """Look for a dark session with the same exposure and gain near the lights."""
    root = search_root or session.path.parent
    try:
        candidates = [s for s in discover_sessions(root)
                      if s.kind == "dark"
                      and s.exposure_s == session.exposure_s
                      and s.gain == session.gain]
    except FileNotFoundError:
        return None
    return candidates[0] if candidates else None


def auto_process(session_dir: str | Path, out_dir: str | Path,
                 darks_dir: str | Path | None = None,
                 export_formats: tuple[str, ...] = ("jpg", "tif", "fits"),
                 progress=None, log=None) -> tuple[AstroImage, StackResult, list[Path]]:
    """Run the full automatic pipeline on one session folder.

    Returns ``(final_image, stack_result, exported_paths)``.
    """
    logs = []

    def _log(msg):
        logs.append(msg)
        if log:
            log(msg)

    session = parse_session(session_dir)
    _log(f"Session: {session.summary()}")

    master_dark = None
    dark_session = (parse_session(darks_dir) if darks_dir
                    else find_matching_darks(session))
    if dark_session and dark_session.lights:
        master_dark = build_master(dark_session.lights)
        _log(f"Master dark from {len(dark_session.lights)} frames "
             f"({dark_session.path.name})")
    else:
        _log("No matching darks found — using statistical hot-pixel removal")

    result = integrate(session.lights, master_dark=master_dark,
                       progress=progress, log=log)
    img = result.image

    for step in AUTO_RECIPE_STEPS:
        try:
            img = apply_op(img, step["op"], **step["params"])
            _log(f"applied {step['op']}")
        except Exception as exc:  # a single failed cosmetic step shouldn't kill the run
            _log(f"SKIPPED {step['op']}: {exc}")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = session.target.replace(" ", "") or "result"
    exported = []
    for fmt in export_formats:
        p = export_image(img, out_dir / f"{base}.{fmt}")
        exported.append(p)
        _log(f"exported {p}")
    return img, result, exported
