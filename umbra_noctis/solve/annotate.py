"""Annotation: draw catalog object labels onto a solved (or pointed) image."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from ..core.image import AstroImage
from ..library.targets import NOTABLE
from ..process.display import auto_stretch_display
from .astrometry import DWARF3_SCALE_ARCSEC, SolveResult
from .catalog_coords import COORDS


def _angular_sep(ra1, dec1, ra2, dec2):
    """Great-circle separation in degrees."""
    ra1, dec1, ra2, dec2 = map(np.radians, (ra1, dec1, ra2, dec2))
    return float(np.degrees(np.arccos(np.clip(
        np.sin(dec1) * np.sin(dec2) + np.cos(dec1) * np.cos(dec2) * np.cos(ra1 - ra2),
        -1, 1))))


def objects_in_field(ra_deg: float, dec_deg: float,
                     radius_deg: float = 1.8) -> list[dict]:
    """Catalog objects within ``radius_deg`` of the field center."""
    found = []
    for name, (ra, dec) in COORDS.items():
        sep = _angular_sep(ra_deg, dec_deg, ra, dec)
        if sep <= radius_deg:
            friendly, kind = NOTABLE.get(name, ("", ""))
            found.append({"name": name, "friendly": friendly, "kind": kind,
                          "ra": ra, "dec": dec, "sep_deg": round(sep, 3)})
    return sorted(found, key=lambda o: o["sep_deg"])


def annotate_image(img: AstroImage, solve: SolveResult, out_path: str | Path,
                   radius_deg: float = 1.8) -> tuple[Path, list[dict]]:
    """Render the image with labels on every catalog object in the field.

    Uses the full WCS when the solver returned one; otherwise falls back to a
    simple tangent-plane approximation from the field center, scale, and
    rotation (good enough for labels on a 3° field).
    """
    if not solve.success or solve.ra_deg is None:
        raise ValueError("annotate_image needs a successful plate solve")

    data = auto_stretch_display(img.data) if img.linear else np.clip(img.data, 0, 1)
    arr = (data * 255).astype(np.uint8)
    if arr.ndim == 2:
        arr = np.repeat(arr[..., None], 3, axis=2)
    pil = Image.fromarray(arr)
    draw = ImageDraw.Draw(pil)
    h, w = arr.shape[:2]

    objects = objects_in_field(solve.ra_deg, solve.dec_deg, radius_deg)
    scale = (solve.scale_arcsec or DWARF3_SCALE_ARCSEC) / 3600.0  # deg/px
    rot = np.radians(solve.rotation_deg or 0.0)

    annotated = []
    for obj in objects:
        if solve.wcs is not None:
            try:
                x, y = solve.wcs.celestial.world_to_pixel_values(obj["ra"], obj["dec"])
            except Exception:
                continue
        else:
            dra = (obj["ra"] - solve.ra_deg) * np.cos(np.radians(solve.dec_deg))
            ddec = obj["dec"] - solve.dec_deg
            dx, dy = -dra / scale, -ddec / scale  # RA increases leftward
            x = w / 2 + dx * np.cos(rot) - dy * np.sin(rot)
            y = h / 2 + dx * np.sin(rot) + dy * np.cos(rot)
        if not (0 <= x < w and 0 <= y < h):
            continue
        r = 26
        draw.ellipse([x - r, y - r, x + r, y + r], outline=(120, 220, 255), width=2)
        label = obj["name"] + (f" — {obj['friendly']}" if obj["friendly"] else "")
        draw.text((x + r + 6, y - 8), label, fill=(120, 220, 255))
        annotated.append(obj)

    out_path = Path(out_path)
    pil.save(out_path, quality=92)
    return out_path, annotated
