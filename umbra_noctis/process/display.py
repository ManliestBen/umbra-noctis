"""Screen-transfer function: non-destructive autostretch for DISPLAY only.

Linear astro data looks almost black on a monitor. Every viewer in Umbra
Noctis renders through this function while the underlying data stays linear —
the same idea as PixInsight's STF or Siril's autostretch.
"""

from __future__ import annotations

import numpy as np

from ..core.stats import robust_sigma


def compute_stf(data: np.ndarray, target_background: float = 0.25,
                shadow_clip: float = -2.8) -> tuple[float, float, float]:
    """Return (shadows, midtones, highlights) for a midtone-transfer stretch,
    computed from the image statistics (median + MAD)."""
    lum = data if data.ndim == 2 else data.mean(axis=2)
    med = float(np.median(lum))
    mad = robust_sigma(lum, eps=1e-9)
    shadows = max(0.0, med + shadow_clip * mad)
    highlights = 1.0
    x = med - shadows
    m = _mtf_solve(x / max(highlights - shadows, 1e-9), target_background)
    return shadows, m, highlights


def _mtf(x: np.ndarray | float, m: float):
    """Midtone transfer function."""
    x = np.clip(x, 0.0, 1.0)
    return ((m - 1.0) * x) / (((2.0 * m - 1.0) * x) - m + 1e-12)


def _mtf_solve(x: float, y: float) -> float:
    """Solve for midtones m such that mtf(x, m) = y."""
    if x <= 0:
        return 0.5
    return (x * (y - 1.0)) / ((2.0 * y - 1.0) * x - y + 1e-12)


def apply_stf(data: np.ndarray, shadows: float, midtones: float,
              highlights: float) -> np.ndarray:
    x = (data - shadows) / max(highlights - shadows, 1e-9)
    return np.clip(_mtf(x, midtones), 0.0, 1.0)


def auto_stretch_display(data: np.ndarray, linked: bool = True,
                         target_background: float = 0.25) -> np.ndarray:
    """Autostretched copy of ``data`` for display. ``linked=False`` stretches
    RGB channels independently (useful pre-color-calibration)."""
    if data.ndim == 3 and not linked:
        return np.stack([auto_stretch_display(data[..., c], True, target_background)
                         for c in range(3)], axis=-1)
    s, m, h = compute_stf(data, target_background)
    return apply_stf(data, s, m, h)
