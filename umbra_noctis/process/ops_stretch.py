"""Stretching: the transition from linear data to a viewable image.

Umbra Noctis offers four stretch families, mildest to most controllable:
arcsinh (best color preservation), histogram/midtone (classic), GHS
(generalized hyperbolic — modern standard, most control), and autostretch
(applies the display STF permanently as a starting point).
"""

from __future__ import annotations

import numpy as np
from scipy.interpolate import PchipInterpolator

from ..core.image import AstroImage
from ..core.ops import Param, register_op
from .display import apply_stf, compute_stf


@register_op(
    "autostretch", "Auto-stretch (permanent STF)", "stretch",
    [Param("target_background", "float", 0.22, 0.05, 0.5, "Post-stretch sky level"),
     Param("linked", "bool", True, doc="Stretch channels together (keep color) or "
           "separately (also neutralizes color casts)")],
)
def autostretch(img: AstroImage, target_background: float = 0.22,
                linked: bool = True) -> AstroImage:
    """Apply the same statistics-driven stretch the screen preview uses,
    permanently. A reliable one-click starting point for any stack."""
    data = img.data
    if img.is_color and not linked:
        out = np.stack([apply_stf(data[..., c], *compute_stf(data[..., c], target_background))
                        for c in range(3)], axis=-1)
    else:
        s, m, h = compute_stf(data, target_background)
        out = apply_stf(data, s, m, h)
    return img.with_data(out, linear=False)


@register_op(
    "histogram_stretch", "Histogram (midtone) stretch", "stretch",
    [Param("shadows", "float", 0.0, 0.0, 0.99, "Black point (clips below)"),
     Param("midtones", "float", 0.5, 0.001, 0.999,
           "Midtone balance: <0.5 brightens, >0.5 darkens"),
     Param("highlights", "float", 1.0, 0.01, 1.0, "White point")],
)
def histogram_stretch(img: AstroImage, shadows: float = 0.0, midtones: float = 0.5,
                      highlights: float = 1.0) -> AstroImage:
    """The classic three-slider stretch (identical math to PixInsight's
    HistogramTransformation). Iterate gently: several small stretches beat
    one aggressive one."""
    out = apply_stf(img.data, shadows, midtones, highlights)
    return img.with_data(out, linear=False)


@register_op(
    "ghs", "Generalized hyperbolic stretch", "stretch",
    [Param("amount", "float", 5.0, 0.0, 15.0, "Stretch intensity (D)"),
     Param("focus", "float", 0.0, 0.0, 1.0,
           "Symmetry point SP: intensity level that gets the most contrast "
           "(set near the background level to lift faint nebulosity)"),
     Param("protect_shadows", "float", 0.0, 0.0, 1.0, "LP: keep contrast out of "
           "levels below this"),
     Param("protect_highlights", "float", 1.0, 0.0, 1.0, "HP: compress above this "
           "(protects star cores)")],
)
def ghs(img: AstroImage, amount: float = 5.0, focus: float = 0.0,
        protect_shadows: float = 0.0, protect_highlights: float = 1.0) -> AstroImage:
    """Generalized Hyperbolic Stretch (Honours/Payne GHS).

    The modern astro stretch: `focus` aims the contrast budget at a chosen
    brightness level, while the protect parameters spare shadows and star
    cores. Typical deep-sky use: focus just above the sky background,
    protect_highlights ~0.7, amount 3–8, applied in 2–3 passes.
    """
    D = float(amount)
    if D <= 0:
        return img.copy()
    b = 6.0  # local-intensity exponent; fixed, D dominates the look
    SP = float(np.clip(focus, 0.0, 1.0))
    LP = float(np.clip(protect_shadows, 0.0, SP))
    HP = float(np.clip(protect_highlights, SP, 1.0))

    def T(x):
        # piecewise GHS transform (type: hyperbolic/harmonic b>0)
        x = np.clip(x, 0.0, 1.0)
        q0 = (1 + D * b * (SP - LP)) ** (-1 / b)
        qwp = 2 - (1 + D * b * (HP - SP)) ** (-1 / b)
        q1 = qwp + (1 - HP) * D * (1 + D * b * (HP - SP)) ** (-(1 + b) / b)
        q = np.empty_like(x)
        m0 = x < LP
        m1 = (~m0) & (x < SP)
        m2 = (~m0) & (~m1) & (x < HP)
        m3 = x >= HP
        a0 = D * (1 + D * b * (SP - LP)) ** (-(1 + b) / b)
        q[m0] = q0 + (x[m0] - LP) * a0
        q[m1] = (1 + D * b * (SP - x[m1])) ** (-1 / b)
        q[m2] = 2 - (1 + D * b * (x[m2] - SP)) ** (-1 / b)
        a3 = D * (1 + D * b * (HP - SP)) ** (-(1 + b) / b)
        q[m3] = qwp + (x[m3] - HP) * a3
        return (q - q0) / max(q1 - q0, 1e-12)

    return img.with_data(np.clip(T(img.data), 0.0, 1.0), linear=False)


