"""Linear-stage operations: everything applied BEFORE stretching.

Order matters in astro processing. The recommended linear sequence is:
background_extract -> background_neutralize -> white_balance/scnr ->
denoise -> deconvolve. All ops preserve linearity.
"""

from __future__ import annotations

import cv2
import numpy as np
from scipy import ndimage

from ..core.image import AstroImage
from ..core.ops import Param, register_op
from ..core.stats import MAD_TO_SIGMA, median_mad
from ..grade.stars import detect_stars


# --------------------------------------------------------------- background
@register_op(
    "background_extract", "Background / gradient removal", "linear",
    [Param("degree", "int", 2, 1, 4, "Polynomial degree of the sky model (2 handles most "
           "light-pollution gradients; 4 for corner glows)"),
     Param("samples", "int", 24, 8, 64, "Sample grid resolution per axis"),
     Param("mode", "choice", "subtract", choices=("subtract", "divide"),
           doc="subtract = additive gradients (light pollution); divide = "
               "multiplicative (vignetting)")],
)
def background_extract(img: AstroImage, degree: int = 2, samples: int = 24,
                       mode: str = "subtract") -> AstroImage:
    """Model and remove the sky background (the #1 fix for backyard imaging).

    A grid of sample boxes is placed across the image; boxes contaminated by
    stars or nebulosity are rejected by sigma-clipping against their
    neighbors, a 2-D polynomial is fit per channel, and the model is
    subtracted (or divided out). The original median level is restored so the
    image doesn't go dark.
    """
    data = img.data.astype(np.float64)
    single = data.ndim == 2
    if single:
        data = data[..., None]
    h, w, nc = data.shape
    yy, xx = np.mgrid[0:h, 0:w]
    xn, yn = (xx - w / 2) / w, (yy - h / 2) / h

    def poly_terms(x, y, deg):
        terms = []
        for i in range(deg + 1):
            for j in range(deg + 1 - i):
                terms.append((x ** i) * (y ** j))
        return np.stack(terms, axis=-1)

    out = np.empty_like(data)
    for c in range(nc):
        ch = data[..., c]
        sy_l, sx_l, val = [], [], []
        for iy in range(samples):
            for ix in range(samples):
                y0, y1 = iy * h // samples, (iy + 1) * h // samples
                x0, x1 = ix * w // samples, (ix + 1) * w // samples
                cell = ch[y0:y1, x0:x1]
                val.append(np.percentile(cell, 25))  # sky, below stars/nebula
                sy_l.append((y0 + y1) / 2)
                sx_l.append((x0 + x1) / 2)
        val = np.array(val)
        # reject samples that sit on nebulosity: sigma-clip against global trend
        med, mad_raw = median_mad(val)
        mad = mad_raw * MAD_TO_SIGMA + 1e-9
        ok = np.abs(val - med) < 3.0 * mad
        sxn = (np.array(sx_l)[ok] - w / 2) / w
        syn = (np.array(sy_l)[ok] - h / 2) / h
        A = poly_terms(sxn, syn, degree)
        coef, *_ = np.linalg.lstsq(A, val[ok], rcond=None)
        model = poly_terms(xn, yn, degree) @ coef
        if mode == "divide":
            model = np.clip(model / max(np.median(model), 1e-9), 0.2, 5.0)
            out[..., c] = ch / model * (np.median(model))
        else:
            out[..., c] = ch - model + np.median(model)
    result = np.clip(out[..., 0] if single else out, 0.0, 1.0)
    return img.with_data(result)


@register_op(
    "background_neutralize", "Neutralize background color", "linear", [],
)
def background_neutralize(img: AstroImage) -> AstroImage:
    """Equalize the RGB background medians so the sky is gray, not orange.
    Run after background_extract, before any stretch."""
    if not img.is_color:
        return img.copy()
    data = img.data.copy()
    meds = [float(np.median(data[..., c])) for c in range(3)]
    target = float(np.mean(meds))
    for c in range(3):
        data[..., c] += target - meds[c]
    return img.with_data(np.clip(data, 0.0, 1.0))


