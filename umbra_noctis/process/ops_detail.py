"""Detail and star operations: sharpening, local contrast, HDR compression,
star masks, star reduction."""

from __future__ import annotations

import cv2
import numpy as np

from ..core.image import AstroImage
from ..core.ops import Param, register_op
from ..grade.stars import detect_stars
from .ops_linear import _starlet_scales


def build_star_mask(img: AstroImage, grow: float = 2.0,
                    threshold_sigma: float = 4.0) -> np.ndarray:
    """Soft 0..1 mask that is 1 on stars, 0 elsewhere. Used to protect stars
    from (or restrict ops to) sharpening/reduction."""
    lum = img.luminance()
    stars = detect_stars(lum, threshold_sigma=threshold_sigma, max_stars=2000)
    mask = np.zeros_like(lum, dtype=np.float32)
    h, w = mask.shape
    for s in stars:
        r = max(2.0, s["fwhm"] * grow)
        x, y = s["x"], s["y"]
        x0, x1 = int(max(0, x - 3 * r)), int(min(w, x + 3 * r + 1))
        y0, y1 = int(max(0, y - 3 * r)), int(min(h, y + 3 * r + 1))
        if x1 <= x0 or y1 <= y0:
            continue
        yy, xx = np.mgrid[y0:y1, x0:x1]
        g = np.exp(-(((xx - x) ** 2 + (yy - y) ** 2) / (2 * (r / 1.5) ** 2)))
        mask[y0:y1, x0:x1] = np.maximum(mask[y0:y1, x0:x1], g.astype(np.float32))
    return np.clip(mask, 0.0, 1.0)


@register_op(
    "star_reduce", "Star reduction", "nonlinear",
    [Param("amount", "float", 0.5, 0.0, 1.0, "0 = off, 1 = maximum shrink"),
     Param("grow", "float", 2.0, 1.0, 5.0, "Star mask size multiplier")],
)
def star_reduce(img: AstroImage, amount: float = 0.5, grow: float = 2.0) -> AstroImage:
    """Shrink stars so the nebula/galaxy becomes the subject. Morphological
    erosion blended in only under a star mask — the background is untouched.
    Run AFTER stretching. For full star removal, export a 16-bit TIFF
    (umbra process ... -o starless-input.tif), run an external
    StarNet++/GraXpert on it, and re-import the result."""
    if amount <= 0:
        return img.copy()
    mask = build_star_mask(img, grow=grow)
    if img.is_color:
        mask3 = mask[..., None]
    else:
        mask3 = mask
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    eroded = img.data.copy()
    for _ in range(2):
        eroded = cv2.erode(eroded, kernel)
    eroded = cv2.GaussianBlur(eroded, (3, 3), 0)
    if eroded.ndim == 2 and img.is_color:  # cv2 collapses (h,w,1)
        eroded = eroded[..., None].repeat(3, axis=2)
    out = img.data * (1 - amount * mask3) + eroded * (amount * mask3)
    return img.with_data(np.clip(out, 0.0, 1.0))


@register_op(
    "sharpen", "Multiscale sharpening", "nonlinear",
    [Param("amount", "float", 0.5, 0.0, 2.0, "Boost for the detail scales"),
     Param("scale", "choice", "medium", choices=("fine", "medium", "large"),
           doc="Which structure size to emphasize"),
     Param("protect_stars", "bool", True, doc="Exclude stars (avoids halos)")],
)
def sharpen(img: AstroImage, amount: float = 0.5, scale: str = "medium",
            protect_stars: bool = True) -> AstroImage:
    """Wavelet-scale sharpening (the RegiStax idea, applied to deep-sky).
    Boosts the chosen starlet scale instead of naive unsharp masking, so it
    lifts real structure with less noise amplification. Use after stretch."""
    if amount <= 0:
        return img.copy()
    boost_idx = {"fine": 1, "medium": 2, "large": 3}[scale]
    mask = None
    if protect_stars:
        mask = 1.0 - build_star_mask(img)

    def _one(plane):
        scales = _starlet_scales(plane, 4)
        scales[boost_idx] = scales[boost_idx] * (1.0 + amount)
        # tiny boost on the neighbor scale for a natural look
        if boost_idx + 1 < 4:
            scales[boost_idx + 1] = scales[boost_idx + 1] * (1.0 + amount * 0.3)
        return np.sum(scales, axis=0)

    if img.is_color:
        lum = img.luminance()
        new_lum = _one(lum)
        delta = new_lum - lum
        if mask is not None:
            delta *= mask
        out = img.data + delta[..., None]
    else:
        new = _one(img.data)
        out = img.data + (new - img.data) * (mask if mask is not None else 1.0)
    return img.with_data(np.clip(out, 0.0, 1.0))


