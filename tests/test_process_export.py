import numpy as np
import pytest

import umbra_noctis.process  # noqa: F401 — registers ops
from umbra_noctis.core.image import AstroImage
from umbra_noctis.core.ops import OPS, apply_op
from umbra_noctis.export import export_image, save_comparison
from umbra_noctis.process.display import auto_stretch_display
from umbra_noctis.recipes import Recipe, run_recipe, auto_process
from umbra_noctis.synth import make_star_field, write_demo_session


def _color_img(gradient=0.05):
    base = make_star_field(200, 300, n_stars=40, gradient=gradient, seed=5)
    rgb = np.stack([base * 1.1, base, base * 0.9], axis=-1)
    return AstroImage(data=np.clip(rgb, 0, 1).astype(np.float32))


def test_ops_registered():
    expected = {"background_extract", "background_neutralize", "white_balance",
                "scnr", "denoise", "deconvolve", "banding_reduce",
                "autostretch", "histogram_stretch", "ghs", "arcsinh", "curves",
                "saturation", "hue_shift", "dualband_extract",
                "crop", "rotate", "flip", "resize", "invert",
                "star_reduce", "sharpen", "local_contrast", "hdr_compress",
                "clone_out"}
    missing = expected - set(OPS)
    assert not missing, f"ops not registered: {missing}"


def test_background_extract_removes_gradient():
    img = _color_img(gradient=0.08)
    lum = img.luminance()
    before_span = float(np.median(lum[-20:]) - np.median(lum[:20]))
    out = apply_op(img, "background_extract", degree=2)
    lum2 = out.luminance()
    after_span = float(np.median(lum2[-20:]) - np.median(lum2[:20]))
    assert abs(after_span) < abs(before_span) * 0.25
    assert out.history[-1]["op"] == "background_extract"


def test_stretches_brighten_and_mark_nonlinear():
    img = _color_img()
    for op, params in [("autostretch", {}), ("ghs", {"amount": 6.0}),
                       ("arcsinh", {"factor": 50.0}),
                       ("histogram_stretch", {"midtones": 0.15})]:
        out = apply_op(img, op, **params)
        assert not out.linear, op
        assert float(np.median(out.data)) > float(np.median(img.data)), op


def test_scnr_and_neutralize():
    img = _color_img()
    data = img.data.copy()
    data[..., 1] += 0.05  # green cast
    img = img.with_data(np.clip(data, 0, 1))
    out = apply_op(apply_op(img, "background_neutralize"), "scnr", amount=1.0)
    meds = [float(np.median(out.data[..., c])) for c in range(3)]
    assert meds[1] <= max(meds[0], meds[2]) + 0.005  # green no longer dominant


def test_dualband_extract_hoo():
    img = _color_img()
    out = apply_op(img, "dualband_extract", palette="HOO")
    assert out.is_color
    # green and blue channels must be identical (both OIII)
    assert np.allclose(out.data[..., 1], out.data[..., 2])
    mono = apply_op(img, "dualband_extract", palette="HA")
    assert not mono.is_color


def test_geometry_roundtrip():
    img = _color_img()
    out = apply_op(img, "rotate", degrees=90.0)
    assert (out.height, out.width) == (img.width, img.height)
    out2 = apply_op(out, "flip", direction="horizontal")
    assert out2.data.shape == out.data.shape
    cropped = apply_op(img, "crop", x=10, y=10, width=100, height=80)
    assert (cropped.height, cropped.width) == (80, 100)
    small = apply_op(img, "resize", scale=0.5, method="area")
    assert small.width == img.width // 2


def test_denoise_reduces_noise_preserves_stars():
    img = _color_img()
    noisy = img.with_data(np.clip(
        img.data + np.random.default_rng(0).normal(0, 0.02, img.data.shape), 0, 1
    ).astype(np.float32))
    out = apply_op(noisy, "denoise", method="wavelet", strength=1.5)

    def hf_noise(d):
        from scipy import ndimage
        lum = d.mean(axis=2)
        hp = lum - ndimage.gaussian_filter(lum, 5)
        return float(np.median(np.abs(hp)))

    assert hf_noise(out.data) < hf_noise(noisy.data) * 0.7
    # brightest star must survive
    assert float(out.data.max()) > 0.5 * float(noisy.data.max())


def test_curves_and_saturation():
    img = apply_op(_color_img(), "autostretch")
    s_curve = apply_op(img, "curves", points="0,0;0.3,0.2;0.7,0.8;1,1")
    assert s_curve.data.shape == img.data.shape
    sat = apply_op(img, "saturation", amount=1.8)
    chroma = np.abs(sat.data - sat.luminance()[..., None]).mean()
    chroma0 = np.abs(img.data - img.luminance()[..., None]).mean()
    assert chroma > chroma0


def test_recipe_roundtrip(tmp_path):
    img = _color_img()
    recipe = Recipe(name="test", steps=[
        {"op": "background_extract", "params": {"degree": 2}},
        {"op": "autostretch", "params": {}},
        {"op": "saturation", "params": {"amount": 1.2}},
    ])
    out = run_recipe(img, recipe)
    assert [h["op"] for h in out.history[-3:]] == [
        "background_extract", "autostretch", "saturation"]

    # recipe extracted from history reproduces the result
    derived = Recipe.from_history(out, "derived")
    p = derived.save(tmp_path / "r.json")
    reloaded = Recipe.load(p)
    out2 = run_recipe(img, reloaded)
    assert np.allclose(out.data, out2.data, atol=1e-5)

    bad = Recipe(name="bad", steps=[{"op": "nope", "params": {}}])
    with pytest.raises(ValueError):
        run_recipe(img, bad)


def test_export_formats(tmp_path):
    img = apply_op(_color_img(), "autostretch")
    for ext in ("tif", "png", "jpg", "fits"):
        p = export_image(img, tmp_path / f"out.{ext}")
        assert p.exists() and p.stat().st_size > 1000
    cmp_path = save_comparison(_color_img(), img, tmp_path / "cmp.jpg")
    assert cmp_path.exists()


def test_display_autostretch_visibility():
    img = _color_img()
    disp = auto_stretch_display(img.data)
    assert 0.1 < float(np.median(disp)) < 0.5  # dark linear data becomes visible


@pytest.mark.slow
def test_auto_process_end_to_end(tmp_path):
    light_dir, dark_dir = write_demo_session(tmp_path / "d", n_lights=8, n_darks=4)
    img, result, exported = auto_process(light_dir, tmp_path / "out")
    assert result.n_used >= 5
    assert len(exported) == 3
    for p in exported:
        assert p.exists() and p.stat().st_size > 1000
    assert not img.linear
    ops = [h["op"] for h in img.history]
    assert "integrate" in ops and "ghs" in ops
    # the darks folder next to the lights must have been found automatically
    assert any(h["op"] == "subtract_dark" for h in img.history), \
        "auto pipeline should have found and subtracted the darks next door"