@register_op(
    "white_balance", "White balance (star-based or manual)", "linear",
    [Param("r", "float", 1.0, 0.2, 5.0, "Red gain (ignored when auto=true)"),
     Param("g", "float", 1.0, 0.2, 5.0, "Green gain"),
     Param("b", "float", 1.0, 0.2, 5.0, "Blue gain"),
     Param("auto", "bool", True, doc="Derive gains so the average detected star is white")],
)
def white_balance(img: AstroImage, r: float = 1.0, g: float = 1.0, b: float = 1.0,
                  auto: bool = True) -> AstroImage:
    """Color-balance the image. Auto mode assumes the *average* star in a wide
    field is roughly solar-colored — a good approximation for Dwarf 3 fields
    (full photometric calibration via plate solve is in `umbra solve`)."""
    if not img.is_color:
        return img.copy()
    data = img.data.copy()
    gains = np.array([r, g, b], dtype=np.float64)
    if auto:
        stars = detect_stars(img.luminance(), threshold_sigma=6.0, max_stars=200)
        if len(stars) >= 10:
            sums = np.zeros(3)
            bg = [float(np.median(data[..., c])) for c in range(3)]
            for s in stars:
                x, y = int(round(s["x"])), int(round(s["y"]))
                patch = data[max(0, y - 3):y + 4, max(0, x - 3):x + 4]
                patch_sum = patch.reshape(-1, 3).sum(axis=0)
                bg_total = np.array(bg) * patch.shape[0] * patch.shape[1]
                sums += np.maximum(patch_sum - bg_total, 1e-9)
            gains = sums[1] / np.maximum(sums, 1e-12)  # normalize to green
    for c in range(3):
        med = float(np.median(data[..., c]))
        data[..., c] = (data[..., c] - med) * gains[c] + med
    return img.with_data(np.clip(data, 0.0, 1.0))


@register_op(
    "scnr", "Remove green cast (SCNR)", "linear",
    [Param("amount", "float", 1.0, 0.0, 1.0, "1.0 = full removal")],
)
def scnr(img: AstroImage, amount: float = 1.0) -> AstroImage:
    """Subtractive Chromatic Noise Reduction: clamps green to the average of
    red and blue. Deep-sky objects are almost never green — leftover green is
    sensor artifact. Safe default after color balancing."""
    if not img.is_color:
        return img.copy()
    data = img.data.copy()
    cap = 0.5 * (data[..., 0] + data[..., 2])
    g = data[..., 1]
    data[..., 1] = np.where(g > cap, g * (1 - amount) + cap * amount, g)
    return img.with_data(data)


# ------------------------------------------------------------------ denoise
@register_op(
    "denoise", "Noise reduction", "linear",
    [Param("method", "choice", "wavelet", choices=("wavelet", "bilateral", "gaussian"),
           doc="wavelet = starlet soft-threshold (best); bilateral = edge-preserving; "
               "gaussian = simple blur"),
     Param("strength", "float", 1.0, 0.0, 4.0, "Threshold multiplier / blur size"),
     Param("chroma_boost", "float", 2.0, 0.0, 6.0,
           "Extra denoise on color channels (chroma noise is uglier than luma)")],
)
def denoise(img: AstroImage, method: str = "wavelet", strength: float = 1.0,
            chroma_boost: float = 2.0) -> AstroImage:
    """Reduce noise while preserving stars and structure.

    Wavelet mode decomposes the image into à-trous (starlet) scales and
    soft-thresholds the finest scales where noise lives; structure at larger
    scales is untouched. On color images the chroma is denoised harder than
    luminance, which is where the "watercolor blotch" look comes from.
    """
    if strength <= 0:
        return img.copy()
    data = img.data

    def _wavelet(plane, s):
        return _starlet_denoise(plane, n_scales=4, k=s)

    def _bilateral(plane, s):
        d = max(3, int(2 * s) * 2 + 1)
        return cv2.bilateralFilter(plane.astype(np.float32), d, 0.05 * s, d)

    def _gauss(plane, s):
        return ndimage.gaussian_filter(plane, 0.6 * s)

    fn = {"wavelet": _wavelet, "bilateral": _bilateral, "gaussian": _gauss}[method]

    if img.is_color:
        # denoise in a luma/chroma decomposition
        lum = img.luminance()
        new_lum = fn(lum, strength)
        out = np.empty_like(data)
        for c in range(3):
            chroma = data[..., c] - lum
            chroma = fn(chroma, strength * max(chroma_boost, 0.0)) if chroma_boost > 0 else chroma
            out[..., c] = new_lum + chroma
        result = out
    else:
        result = fn(data, strength)
    return img.with_data(np.clip(result, 0.0, 1.0))


def _starlet_scales(plane: np.ndarray, n_scales: int) -> list[np.ndarray]:
    """À-trous B3-spline wavelet decomposition."""
    kernel1d = np.array([1, 4, 6, 4, 1], dtype=np.float32) / 16.0
    scales = []
    current = plane.astype(np.float32)
    for j in range(n_scales):
        dilated = np.zeros(len(kernel1d) + (len(kernel1d) - 1) * (2**j - 1), dtype=np.float32)
        dilated[:: 2**j] = kernel1d
        smooth = ndimage.convolve1d(current, dilated, axis=0, mode="reflect")
        smooth = ndimage.convolve1d(smooth, dilated, axis=1, mode="reflect")
        scales.append(current - smooth)
        current = smooth
    scales.append(current)  # residual
    return scales