@register_op(
    "arcsinh", "Arcsinh stretch", "stretch",
    [Param("factor", "float", 30.0, 1.0, 1000.0, "Stretch factor (log-ish scale)"),
     Param("black_point", "float", 0.0, 0.0, 0.5, "Subtract before stretching")],
)
def arcsinh(img: AstroImage, factor: float = 30.0, black_point: float = 0.0) -> AstroImage:
    """Color-preserving stretch: scales R, G, B by the same luminance-derived
    factor, so star colors survive where a plain histogram stretch would
    bleach them white. Great first stretch for star fields and clusters."""
    data = np.clip(img.data - black_point, 0.0, 1.0)
    if img.is_color:
        lum = 0.2126 * data[..., 0] + 0.7152 * data[..., 1] + 0.0722 * data[..., 2]
        stretched = np.arcsinh(factor * lum) / np.arcsinh(factor)
        ratio = np.where(lum > 1e-9, stretched / np.maximum(lum, 1e-9), 0.0)
        out = data * ratio[..., None]
    else:
        out = np.arcsinh(factor * data) / np.arcsinh(factor)
    return img.with_data(np.clip(out, 0.0, 1.0), linear=False)


def _parse_points(points: str) -> tuple[np.ndarray, np.ndarray]:
    """Parse a ``'x0,y0;x1,y1;...'`` control-point string. Duplicate x values
    are deduped (last one wins) rather than raising, since PchipInterpolator
    requires strictly increasing x. Raises a ValueError with a format hint on
    any parse failure, distinct from the "need at least 2 points" case."""
    try:
        by_x: dict[float, float] = {}
        for chunk in points.split(";"):
            x_str, y_str = chunk.split(",")
            by_x[float(x_str)] = float(y_str)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"curves: points must look like '0,0;0.5,0.6;1,1' — got {points!r}"
        ) from exc
    if len(by_x) < 2:
        raise ValueError("curves: need at least 2 control points")
    xs_sorted = sorted(by_x)
    return np.array(xs_sorted), np.array([by_x[x] for x in xs_sorted])


@register_op(
    "curves", "Curves", "nonlinear",
    [Param("points", "str", "0,0;0.5,0.5;1,1",
           doc="Semicolon-separated x,y control points, e.g. '0,0;0.25,0.2;0.7,0.8;1,1'"),
     Param("channel", "choice", "all", choices=("all", "r", "g", "b", "saturation"),
           doc="What the curve drives")],
)
def curves(img: AstroImage, points: str = "0,0;0.5,0.5;1,1",
           channel: str = "all") -> AstroImage:
    """Classic monotone-spline curves. An S-shape adds contrast; lifting only
    the lower-mid region brightens nebulosity. The 'saturation' channel
    applies the curve to color saturation instead of brightness."""
    xs, ys = _parse_points(points)
    spline = PchipInterpolator(xs, ys, extrapolate=True)

    def apply(v):
        return np.clip(spline(np.clip(v, 0.0, 1.0)), 0.0, 1.0).astype(np.float32)

    data = img.data.copy()
    if channel == "all" or not img.is_color:
        data = apply(data)
    elif channel in ("r", "g", "b"):
        c = "rgb".index(channel)
        data[..., c] = apply(data[..., c])
    else:  # saturation
        lum = img.luminance()[..., None]
        sat = data - lum
        mag = np.abs(sat).max(axis=2, keepdims=True)
        scale = np.where(mag > 1e-9, apply(np.clip(mag, 0, 1)) / np.maximum(mag, 1e-9), 1.0)
        data = np.clip(lum + sat * scale, 0.0, 1.0)
    return img.with_data(data, linear=img.linear and channel == "saturation")
