"""Integration: combine registered frames into one deep image.

The full pipeline lives in :func:`integrate`:

    lights -> (calibrate) -> (demosaic) -> grade -> register -> normalize
           -> reject outlier pixels -> weighted combine -> auto-crop

Pixel rejection uses winsorized sigma-clipping, which removes satellite
trails, cosmic rays, and hot pixels that survive calibration. Frames are
weighted by their quality score so a mediocre sub can help without hurting.

Memory strategy: registered frames are streamed into per-strip stacks so an
8 MP × 100-frame integration never needs the whole cube in RAM at once.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from ..calib.masters import (
    cosmetic_correction,
    hot_pixel_map,
    hot_pixels_from_lights,
    subtract_dark,
)
from ..core.image import AstroImage
from ..grade.metrics import FrameQuality, grade_frame, score_qualities
from .register import Transform, pick_reference, solve_transform, warp

_CV_BAYER = {
    # OpenCV pattern names refer to the 2×2 tile at (0,0) read as BGR order.
    "RGGB": cv2.COLOR_BayerBG2RGB,
    "BGGR": cv2.COLOR_BayerRG2RGB,
    "GRBG": cv2.COLOR_BayerGB2RGB,
    "GBRG": cv2.COLOR_BayerGR2RGB,
}


def demosaic(img: AstroImage, method: str = "ea") -> AstroImage:
    """CFA mosaic -> RGB. ``method``: "ea" (edge-aware, best), "vng", "bilinear"."""
    if not img.cfa or img.data.ndim != 2:
        return img
    code = _CV_BAYER[img.cfa]
    if method == "vng":
        code += cv2.COLOR_BayerBG2RGB_VNG - cv2.COLOR_BayerBG2RGB
    elif method == "ea":
        code += cv2.COLOR_BayerBG2RGB_EA - cv2.COLOR_BayerBG2RGB
    raw16 = (np.clip(img.data, 0, 1) * 65535).astype(np.uint16)
    rgb = cv2.cvtColor(raw16, code).astype(np.float32) / 65535.0
    out = img.with_data(rgb, cfa=None)
    out.record("demosaic", {"method": method, "pattern": img.cfa})
    return out


@dataclass
class StackResult:
    image: AstroImage
    n_used: int
    n_rejected_frames: int
    qualities: list = field(default_factory=list)
    transforms: list = field(default_factory=list)
    reference_index: int = 0
    rejected_pixel_fraction: float = 0.0
    log: list = field(default_factory=list)


def _normalize_to_ref(data: np.ndarray, ref_median: float, ref_scale: float) -> np.ndarray:
    med = np.nanmedian(data)
    mad = np.nanmedian(np.abs(data - med)) + 1e-9
    return (data - med) * (ref_scale / mad) + ref_median


def integrate(
    light_paths: list[str | Path],
    master_dark: AstroImage | None = None,
    master_flat: AstroImage | None = None,
    demosaic_method: str = "ea",
    rejection_sigma: float = 3.0,
    quality_filter: bool = True,
    best_fraction: float = 0.9,
    weighting: bool = True,
    normalize: bool = True,
    drizzle: float = 1.0,
    strip_rows: int = 128,
    qualities: list[FrameQuality] | None = None,
    progress=None,
    log=None,
) -> StackResult:
    """Full calibrate-register-integrate pipeline. See module docstring.

    ``drizzle=2.0`` integrates onto a 2× grid (needs many well-dithered subs).
    ``progress(stage, done, total)`` and ``log(str)`` are optional callbacks.
    ``qualities``, if given, must be the same length and order as
    ``light_paths`` (e.g. already computed by a Grade step) — supplying it
    skips re-grading every frame from scratch.
    """
    logs: list[str] = []

    def _log(msg: str):
        logs.append(msg)
        if log:
            log(msg)

    def _prog(stage, done, total):
        if progress:
            progress(stage, done, total)

    if not light_paths:
        raise ValueError("No light frames supplied")

    from ..calib.masters import apply_flat  # local import to avoid cycle

    # ---------------------------------------------------------- calibration
    hot_map = None
    if master_dark is not None:
        hot_map = hot_pixel_map(master_dark)
        _log(f"Master dark loaded; {int(hot_map.sum())} hot pixels mapped")
    else:
        hot_map = hot_pixels_from_lights(light_paths)
        _log(f"No dark — statistical hot-pixel map from lights: {int(hot_map.sum())} pixels")

    qualities_supplied = qualities is not None
    if qualities_supplied and len(qualities) != len(light_paths):
        raise ValueError(
            f"qualities has {len(qualities)} entries but light_paths has "
            f"{len(light_paths)} — they must be the same length and order")

    def _load_calibrated(path: str | Path) -> AstroImage:
        """Load one frame and apply dark/flat/cosmetic/demosaic calibration —
        the one calibration path shared by pass 1 (metrics only) and pass 2
        (integration), so a frame is never calibrated two different ways."""
        img = AstroImage.from_file(path)
        if master_dark is not None:
            img = subtract_dark(img, master_dark)
        if master_flat is not None:
            img = apply_flat(img, master_flat)
        if hot_map is not None and hot_map.shape == img.data.shape[:2]:
            img = cosmetic_correction(img, hot_map)
        if img.cfa:
            img = demosaic(img, demosaic_method)
        return img

    # --------------------------------------------------------- pass 1: grade
    # Only the FrameQuality survives each iteration — pixels are discarded
    # immediately, so this never holds more than one decoded frame at a time
    # regardless of session size.
    qualities = list(qualities) if qualities_supplied else []
    for i, path in enumerate(light_paths):
        if not qualities_supplied:
            img = _load_calibrated(path)
            qualities.append(grade_frame(img, path))
        _prog("calibrate", i + 1, len(light_paths))
    if not qualities_supplied:
        score_qualities(qualities)

    # ------------------------------------------------------- quality filter
    kept_idx = list(range(len(light_paths)))
    if quality_filter and len(light_paths) >= 5:
        # Re-run the session-relative rejection on already-computed metrics.
        n_stars = np.array([q.n_stars for q in qualities], dtype=float)
        star_med = max(np.nanmedian(n_stars), 1.0)
        fwhm = np.array([q.fwhm for q in qualities])
        med_f = np.nanmedian(fwhm)
        mad_f = np.nanmedian(np.abs(fwhm - med_f)) * 1.4826 + 1e-9
        bg = np.array([q.background for q in qualities])
        med_b = np.nanmedian(bg)
        mad_b = np.nanmedian(np.abs(bg - med_b)) * 1.4826 + 1e-9

        kept_idx = []
        for i, q in enumerate(qualities):
            reasons = []
            if q.n_stars < 0.3 * star_med:
                reasons.append("clouds")
            if np.isfinite(fwhm[i]) and fwhm[i] > med_f + 3.5 * mad_f:
                reasons.append("soft")
            if bg[i] > med_b + 3.5 * mad_b:
                reasons.append("bright sky")
            q.accepted = not reasons
            q.reject_reasons = reasons
            if q.accepted:
                kept_idx.append(i)
            else:
                _log(f"REJECT {Path(str(light_paths[i])).name}: {', '.join(reasons)}")
        # best-N% cut by score
        ranked = sorted(kept_idx, key=lambda i: -(qualities[i].score or 0))
        n_keep = max(3, int(round(len(ranked) * best_fraction)))
        kept_idx = sorted(ranked[:n_keep])
    if len(kept_idx) < 1:
        kept_idx = list(range(len(light_paths)))
        _log("Quality filter removed everything — keeping all frames instead")
    _log(f"Using {len(kept_idx)}/{len(light_paths)} frames")

    kept_paths = [light_paths[i] for i in kept_idx]
    used_q = [qualities[i] for i in kept_idx]
    n = len(kept_paths)

    # ---------------------------------------------------------- registration
    ref_local = pick_reference(used_q)

    # Reload the reference frame once, here at the start of pass 2: pass 1
    # discarded every frame's pixels, keeping only its FrameQuality, so the
    # reference's data is needed again both as the registration target below
    # and for the luminance normalization stats every other kept frame is
    # matched against.
    ref_img = _load_calibrated(kept_paths[ref_local])
    out_h = int(ref_img.height * drizzle)
    out_w = int(ref_img.width * drizzle)
    is_color = ref_img.is_color

    ref_lum = ref_img.luminance()
    ref_median = float(np.nanmedian(ref_lum))
    ref_scale = float(np.nanmedian(np.abs(ref_lum - ref_median))) + 1e-9

    weights = np.ones(n, dtype=np.float32)
    if weighting:
        scores = np.array([max(q.score, 1.0) for q in used_q], dtype=np.float32)
        weights = scores / scores.max()

    # --------------------------------------------------- pass 2: warp + write
    # One kept path at a time: reload, calibrate (same _load_calibrated as
    # pass 1), solve its transform against the already-loaded reference,
    # warp straight into the disk-backed memmap, then drop it. At no point
    # does this loop hold more than the reference frame plus the one frame
    # currently being processed.
    tmpdir = tempfile.TemporaryDirectory(prefix="umbra_stack_")
    shape = (n, out_h, out_w, 3) if is_color else (n, out_h, out_w)
    cube = np.memmap(Path(tmpdir.name) / "cube.dat", dtype=np.float32,
                     mode="w+", shape=shape)
    transforms: list[Transform] = []
    for i, path in enumerate(kept_paths):
        if i == ref_local:
            img, t = ref_img, Transform.identity()
        else:
            img = _load_calibrated(path)
            t = solve_transform(img, ref_img)
        transforms.append(t)
        _prog("register", i + 1, n)

        data = img.data
        if normalize and i != ref_local:
            data = _normalize_to_ref(data, ref_median, ref_scale)
        cube[i] = warp(data, t, order=1, output_shape=(out_h, out_w),
                       upscale=drizzle)
        _prog("integrate", i + 1, n + 1)
        del img, data

    solved = [t for t in transforms if t.method != "identity"]
    if solved:
        rot_span = max(abs(t.rotation_deg) for t in solved)
        _log(f"Registration: {sum(1 for t in solved if t.method == 'stars')} star-solved, "
             f"{sum(1 for t in solved if t.method == 'phase')} phase-only; "
             f"max field rotation {rot_span:.2f} deg")

    result = np.zeros(shape[1:], dtype=np.float32)
    rejected_px = 0
    total_px = 0
    w_col = weights.reshape(-1, *([1] * (len(shape) - 1)))
    for y0 in range(0, out_h, strip_rows):
        y1 = min(y0 + strip_rows, out_h)
        strip = np.asarray(cube[:, y0:y1])          # (n, rows, w[, 3])
        valid = np.isfinite(strip)
        med = np.nanmedian(strip, axis=0)
        # Robust sigma via MAD: a plain std is inflated by the very outliers
        # (satellite trails) we are trying to reject, hiding them at ~3.0 dev.
        std = 1.4826 * np.nanmedian(np.abs(strip - med[None]), axis=0) + 1e-5
        dev = np.abs(strip - med[None]) / std[None]
        keep = valid & (dev < rejection_sigma)
        # Winsorize: clamp rejected-but-valid samples to the clip boundary
        lo = med[None] - rejection_sigma * std[None]
        hi = med[None] + rejection_sigma * std[None]
        wins = np.clip(np.where(valid, strip, med[None]), lo, hi)
        wmask = np.where(valid, w_col, 0.0).astype(np.float32)
        # full weight where kept, quarter weight where winsorized
        wmask = np.where(keep, wmask, wmask * 0.25)
        denom = wmask.sum(axis=0)
        result[y0:y1] = np.where(denom > 0, (wins * wmask).sum(axis=0) / np.maximum(denom, 1e-9),
                                 med)
        rejected_px += int((valid & ~keep).sum())
        total_px += int(valid.sum())
    _prog("integrate", n + 1, n + 1)
    del cube
    tmpdir.cleanup()

    stacked = ref_img.with_data(np.clip(np.nan_to_num(result, nan=0.0), 0.0, 1.0))
    stacked.meta["n_stacked"] = n
    stacked.meta["total_integration_s"] = (
        float(ref_img.meta.get("exposure_s", 0) or 0) * n)
    stacked.record("integrate", {
        "n_frames": n, "rejection_sigma": rejection_sigma,
        "weighting": weighting, "normalize": normalize, "drizzle": drizzle,
    })

    stacked = auto_crop_borders(stacked, transforms, drizzle)
    frac = rejected_px / max(total_px, 1)
    _log(f"Pixel rejection removed {100 * frac:.2f}% of samples "
         f"(satellites/hot pixels/cosmic rays)")

    return StackResult(
        image=stacked,
        n_used=n,
        n_rejected_frames=len(light_paths) - n,
        qualities=qualities,
        transforms=transforms,
        reference_index=kept_idx[ref_local],
        rejected_pixel_fraction=frac,
        log=logs,
    )


def auto_crop_borders(img: AstroImage, transforms: list[Transform],
                      upscale: float = 1.0) -> AstroImage:
    """Crop to the region covered by EVERY registered frame, removing the
    rotated/dithered edges that alt-az stacking always produces."""
    h, w = img.height, img.width
    src_h, src_w = int(h / upscale), int(w / upscale)
    corners = np.array([[0, 0, 1], [src_w - 1, 0, 1],
                        [src_w - 1, src_h - 1, 1], [0, src_h - 1, 1]], dtype=float).T
    x0, y0, x1, y1 = 0.0, 0.0, float(w - 1), float(h - 1)
    for t in transforms:
        m = np.diag([upscale, upscale, 1.0]) @ t.matrix
        c = m @ corners
        xs, ys = c[0] / c[2], c[1] / c[2]
        # intersect: the frame covers [min_x, max_x]; conservative inner box
        x0 = max(x0, np.sort(xs)[1])
        y0 = max(y0, np.sort(ys)[1])
        x1 = min(x1, np.sort(xs)[2])
        y1 = min(y1, np.sort(ys)[2])
    ix0, iy0 = int(np.ceil(max(0, x0))), int(np.ceil(max(0, y0)))
    ix1, iy1 = int(np.floor(min(w - 1, x1))), int(np.floor(min(h - 1, y1)))
    if ix1 - ix0 < w // 2 or iy1 - iy0 < h // 2:
        return img  # refuse pathological crops
    out = img.with_data(img.data[iy0:iy1 + 1, ix0:ix1 + 1])
    out.record("auto_crop", {"box": [ix0, iy0, ix1, iy1]})
    return out