def _starlet_denoise(plane: np.ndarray, n_scales: int = 4, k: float = 1.0) -> np.ndarray:
    scales = _starlet_scales(plane, n_scales)
    out = scales[-1].copy()
    for j, layer in enumerate(scales[:-1]):
        # MAD from zero (not from the layer's own median): wavelet detail
        # coefficients are already zero-centered, so this is the standard
        # noise-sigma estimator for starlet/wavelet denoising.
        sigma = np.median(np.abs(layer)) * MAD_TO_SIGMA + 1e-12
        # threshold falls off with scale: noise lives in the fine scales
        thresh = k * sigma * (3.0, 2.0, 1.0, 0.5)[min(j, 3)]
        out += np.sign(layer) * np.maximum(np.abs(layer) - thresh, 0.0)
    return out


# ------------------------------------------------------------- deconvolution
@register_op(
    "deconvolve", "Deconvolution (Richardson–Lucy)", "linear",
    [Param("iterations", "int", 15, 1, 60, "More iterations = sharper but riskier"),
     Param("psf_fwhm", "float", 0.0, 0.0, 12.0,
           "PSF size in px; 0 = measure automatically from stars"),
     Param("regularization", "float", 0.002, 0.0, 0.02, "Damping against ringing")],
)
def deconvolve(img: AstroImage, iterations: int = 15, psf_fwhm: float = 0.0,
               regularization: float = 0.002) -> AstroImage:
    """Sharpen by undoing the blur the optics/atmosphere applied.

    Richardson–Lucy with a Gaussian PSF. By default the PSF width is measured
    from the stars in the image itself. Apply on LINEAR data only, ideally
    after denoising. If stars grow dark rings, lower iterations or raise
    regularization."""
    lum = img.luminance()
    if psf_fwhm <= 0:
        stars = detect_stars(lum)
        psf_fwhm = float(np.median(stars["fwhm"])) if len(stars) >= 5 else 3.0
        psf_fwhm = float(np.clip(psf_fwhm, 1.5, 8.0))
    sigma = psf_fwhm / 2.3548
    size = max(7, int(sigma * 6) | 1)
    ax = np.arange(size) - size // 2
    g = np.exp(-(ax**2) / (2 * sigma**2))
    psf = np.outer(g, g)
    psf /= psf.sum()

    def _rl(plane):
        est = np.clip(plane, 1e-6, 1.0).astype(np.float64)
        obs = est.copy()
        for _ in range(iterations):
            conv = cv2.filter2D(est, -1, psf, borderType=cv2.BORDER_REFLECT)
            ratio = obs / np.maximum(conv, regularization)
            est *= cv2.filter2D(ratio, -1, psf[::-1, ::-1], borderType=cv2.BORDER_REFLECT)
        return est

    if img.is_color:
        out = np.stack([_rl(img.data[..., c]) for c in range(3)], axis=-1)
    else:
        out = _rl(img.data)
    return img.with_data(np.clip(out, 0.0, 1.0).astype(np.float32))


@register_op(
    "banding_reduce", "Reduce row/column banding", "linear",
    [Param("axis", "choice", "rows", choices=("rows", "cols", "both"),
           doc="Direction of the banding pattern"),
     Param("protect", "float", 0.9, 0.5, 1.0,
           "Percentile of pixels treated as background per line")],
)
def banding_reduce(img: AstroImage, axis: str = "rows", protect: float = 0.9) -> AstroImage:
    """Suppress horizontal/vertical pattern banding by subtracting each
    line's robust background offset from the global background level."""
    data = img.data.copy()
    planes = [data] if data.ndim == 2 else [data[..., c] for c in range(3)]
    for plane in planes:
        for ax in ((0,) if axis == "rows" else (1,) if axis == "cols" else (0, 1)):
            other = 1 - ax
            line_bg = np.percentile(plane, 100 * (1 - protect) + 25, axis=other)
            line_bg = ndimage.median_filter(line_bg, 5)
            correction = line_bg - np.median(line_bg)
            plane -= correction[:, None] if ax == 0 else correction[None, :]
    return img.with_data(np.clip(data, 0.0, 1.0))


@register_op(
    "vignette_correct", "Vignetting correction", "linear",
    [Param("strength", "float", 1.0, 0.0, 1.0, "0 = off, 1 = full correction"),
     Param("box", "int", 64, 16, 256, "Sampling box size in pixels")],
)
def vignette_correct(img: AstroImage, strength: float = 1.0,
                     box: int = 64) -> AstroImage:
    """Remove radial lens vignetting (dark corners) by fitting a smooth 2-D
    illumination surface to the image's own star-free background and dividing
    it out — a synthetic flat. Made for wide-angle DSLR nightscapes and
    Dwarf 3 frames when no real flats exist. Run before stretching."""
    from ..calib.masters import synthetic_flat
    if strength <= 0:
        return img.copy()
    flat = synthetic_flat(img, box=box).data
    norm = (1.0 - strength) + strength * flat
    return img.with_data(np.clip(img.data / np.clip(norm, 0.2, 5.0), 0.0, 1.0))