@register_op(
    "local_contrast", "Local contrast (HDR reveal)", "nonlinear",
    [Param("amount", "float", 0.4, 0.0, 1.5, "Strength"),
     Param("radius", "int", 60, 10, 300, "Structure size in px to enhance")],
)
def local_contrast(img: AstroImage, amount: float = 0.4, radius: int = 60) -> AstroImage:
    """Large-scale unsharp mask: brings out galaxy arms and nebula filaments
    without changing global brightness. The counterpart of hdr_compress."""
    if amount <= 0:
        return img.copy()
    lum = img.luminance() if img.is_color else img.data
    blur = cv2.GaussianBlur(lum, (0, 0), radius / 3.0)
    delta = (lum - blur) * amount
    out = img.data + (delta[..., None] if img.is_color else delta)
    return img.with_data(np.clip(out, 0.0, 1.0))


@register_op(
    "hdr_compress", "HDR compression (rescue bright cores)", "nonlinear",
    [Param("amount", "float", 0.5, 0.0, 1.0, "How much to flatten large-scale range"),
     Param("radius", "int", 80, 20, 400, "Scale treated as 'large'")],
)
def hdr_compress(img: AstroImage, amount: float = 0.5, radius: int = 80) -> AstroImage:
    """Compress large-scale brightness range so M42's core or M31's bulge
    keeps detail after a hard stretch, while small-scale contrast survives."""
    if amount <= 0:
        return img.copy()
    lum = img.luminance() if img.is_color else img.data
    base = cv2.GaussianBlur(lum, (0, 0), radius / 3.0)
    detail = lum - base
    compressed = np.median(base) + (base - np.median(base)) * (1.0 - amount * 0.7)
    new_lum = np.clip(compressed + detail, 0.0, 1.0)
    if img.is_color:
        ratio = np.where(lum > 1e-6, new_lum / np.maximum(lum, 1e-6), 1.0)
        out = img.data * ratio[..., None]
    else:
        out = new_lum
    return img.with_data(np.clip(out, 0.0, 1.0))


@register_op(
    "clone_out", "Clone-out a defect", "cosmetic",
    [Param("x", "int", 0, doc="Center of the blemish"),
     Param("y", "int", 0, doc="Center of the blemish"),
     Param("radius", "int", 12, 2, 200, "Patch radius"),
     Param("src_x", "int", -1, doc="Source center; -1 = auto (inpaint)"),
     Param("src_y", "int", -1, doc="Source center; -1 = auto (inpaint)")],
)
def clone_out(img: AstroImage, x: int = 0, y: int = 0, radius: int = 12,
              src_x: int = -1, src_y: int = -1) -> AstroImage:
    """Remove a residual satellite streak segment, dust blob, or edge artifact.
    With no source given, OpenCV inpainting fills from the surroundings;
    with a source, a feathered patch is cloned over."""
    data = img.data.copy()
    h, w = data.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    dist = np.sqrt((xx - x) ** 2 + (yy - y) ** 2)
    mask = (dist <= radius)
    if src_x < 0 or src_y < 0:
        m8 = (mask * 255).astype(np.uint8)
        src16 = (np.clip(data, 0, 1) * 65535).astype(np.uint16)
        if data.ndim == 3:
            fixed = np.stack(
                [cv2.inpaint((src16[..., c] // 257).astype(np.uint8), m8, radius, cv2.INPAINT_TELEA)
                 for c in range(3)], axis=-1).astype(np.float32) / 255.0
        else:
            fixed = cv2.inpaint((src16 // 257).astype(np.uint8), m8, radius,
                                cv2.INPAINT_TELEA).astype(np.float32) / 255.0
        feather = np.clip((radius - dist) / max(radius * 0.3, 1), 0, 1)
        fm = feather if data.ndim == 2 else feather[..., None]
        data = data * (1 - fm) + fixed * fm
    else:
        dx, dy = src_x - x, src_y - y
        ys, xs = np.nonzero(mask)
        ys_src = np.clip(ys + dy, 0, h - 1)
        xs_src = np.clip(xs + dx, 0, w - 1)
        feather = np.clip((radius - dist[ys, xs]) / max(radius * 0.3, 1), 0, 1)
        if data.ndim == 3:
            data[ys, xs] = (data[ys, xs] * (1 - feather[:, None])
                             + data[ys_src, xs_src] * feather[:, None])
        else:
            data[ys, xs] = data[ys, xs] * (1 - feather) + data[ys_src, xs_src] * feather
    return img.with_data(np.clip(data, 0.0, 1.0))
