"""Synthetic astronomical data generation.

Used by the test suite for ground-truth validation, and by ``umbra demo-data``
to create a realistic fake Dwarf 3 session so new users can try the entire
pipeline before their first clear night.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from astropy.io import fits


def make_star_field(
    height: int = 540,
    width: int = 960,
    n_stars: int = 120,
    fwhm: float = 3.0,
    background: float = 0.06,
    noise: float = 0.004,
    shift: tuple[float, float] = (0.0, 0.0),
    rotation_deg: float = 0.0,
    gradient: float = 0.0,
    hot_pixels: int = 0,
    satellite: bool = False,
    seed: int = 42,
    star_seed: int | None = 7,
) -> np.ndarray:
    """Render a synthetic linear star field in [0, 1].

    Star *positions* are drawn from ``star_seed`` so multiple calls produce the
    same sky; ``shift``/``rotation_deg`` (about the image center) then move that
    sky, letting tests validate registration against exact ground truth.
    ``seed`` controls the noise realization only.
    """
    rng_stars = np.random.default_rng(star_seed)
    rng_noise = np.random.default_rng(seed)

    margin = 40
    xs = rng_stars.uniform(margin, width - margin, n_stars)
    ys = rng_stars.uniform(margin, height - margin, n_stars)
    fluxes = 10.0 ** rng_stars.uniform(-1.2, 0.9, n_stars)

    theta = np.deg2rad(rotation_deg)
    cx, cy = width / 2.0, height / 2.0
    if theta != 0.0:
        dx, dy = xs - cx, ys - cy
        xs = cx + dx * np.cos(theta) - dy * np.sin(theta)
        ys = cy + dx * np.sin(theta) + dy * np.cos(theta)
    xs = xs + shift[0]
    ys = ys + shift[1]

    img = np.full((height, width), background, dtype=np.float32)
    sigma = fwhm / 2.3548
    half = max(4, int(4 * sigma))
    yy, xx = np.mgrid[-half:half + 1, -half:half + 1]
    for x, y, f in zip(xs, ys, fluxes, strict=False):
        ix, iy = int(round(x)), int(round(y))
        if not (half <= ix < width - half and half <= iy < height - half):
            continue
        psf = np.exp(-(((xx - (x - ix)) ** 2 + (yy - (y - iy)) ** 2) / (2 * sigma**2)))
        img[iy - half:iy + half + 1, ix - half:ix + half + 1] += (
            0.03 * f * psf / psf.sum() * psf.size / 4
        ).astype(np.float32)

    if gradient:
        gy = np.linspace(0, gradient, height, dtype=np.float32)[:, None]
        gx = np.linspace(0, gradient * 0.6, width, dtype=np.float32)[None, :]
        img += gy + gx

    if satellite:
        t = np.linspace(0, 1, 800)
        sx = (t * (width - 1)).astype(int)
        sy = (height * 0.2 + t * height * 0.5).astype(int)
        ok = (sy >= 0) & (sy < height)
        img[sy[ok], sx[ok]] += 0.25

    if hot_pixels:
        hx = rng_noise.integers(0, width, hot_pixels)
        hy = rng_noise.integers(0, height, hot_pixels)
        img[hy, hx] = 0.95

    img += rng_noise.normal(0.0, noise, img.shape).astype(np.float32)
    return np.clip(img, 0.0, 1.0)


def write_demo_session(
    root: str | Path,
    target: str = "M 42",
    n_lights: int = 12,
    n_darks: int = 8,
    exposure_s: float = 15.0,
    gain: int = 80,
    height: int = 540,
    width: int = 960,
    field_rotation: bool = True,
) -> tuple[Path, Path]:
    """Create a fake Dwarf 3 folder tree: one light session + one dark session.

    Lights include realistic defects — per-frame drift, alt-az field rotation,
    a light-pollution gradient, hot pixels, one cloudy frame, and one frame
    with a satellite trail — so every downstream feature has something to fix.
    Returns ``(light_session_dir, dark_session_dir)``.
    """
    root = Path(root)
    light_dir = root / (
        f"DWARF_RAW_TELE_{target}_EXP_{exposure_s:g}_GAIN_{gain}_2026-07-20-22-30-15-000"
    )
    dark_dir = root / f"DWARF_DARK_EXP_{exposure_s:g}_GAIN_{gain}_2026-07-20-20-05-01-000"
    light_dir.mkdir(parents=True, exist_ok=True)
    dark_dir.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(1)
    hot_x = rng.integers(0, width, 30)
    hot_y = rng.integers(0, height, 30)

    def header(exp, gn, obj=None):
        h = fits.Header()
        h["EXPTIME"] = exp
        h["GAIN"] = gn
        h["INSTRUME"] = "DWARF3 TELE (synthetic)"
        if obj:
            h["OBJECT"] = obj
        return h

    for i in range(n_lights):
        rot = 0.35 * i if field_rotation else 0.0
        cloudy = i == n_lights // 2  # one frame ruined by a passing cloud
        frame = make_star_field(
            height, width,
            fwhm=3.0 if not cloudy else 6.5,
            background=0.06 if not cloudy else 0.16,
            noise=0.004,
            shift=(1.7 * i + rng.normal(0, 0.3), -1.1 * i + rng.normal(0, 0.3)),
            rotation_deg=rot,
            gradient=0.03,
            satellite=(i == 2),
            seed=100 + i,
        )
        frame[hot_y, hot_x] = np.minimum(1.0, frame[hot_y, hot_x] + 0.6)  # fixed-pattern hot pixels
        data = (frame * 65535).astype(np.uint16)
        fits.PrimaryHDU(data=data, header=header(exposure_s, gain, target)).writeto(
            light_dir / f"{i:04d}.fits", overwrite=True)

    stacked = make_star_field(height, width, gradient=0.03, seed=999)
    fits.PrimaryHDU(data=(stacked * 65535).astype(np.uint16),
                    header=header(exposure_s, gain, target)).writeto(
        light_dir / "stacked.fits", overwrite=True)

    (light_dir / "shotsInfo.json").write_text(json.dumps({
        "target": target, "exp": str(exposure_s), "gain": gain, "ir": "PASS",
        "binning": "1x1", "format": "FITS",
        "shotsTaken": n_lights, "shotsStacked": n_lights - 1, "shotsToTake": n_lights,
        "RA": 5.588, "DEC": -5.39,
    }, indent=2))

    for i in range(n_darks):
        dark = np.full((height, width), 0.012, dtype=np.float32)
        dark += np.random.default_rng(500 + i).normal(0, 0.002, dark.shape).astype(np.float32)
        dark[hot_y, hot_x] = 0.6  # same hot pixels as the lights
        fits.PrimaryHDU(data=(np.clip(dark, 0, 1) * 65535).astype(np.uint16),
                        header=header(exposure_s, gain)).writeto(
            dark_dir / f"{i:04d}.fits", overwrite=True)
    (dark_dir / "shotsInfo.json").write_text(json.dumps(
        {"exp": str(exposure_s), "gain": gain, "shotsTaken": n_darks}, indent=2))

    return light_dir, dark_dir
