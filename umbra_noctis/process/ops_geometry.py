"""Geometry: crop, rotate, flip, resample, invert."""

from __future__ import annotations

import cv2
import numpy as np

from ..core.image import AstroImage
from ..core.ops import Param, register_op


@register_op(
    "crop", "Crop", "geometry",
    [Param("x", "int", 0, doc="Left edge (px)"),
     Param("y", "int", 0, doc="Top edge (px)"),
     Param("width", "int", 0, doc="Width; 0 = to the right edge"),
     Param("height", "int", 0, doc="Height; 0 = to the bottom edge")],
)
def crop(img: AstroImage, x: int = 0, y: int = 0, width: int = 0, height: int = 0) -> AstroImage:
    """Crop to a pixel rectangle. (The stacker's auto-crop handles stacking
    borders automatically; this is for framing.)"""
    h, w = img.height, img.width
    x = max(0, min(x, w - 2))
    y = max(0, min(y, h - 2))
    x1 = w if width <= 0 else min(w, x + width)
    y1 = h if height <= 0 else min(h, y + height)
    if x1 - x < 8 or y1 - y < 8:
        raise ValueError("crop too small")
    return img.with_data(img.data[y:y1, x:x1])


@register_op(
    "rotate", "Rotate", "geometry",
    [Param("degrees", "float", 0.0, -360.0, 360.0,
           "Counter-clockwise. Multiples of 90 are lossless"),
     Param("expand", "bool", True, doc="Grow canvas to fit instead of clipping corners")],
)
def rotate(img: AstroImage, degrees: float = 0.0, expand: bool = True) -> AstroImage:
    d = degrees % 360.0
    data = img.data
    if d == 0.0:
        return img.copy()
    if d in (90.0, 180.0, 270.0):
        out = np.rot90(data, k=int(d // 90), axes=(0, 1)).copy()
        return img.with_data(out)
    h, w = data.shape[:2]
    center = (w / 2.0, h / 2.0)
    m = cv2.getRotationMatrix2D(center, d, 1.0)
    if expand:
        cos, sin = abs(m[0, 0]), abs(m[0, 1])
        nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
        m[0, 2] += nw / 2 - center[0]
        m[1, 2] += nh / 2 - center[1]
        w, h = nw, nh
    out = cv2.warpAffine(data, m, (w, h), flags=cv2.INTER_LANCZOS4,
                         borderMode=cv2.BORDER_CONSTANT)
    return img.with_data(out)


@register_op(
    "flip", "Flip / mirror", "geometry",
    [Param("direction", "choice", "horizontal", choices=("horizontal", "vertical"))],
)
def flip(img: AstroImage, direction: str = "horizontal") -> AstroImage:
    axis = 1 if direction == "horizontal" else 0
    return img.with_data(np.flip(img.data, axis=axis).copy())


@register_op(
    "resize", "Resample", "geometry",
    [Param("scale", "float", 0.5, 0.05, 4.0, "Size multiplier (0.5 = half size)"),
     Param("method", "choice", "lanczos", choices=("lanczos", "cubic", "area"),
           doc="area is best for downsizing, lanczos for upsizing")],
)
def resize(img: AstroImage, scale: float = 0.5, method: str = "lanczos") -> AstroImage:
    """Resample the image. Downsizing 2× is also a cheap noise reduction —
    a good trick for web-bound Dwarf images."""
    interp = {"lanczos": cv2.INTER_LANCZOS4, "cubic": cv2.INTER_CUBIC,
              "area": cv2.INTER_AREA}[method]
    h, w = img.height, img.width
    out = cv2.resize(img.data, (max(8, int(w * scale)), max(8, int(h * scale))),
                     interpolation=interp)
    return img.with_data(out)


@register_op("invert", "Invert", "geometry", [])
def invert(img: AstroImage) -> AstroImage:
    """Negative view — surprisingly useful for spotting faint halos and
    gradient residuals during inspection."""
    return img.with_data(1.0 - img.data)
