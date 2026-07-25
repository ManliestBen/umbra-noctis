"""Star-trail and meteor composites: lighten (maximum-value) blending.

Deep-sky integration registers frames so the stars land on top of each other.
Trail stacking is the opposite discipline: the motion of the stars between
frames IS the picture, so frames are blended exactly as shot — every output
pixel keeps the brightest value it ever saw. The same blend composites a
night of meteor-shower frames into one image; pass ``align=True`` there so
the star field is registered first and the meteors land on a fixed sky.

Frames stream through two running accumulators (max, and a luminance min used
for hot-pixel detection), so a 400-frame DSLR night needs the memory of about
three frames, not four hundred.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..calib.masters import cosmetic_correction, subtract_dark
from ..core.image import FRAME_SUFFIXES, AstroImage
from .integrate import demosaic
from .register import solve_transform, warp


@dataclass
class TrailResult:
    image: AstroImage
    n_frames: int
    n_skipped: int
    n_hot_pixels: int
    log: list = field(default_factory=list)


def collect_frames(paths: list[str | Path]) -> list[Path]:
    """Expand a mix of files and folders into a sorted list of frame paths.

    Folders are scanned (non-recursively) for every supported format; files
    are taken as given. Sorting is by name, which for camera file numbering
    is chronological order.
    """
    frames: list[Path] = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            frames.extend(sorted(
                f for f in p.iterdir()
                if f.is_file() and f.suffix.lower() in FRAME_SUFFIXES))
        elif p.is_file():
            frames.append(p)
        else:
            raise FileNotFoundError(f"No such file or folder: {p}")
    return frames


def trail_stack(paths: list[str | Path], master_dark: AstroImage | None = None,
                align: bool = False, cosmetic: bool = True,
                demosaic_method: str = "ea",
                progress=None, log=None) -> TrailResult:
    """Lighten-blend ``paths`` into one composite.

    - ``master_dark``: subtracted from every frame (build it from cap-on
      frames shot at the same settings).
    - ``align=False`` (star trails): frames blend exactly as shot.
      ``align=True`` (meteor composites): each frame is registered to the
      first so stars stay put and only the meteors differ.
    - ``cosmetic``: when no dark is given, hot pixels are found statistically
      (bright in the per-pixel *minimum* of all frames — stars move, defects
      don't) and repaired in the result.
    """
    logs: list[str] = []

    def _log(msg: str):
        logs.append(msg)
        if log:
            log(msg)

    paths = [Path(p) for p in paths]
    if not paths:
        raise ValueError("No frames supplied")

    max_acc: np.ndarray | None = None
    min_lum: np.ndarray | None = None
    ref_img: AstroImage | None = None
    n_used = 0
    n_skipped = 0

    for i, path in enumerate(paths):
        try:
            img = AstroImage.from_file(path)
        except (ValueError, OSError) as exc:
            n_skipped += 1
            _log(f"SKIP {path.name}: {exc}")
            continue
        if img.cfa:
            img = demosaic(img, demosaic_method)
        if master_dark is not None and master_dark.data.shape == img.data.shape:
            img = subtract_dark(img, master_dark)

        if ref_img is None:
            ref_img = img
        elif img.data.shape != ref_img.data.shape:
            n_skipped += 1
            _log(f"SKIP {path.name}: shape {img.data.shape} != "
                 f"{ref_img.data.shape}")
            continue

        data = img.data
        if align and img is not ref_img:
            t = solve_transform(img, ref_img)
            data = warp(data, t)  # out-of-footprint pixels become NaN

        # fmax/fmin ignore NaN, so warped-in borders never darken the blend
        if max_acc is None:
            max_acc = np.nan_to_num(data, nan=0.0).copy()
            min_lum = img.luminance().copy()
        else:
            max_acc = np.fmax(max_acc, data)
            min_lum = np.fmin(min_lum, img.luminance())
        n_used += 1
        if progress:
            progress("blend", i + 1, len(paths))

    if ref_img is None or max_acc is None:
        raise ValueError("No readable frames in input")

    result = ref_img.with_data(np.clip(np.nan_to_num(max_acc, nan=0.0), 0.0, 1.0))

    n_hot = 0
    if cosmetic and master_dark is None and not align and n_used >= 3:
        med = float(np.median(min_lum))
        mad = float(np.median(np.abs(min_lum - med))) * 1.4826 + 1e-9
        hot = min_lum > med + 10.0 * mad
        n_hot = int(hot.sum())
        if 0 < n_hot < 0.01 * hot.size:
            result = cosmetic_correction(result, hot)
            _log(f"Repaired {n_hot} hot pixels (statistical, no dark needed)")
        else:
            n_hot = 0

    result.meta["n_frames"] = n_used
    exp = ref_img.meta.get("exposure_s")
    if exp:
        try:
            result.meta["total_integration_s"] = float(exp) * n_used
        except (TypeError, ValueError):
            pass
    result.record("trail_stack", {
        "n_frames": n_used, "n_skipped": n_skipped,
        "align": align, "dark": master_dark is not None,
    })
    _log(f"Blended {n_used} frames" +
         (f", skipped {n_skipped}" if n_skipped else ""))
    return TrailResult(image=result, n_frames=n_used, n_skipped=n_skipped,
                       n_hot_pixels=n_hot, log=logs)
