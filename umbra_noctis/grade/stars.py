"""Star detection.

Primary path uses ``sep`` (the SExtractor port that ships with astroalign).
A pure scipy fallback keeps the feature working if sep is unavailable.
Returns a structured array with columns: x, y, flux, fwhm, ellipticity.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

try:
    import sep as _sep
    _HAVE_SEP = True
except ImportError:  # pragma: no cover
    _HAVE_SEP = False

_DTYPE = np.dtype([("x", "f8"), ("y", "f8"), ("flux", "f8"),
                   ("fwhm", "f8"), ("ellipticity", "f8")])


def _luminance(data: np.ndarray) -> np.ndarray:
    if data.ndim == 3:
        return (0.2126 * data[..., 0] + 0.7152 * data[..., 1]
                + 0.0722 * data[..., 2]).astype(np.float32)
    return np.ascontiguousarray(data, dtype=np.float32)


def detect_stars(data: np.ndarray, threshold_sigma: float = 5.0,
                 max_stars: int = 500) -> np.ndarray:
    """Detect point sources; brightest ``max_stars`` returned, flux-sorted."""
    lum = _luminance(data)
    if _HAVE_SEP:
        try:
            return _detect_sep(lum, threshold_sigma, max_stars)
        except Exception:
            pass
    return _detect_scipy(lum, threshold_sigma, max_stars)


def _detect_sep(lum: np.ndarray, threshold_sigma: float, max_stars: int) -> np.ndarray:
    lum64 = lum.astype(np.float64)
    bkg = _sep.Background(lum64)
    sub = lum64 - bkg.back()
    objs = _sep.extract(sub, threshold_sigma, err=bkg.globalrms, minarea=5)
    out = np.zeros(len(objs), dtype=_DTYPE)
    out["x"], out["y"], out["flux"] = objs["x"], objs["y"], objs["flux"]
    # FWHM from second moments of a Gaussian profile; ellipticity = 1 - b/a
    sigma_eq = np.sqrt(np.maximum(objs["a"] * objs["b"], 1e-12))
    out["fwhm"] = 2.3548 * sigma_eq
    with np.errstate(divide="ignore", invalid="ignore"):
        out["ellipticity"] = 1.0 - np.where(objs["a"] > 0, objs["b"] / objs["a"], 1.0)
    order = np.argsort(out["flux"])[::-1]
    return _clean(out[order][:max_stars], lum.shape)


def _detect_scipy(lum: np.ndarray, threshold_sigma: float, max_stars: int) -> np.ndarray:
    med = float(np.median(lum))
    mad = float(np.median(np.abs(lum - med))) * 1.4826 + 1e-9
    mask = lum > med + threshold_sigma * mad
    labels, n = ndimage.label(mask)
    if n == 0:
        return np.zeros(0, dtype=_DTYPE)
    idx = np.arange(1, n + 1)
    sizes = ndimage.sum_labels(np.ones_like(lum), labels, idx)
    keep = idx[(sizes >= 4) & (sizes <= 2500)]
    if keep.size == 0:
        return np.zeros(0, dtype=_DTYPE)

    sub = np.clip(lum - med, 0, None)
    out = np.zeros(len(keep), dtype=_DTYPE)
    coms = ndimage.center_of_mass(sub, labels, keep)
    out["y"] = [c[0] for c in coms]
    out["x"] = [c[1] for c in coms]
    out["flux"] = ndimage.sum_labels(sub, labels, keep)

    # Second moments per source for FWHM / ellipticity
    for i, lab in enumerate(keep):
        ys, xs = np.nonzero(labels == lab)
        w = sub[ys, xs]
        wsum = w.sum() + 1e-12
        my, mx = out["y"][i], out["x"][i]
        cyy = np.sum(w * (ys - my) ** 2) / wsum
        cxx = np.sum(w * (xs - mx) ** 2) / wsum
        cxy = np.sum(w * (xs - mx) * (ys - my)) / wsum
        tr, det = cxx + cyy, cxx * cyy - cxy**2
        disc = max(tr * tr / 4 - det, 0.0)
        l1 = tr / 2 + np.sqrt(disc)
        l2 = max(tr / 2 - np.sqrt(disc), 1e-9)
        out["fwhm"][i] = 2.3548 * np.sqrt(max(np.sqrt(l1 * l2), 1e-9))
        out["ellipticity"][i] = 1.0 - np.sqrt(l2 / l1) if l1 > 0 else 0.0

    order = np.argsort(out["flux"])[::-1]
    return _clean(out[order][:max_stars], lum.shape)


def _clean(stars: np.ndarray, shape: tuple) -> np.ndarray:
    """Drop border sources and non-finite rows."""
    h, w = shape
    m = 8
    ok = (
        np.isfinite(stars["x"]) & np.isfinite(stars["y"]) & np.isfinite(stars["fwhm"])
        & (stars["x"] > m) & (stars["x"] < w - m)
        & (stars["y"] > m) & (stars["y"] < h - m)
    )
    return stars[ok]
