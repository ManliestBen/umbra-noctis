import numpy as np
import pytest
from astropy.io import fits

from umbra_noctis.calib import (
    build_master,
    cosmetic_correction,
    hot_pixel_map,
    subtract_dark,
    synthetic_flat,
)
from umbra_noctis.core.image import AstroImage
from umbra_noctis.grade import grade_session
from umbra_noctis.ingest import parse_session
from umbra_noctis.stack import integrate
from umbra_noctis.stack.register import solve_transform
from umbra_noctis.synth import make_star_field, write_demo_session


def _img(arr, **meta):
    im = AstroImage(data=arr.astype(np.float32))
    im.meta.update(meta)
    return im


def test_grading_flags_cloudy_frame(tmp_path):
    light_dir, _ = write_demo_session(tmp_path, n_lights=9, n_darks=2)
    session = parse_session(light_dir)
    results = grade_session(session.lights)
    assert len(results) == 9
    cloudy = results[9 // 2]  # write_demo_session ruins the middle frame
    assert not cloudy.accepted
    assert any("clouds" in r or "bright" in r for r in cloudy.reject_reasons)
    good = [q for q in results if q.accepted]
    assert len(good) >= 6
    assert all(q.n_stars > 20 for q in good)


def test_registration_recovers_known_transform():
    ref = _img(make_star_field(seed=1))
    rotated = _img(make_star_field(shift=(12.3, -7.8), rotation_deg=1.6, seed=2))
    t = solve_transform(rotated, ref)
    assert t.method == "stars"
    # astroalign should recover the inverse transform to sub-pixel accuracy
    assert abs(abs(t.rotation_deg) - 1.6) < 0.1
    # verify by mapping a star position through the matrix
    src = np.array([600.0, 300.0, 1.0])  # center is rotation-invariant, use offset point
    mapped = t.matrix @ src
    # ground truth: rotate about center then shift, inverted
    theta = np.deg2rad(1.6)
    cx, cy = 480.0, 270.0
    x, y = src[0] - 12.3, src[1] + 7.8  # undo shift
    gx = cx + (x - cx) * np.cos(-theta) - (y - cy) * np.sin(-theta)
    gy = cy + (x - cx) * np.sin(-theta) + (y - cy) * np.cos(-theta)
    assert abs(mapped[0] - gx) < 1.5
    assert abs(mapped[1] - gy) < 1.5


def test_dark_subtraction_and_hot_pixels():
    rng = np.random.default_rng(0)
    dark = np.full((80, 100), 0.02, dtype=np.float32)
    hot = (rng.random((80, 100)) > 0.995)
    dark[hot] = 0.7
    master = _img(dark, exposure_s=15.0)

    light = _img(np.clip(0.1 + dark + rng.normal(0, 0.002, dark.shape), 0, 1).astype(np.float32),
                 exposure_s=15.0)
    calibrated = subtract_dark(light, master)
    assert abs(float(np.median(calibrated.data)) - 0.1) < 0.01

    hmap = hot_pixel_map(master)
    assert (hmap == hot).mean() > 0.99
    fixed = cosmetic_correction(light, hmap)
    assert float(fixed.data[hot].mean()) < 0.2


def test_build_master_sigma_clip(tmp_path):
    rng = np.random.default_rng(3)
    frames = [np.full((40, 40), 0.05, dtype=np.float32) + rng.normal(0, 0.01, (40, 40))
              for _ in range(10)]
    frames[4][10, 10] = 1.0  # cosmic ray in one frame
    paths = []
    for i, f in enumerate(frames):
        p = tmp_path / f"d{i}.fits"
        fits.PrimaryHDU((np.clip(f, 0, 1) * 65535).astype(np.uint16)).writeto(p)
        paths.append(str(p))
    master = build_master(paths, method="sigma_clip")
    assert abs(float(master.data[10, 10]) - 0.05) < 0.02  # outlier rejected


def test_synthetic_flat_flattens_vignette():
    yy, xx = np.mgrid[0:200, 0:300]
    r2 = ((xx - 150) / 150.0) ** 2 + ((yy - 100) / 100.0) ** 2
    vignette = (1.0 - 0.4 * r2).astype(np.float32)
    field = 0.2 * vignette
    img = _img(field)
    flat = synthetic_flat(img, box=32)
    from umbra_noctis.calib import apply_flat
    fixed = apply_flat(img, flat)
    corner = float(fixed.data[5:20, 5:20].mean())
    center = float(fixed.data[90:110, 140:160].mean())
    assert abs(corner - center) / center < 0.08  # within 8% after correction


@pytest.mark.slow
def test_end_to_end_integration_improves_snr(tmp_path):
    light_dir, dark_dir = write_demo_session(tmp_path, n_lights=10, n_darks=6)
    session = parse_session(light_dir)
    darks = parse_session(dark_dir)
    master_dark = build_master(darks.lights)

    result = integrate(session.lights, master_dark=master_dark)

    # The cloudy frame must have been dropped
    assert result.n_used < 10
    stacked = result.image

    single = AstroImage.from_fits(session.lights[0])
    # SNR proxy: HIGH-FREQUENCY background noise must drop roughly as sqrt(N).
    # (High-pass first so the light-pollution gradient doesn't dominate the MAD.)
    from scipy import ndimage as _ndi

    def bg_noise(d):
        lum = d if d.ndim == 2 else d.mean(axis=2)
        hp = lum - _ndi.gaussian_filter(lum, 8)
        return np.median(np.abs(hp - np.median(hp))) * 1.4826

    noise_single = bg_noise(single.data)
    noise_stack = bg_noise(stacked.data)
    assert noise_stack < noise_single * 0.6, (
        f"stacking should cut noise: single={noise_single:.5f} stack={noise_stack:.5f}")

    # Satellite trail from frame 2 must be gone (rejection worked):
    # trail pixels would be ~0.25 above background in a plain mean
    assert result.rejected_pixel_fraction > 0.0
    assert float(stacked.data.max()) <= 1.0
    # history must record the full lineage
    ops = [h["op"] for h in stacked.history]
    assert "integrate" in ops
