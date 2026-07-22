"""Color operations, including the Dwarf 3's killer feature: dual-band
narrowband extraction from the built-in Hα/OIII filter."""

from __future__ import annotations

import numpy as np

from ..core.image import AstroImage
from ..core.ops import Param, register_op


@register_op(
    "saturation", "Saturation / vibrance", "nonlinear",
    [Param("amount", "float", 1.3, 0.0, 3.0, "1 = unchanged, >1 boosts"),
     Param("vibrance", "bool", True, doc="Protect already-saturated pixels and "
           "boost muted ones (safer than raw saturation)"),
     Param("luminance_protect", "float", 0.15, 0.0, 0.5,
           "Don't saturate the darkest sky (keeps noise monochrome)")],
)
def saturation(img: AstroImage, amount: float = 1.3, vibrance: bool = True,
               luminance_protect: float = 0.15) -> AstroImage:
    """Boost color. Use after stretching. Vibrance mode is the default
    because plain saturation quickly clips nebula cores to neon."""
    if not img.is_color:
        return img.copy()
    data = img.data
    lum = img.luminance()[..., None]
    chroma = data - lum
    if vibrance:
        sat_now = np.abs(chroma).max(axis=2, keepdims=True)
        boost = 1.0 + (amount - 1.0) * (1.0 - np.clip(sat_now * 4.0, 0.0, 1.0))
    else:
        boost = amount
    mask = np.clip(lum / max(luminance_protect, 1e-6), 0.0, 1.0)
    out = lum + chroma * (1.0 + (boost - 1.0) * mask)
    return img.with_data(np.clip(out, 0.0, 1.0))


@register_op(
    "hue_shift", "Selective hue rotation", "nonlinear",
    [Param("degrees", "float", 0.0, -180.0, 180.0, "Rotate all hues by this angle")],
)
def hue_shift(img: AstroImage, degrees: float = 0.0) -> AstroImage:
    """Rotate hues (e.g. to tune a dual-band palette). Simple RGB rotation
    about the gray axis; luminance is preserved."""
    if not img.is_color or degrees == 0.0:
        return img.copy()
    theta = np.deg2rad(degrees)
    c, s = np.cos(theta), np.sin(theta)
    one3 = 1.0 / 3.0
    sq3 = np.sqrt(1.0 / 3.0)
    m = np.array([
        [c + (1 - c) * one3, one3 * (1 - c) - sq3 * s, one3 * (1 - c) + sq3 * s],
        [one3 * (1 - c) + sq3 * s, c + one3 * (1 - c), one3 * (1 - c) - sq3 * s],
        [one3 * (1 - c) - sq3 * s, one3 * (1 - c) + sq3 * s, c + one3 * (1 - c)],
    ])
    out = img.data @ m.T
    return img.with_data(np.clip(out, 0.0, 1.0))


@register_op(
    "dualband_extract", "Dual-band Hα/OIII extraction", "linear",
    [Param("palette", "choice", "HOO", choices=("HOO", "OHH", "HA", "OIII"),
           doc="HOO = Hα→red, OIII→green+blue (natural bicolor). "
               "HA/OIII output the raw extracted channel as mono"),
     Param("ha_boost", "float", 1.0, 0.2, 4.0, "Hα channel gain"),
     Param("oiii_boost", "float", 1.0, 0.2, 4.0, "OIII channel gain")],
)
def dualband_extract(img: AstroImage, palette: str = "HOO", ha_boost: float = 1.0,
                     oiii_boost: float = 1.0) -> AstroImage:
    """Turn a session shot through the Dwarf 3's built-in dual-band filter
    into a narrowband-style image.

    Through that filter, the sensor's red pixels see almost pure Hα and the
    green/blue pixels see almost pure OIII — so R becomes a synthetic Hα
    channel and a weighted G+B average becomes OIII. Backgrounds are
    equalized before combination. Run on LINEAR stacked data, then stretch.
    """
    if not img.is_color:
        raise ValueError("dualband_extract needs an RGB image from a dual-band session")
    r = img.data[..., 0].astype(np.float64)
    g = img.data[..., 1].astype(np.float64)
    b = img.data[..., 2].astype(np.float64)
    ha = r
    oiii = 0.6 * g + 0.4 * b   # G carries more OIII signal than B on IMX678

    def bg(x):
        return float(np.median(x))

    # equalize backgrounds, apply user gains
    target = min(bg(ha), bg(oiii))
    ha = np.clip((ha - bg(ha) + target) * ha_boost, 0.0, 1.0)
    oiii = np.clip((oiii - bg(oiii) + target) * oiii_boost, 0.0, 1.0)

    if palette == "HA":
        return img.with_data(ha.astype(np.float32))
    if palette == "OIII":
        return img.with_data(oiii.astype(np.float32))
    if palette == "HOO":
        out = np.stack([ha, oiii, oiii], axis=-1)
    else:  # OHH — inverted bicolor for variety
        out = np.stack([oiii, ha, ha], axis=-1)
    return img.with_data(np.clip(out, 0.0, 1.0).astype(np.float32))
