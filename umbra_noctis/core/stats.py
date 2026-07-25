"""Shared robust statistics used across grading, calibration, and stacking.

Every module that estimated a noise/scale value via ``median + 1.4826 *
MAD`` used to hand-roll it separately, each with its own (sometimes
missing) epsilon. This is the one place that pattern lives now.
"""

from __future__ import annotations

import numpy as np

MAD_TO_SIGMA = 1.4826  # scales the median absolute deviation to a Gaussian sigma


def median_mad(a, axis=None):
    """Return ``(median, mad)`` — the median and the *unscaled* median
    absolute deviation from it, along ``axis`` (the whole array by default).

    Uses NaN-aware reductions throughout, so a few non-finite samples don't
    poison the whole estimate.
    """
    a = np.asarray(a)
    med = np.nanmedian(a, axis=axis)
    if axis is None:
        mad = np.nanmedian(np.abs(a - med))
    else:
        mad = np.nanmedian(np.abs(a - np.expand_dims(med, axis=axis)), axis=axis)
    return med, mad


def robust_sigma(a, axis=None, eps: float = 1e-9):
    """Robust standard-deviation estimate: ``MAD_TO_SIGMA * MAD + eps``.

    The ``eps`` offset keeps the result away from exactly zero on
    perfectly flat input, so callers can safely divide by it.
    """
    _, mad = median_mad(a, axis=axis)
    return mad * MAD_TO_SIGMA + eps


def robust_z(values, eps: float = 1e-12) -> np.ndarray:
    """Robust z-score: ``(x - median) / (MAD_TO_SIGMA * MAD)``.

    Returns all-zero when the spread is degenerate (near-constant data)
    rather than dividing by ~0.
    """
    values = np.asarray(values, dtype=float)
    med, mad = median_mad(values)
    sigma = mad * MAD_TO_SIGMA
    if not np.isfinite(sigma) or sigma < eps:
        return np.zeros_like(values)
    return (values - med) / sigma
