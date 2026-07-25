"""Acquisition summary: shareable caption text and an annotated card image."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from ..core.image import AstroImage
from ..ingest.session import DwarfSession
from ..library.targets import resolve_target
from ..process.display import auto_stretch_display


def acquisition_caption(sessions: list[DwarfSession], n_used: int | None = None) -> str:
    """Ready-to-paste caption for Reddit/AstroBin/Instagram."""
    if not sessions:
        return ""
    target = resolve_target(sessions[0].target)
    total_s = sum(s.integration_s for s in sessions)
    frames = sum(s.frame_count for s in sessions)
    nights = len({s.timestamp[:10] for s in sessions if s.timestamp})
    exp = sessions[0].exposure_s
    gain = sessions[0].gain
    exp_str = f"{exp:g}" if exp else "?"
    gain_str = f"{gain}" if gain else "?"
    hours, rem = divmod(int(total_s), 3600)
    mins = rem // 60
    lines = [
        f"{target['display']}",
        "",
        "Telescope: DwarfLab Dwarf 3 (150 mm f/4.3, IMX678)",
        f"Frames: {n_used or frames} × {exp_str}s @ gain {gain_str}"
        + (f" across {nights} night(s)" if nights > 1 else ""),
        f"Integration: {hours}h {mins:02d}m",
        "Processed with Umbra Noctis",
    ]
    return "\n".join(lines)


def acquisition_card(img: AstroImage, sessions: list[DwarfSession],
                     path: str | Path, n_used: int | None = None) -> Path:
    """Export the image with a caption bar rendered underneath."""
    data = auto_stretch_display(img.data) if img.linear else np.clip(img.data, 0, 1)
    arr = (data * 255).astype(np.uint8)
    if arr.ndim == 2:
        arr = np.repeat(arr[..., None], 3, axis=2)
    h, w = arr.shape[:2]
    bar = max(70, h // 8)
    canvas = np.zeros((h + bar, w, 3), dtype=np.uint8)
    canvas[:h] = arr
    pil = Image.fromarray(canvas)
    draw = ImageDraw.Draw(pil)
    caption = acquisition_caption(sessions, n_used)
    lines = [ln for ln in caption.splitlines() if ln]
    y = h + 8
    for i, line in enumerate(lines):
        fill = (255, 255, 255) if i == 0 else (170, 170, 190)
        draw.text((12, y), line, fill=fill)
        y += max(12, (bar - 16) // max(len(lines), 1))
    pil.save(Path(path), quality=92)
    return Path(path)
