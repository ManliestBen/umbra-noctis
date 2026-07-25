"""Calibration: master frames, dark subtraction, flats, and defect repair.

Umbra Noctis is built for smart-telescope reality: darks are often available
(the Dwarf 3 can shoot them), flats usually are not. Every light-frame path
therefore works in three tiers:

1. full calibration (darks + flats) when masters exist,
2. dark-only calibration,
3. no calibration at all — statistical hot-pixel repair keeps stacks clean.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
from scipy import ndimage

from ..core.image import AstroImage
from ..core.stats import robust_sigma

_MASTER_STRIP_ROWS = 64


def build_master(paths: list[str | Path], method: str = "sigma_clip",
                 sigma: float = 3.0, progress=None) -> AstroImage:
    """Combine calibration frames (darks/flats/bias) into a master.

    ``method``: "median" (robust, default for few frames), "mean", or
    "sigma_clip" (mean after iterative outlier rejection — best with ≥8 frames).

    Memory: ``mean`` never holds more than one frame plus a running float64
    accumulator; ``median``/``sigma_clip`` need every sample per pixel to
    reduce, so frames are streamed into a disk-backed memmap cube and reduced
    in row-strips rather than held as one in-RAM stack (~5x a frame's size
    for a typical calibration set, more for large ones).
    """
    if not paths:
        raise ValueError("No frames given")

    method_eff = "median" if (method == "median" or len(paths) < 4) else method

    ref: AstroImage | None = None
    shape0: tuple | None = None

    def _load_checked(p):
        nonlocal ref, shape0
        img = AstroImage.from_file(p)
        if ref is None:
            ref = img
            shape0 = img.data.shape
        elif img.data.shape != shape0:
            raise ValueError(
                f"Calibration frames must all share one shape: {paths[0]} is "
                f"{shape0} but {p} is {img.data.shape}")
        return img

    if method_eff == "mean":
        acc: np.ndarray | None = None
        for i, p in enumerate(paths):
            img = _load_checked(p)
            frame = img.data.astype(np.float64)
            acc = frame if acc is None else acc + frame
            if progress:
                progress(i + 1, len(paths))
        master = (acc / len(paths)).astype(np.float32)
    else:
        with tempfile.TemporaryDirectory(prefix="umbra_master_") as tmpdir_name:
            cube = None
            try:
                for i, p in enumerate(paths):
                    img = _load_checked(p)
                    if cube is None:
                        shape = (len(paths),) + shape0
                        cube = np.memmap(Path(tmpdir_name) / "cube.dat", dtype=np.float32,
                                         mode="w+", shape=shape)
                    cube[i] = img.data
                    if progress:
                        progress(i + 1, len(paths))

                master = np.zeros(shape0, dtype=np.float32)
                for y0 in range(0, shape0[0], _MASTER_STRIP_ROWS):
                    y1 = min(y0 + _MASTER_STRIP_ROWS, shape0[0])
                    strip = np.asarray(cube[:, y0:y1])
                    if method_eff == "median":
                        master[y0:y1] = np.median(strip, axis=0)
                    else:  # sigma_clip
                        med = np.median(strip, axis=0)
                        std = strip.std(axis=0) + 1e-9
                        mask = np.abs(strip - med) < sigma * std
                        weights = mask.astype(np.float32)
                        wsum = weights.sum(axis=0)
                        weighted_mean = (strip * weights).sum(axis=0) / np.maximum(wsum, 1.0)
                        # A pixel rejected in every sample has no weighted mean
                        # to fall back on — use the (unweighted) median instead
                        # of silently going to 0.
                        master[y0:y1] = np.where(wsum > 0, weighted_mean, med)
            finally:
                del cube

    out = ref.with_data(master.astype(np.float32))
    out.meta["n_frames"] = len(paths)
    out.record("build_master", {"method": method, "n": len(paths), "sigma": sigma})
    return out


def subtract_dark(light: AstroImage, master_dark: AstroImage,
                  scale: float | None = None) -> AstroImage:
    """Subtract a master dark from a light frame.

    ``scale=None`` auto-scales when exposures differ (dark current is roughly
    linear in exposure time); pass 1.0 to force an exact subtraction.
    """
    if light.data.shape != master_dark.data.shape:
        raise ValueError(
            f"Dark shape {master_dark.data.shape} != light shape {light.data.shape}")
    if scale is None:
        le = light.meta.get("exposure_s")
        de = master_dark.meta.get("exposure_s")
        try:
            scale = float(le) / float(de) if le and de and float(de) > 0 else 1.0
        except (TypeError, ValueError):
            scale = 1.0
    data = np.clip(light.data - scale * master_dark.data, 0.0, 1.0)
    out = light.with_data(data)
    out.record("subtract_dark", {"scale": round(float(scale), 4)})
    return out


def apply_flat(light: AstroImage, master_flat: AstroImage) -> AstroImage:
    """Divide a light frame by a normalized master flat (vignetting/dust fix)."""
    flat = master_flat.data
    norm = flat / max(float(np.median(flat)), 1e-6)
    norm = np.clip(norm, 0.2, 5.0)  # never divide by ~0 at dead pixels
    out = light.with_data(np.clip(light.data / norm, 0.0, 1.0))
    out.record("apply_flat", {})
    return out


def hot_pixel_map(master_dark: AstroImage, k: float = 8.0) -> np.ndarray:
    """Boolean map of hot pixels: dark value > median + k·MAD."""
    d = master_dark.data if master_dark.data.ndim == 2 else master_dark.luminance()
    med = float(np.median(d))
    mad = robust_sigma(d, eps=1e-9)
    return d > med + k * mad


def hot_pixels_from_lights(paths: list[str | Path], k: float = 10.0,
                           sample: int = 5) -> np.ndarray:
    """No-darks fallback: pixels hot in the *minimum* of several lights are
    defects, not stars (stars move between frames; defects don't)."""
    picks = list(paths)[:: max(1, len(paths) // sample)][:sample]
    minimum = None
    for p in picks:
        d = AstroImage.from_file(p).data
        if d.ndim == 3:
            d = d.mean(axis=2)
        minimum = d if minimum is None else np.minimum(minimum, d)
    med = float(np.median(minimum))
    mad = robust_sigma(minimum, eps=1e-9)
    return minimum > med + k * mad


def cosmetic_correction(img: AstroImage, defect_map: np.ndarray) -> AstroImage:
    """Replace defective pixels with the local 3×3 median (CFA-safe: on CFA
    data a 5×5 same-color median is used instead)."""
    data = img.data.copy()
    if img.cfa and data.ndim == 2:
        # same-color neighbors on a Bayer mosaic live 2 pixels away
        med = ndimage.median_filter(data, footprint=_cfa_footprint())
    elif data.ndim == 3:
        med = np.stack([ndimage.median_filter(data[..., c], size=3) for c in range(3)], axis=-1)
        data[defect_map, :] = med[defect_map, :]
        out = img.with_data(data)
        out.record("cosmetic_correction", {"n_pixels": int(defect_map.sum())})
        return out
    else:
        med = ndimage.median_filter(data, size=3)
    data[defect_map] = med[defect_map]
    out = img.with_data(data)
    out.record("cosmetic_correction", {"n_pixels": int(defect_map.sum())})
    return out


def _cfa_footprint() -> np.ndarray:
    fp = np.zeros((5, 5), dtype=bool)
    fp[0, 0] = fp[0, 2] = fp[0, 4] = True
    fp[2, 0] = fp[2, 4] = True
    fp[4, 0] = fp[4, 2] = fp[4, 4] = True
    return fp


def synthetic_flat(img: AstroImage, box: int = 64) -> AstroImage:
    """Build a synthetic flat from a (stacked) light itself.

    Estimates the large-scale illumination surface by taking a low percentile
    in coarse boxes (stars ignored), smoothing heavily, and normalizing. Good
    for correcting Dwarf 3 vignetting when no real flats exist. Returns the
    flat itself; divide with :func:`apply_flat`.
    """
    lum = img.luminance()
    h, w = lum.shape
    ny, nx = max(6, h // box), max(6, w // box)
    samples, sy, sx = [], [], []
    for iy in range(ny):
        for ix in range(nx):
            y0, y1 = iy * h // ny, (iy + 1) * h // ny
            x0, x1 = ix * w // nx, (ix + 1) * w // nx
            # Median per box: robust to stars (few pixels) yet unbiased in a
            # gradient, unlike a low percentile which undershoots at corners.
            samples.append(np.percentile(lum[y0:y1, x0:x1], 50))
            sy.append((y0 + y1) / 2.0)
            sx.append((x0 + x1) / 2.0)
    # Vignetting is smooth and radial: fit a 2nd-degree 2-D polynomial
    # (1, x, y, x², xy, y²) to the star-free box samples.
    sxn = (np.array(sx) - w / 2) / w
    syn = (np.array(sy) - h / 2) / h
    A = np.stack([np.ones_like(sxn), sxn, syn, sxn**2, sxn * syn, syn**2], axis=1)
    coef, *_ = np.linalg.lstsq(A, np.array(samples), rcond=None)
    yy, xx = np.mgrid[0:h, 0:w]
    xxn = (xx - w / 2) / w
    yyn = (yy - h / 2) / h
    flat = (coef[0] + coef[1] * xxn + coef[2] * yyn
            + coef[3] * xxn**2 + coef[4] * xxn * yyn + coef[5] * yyn**2)
    flat = np.clip(flat / max(float(np.median(flat)), 1e-6), 0.2, 5.0)
    if img.is_color:
        flat = np.repeat(flat[..., None], 3, axis=2)
    out = img.with_data(flat.astype(np.float32))
    out.record("synthetic_flat", {"box": box})
    return out
