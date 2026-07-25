"""Trail stacking and the universal frame loader, verified on synthetic data
with known ground truth: a star that moves a known amount per frame must paint
its entire path into the composite, and a defect that never moves must not.
"""

import numpy as np
import pytest
from PIL import Image

from umbra_noctis.core.image import AstroImage
from umbra_noctis.stack.trails import collect_frames, trail_stack

H, W = 48, 64
HOT = (10, 50)  # a hot pixel present in every frame


def _frame(star_x: int) -> np.ndarray:
    """Dim sky + one bright star at (24, star_x) + one constant hot pixel."""
    rng = np.random.default_rng(star_x)
    data = rng.normal(0.05, 0.005, size=(H, W)).astype(np.float32)
    data[24, star_x] = 0.9
    data[HOT] = 0.8
    return np.clip(data, 0.0, 1.0)


def _write_session(tmp_path, n=8, fmt="fits"):
    paths = []
    for i in range(n):
        p = tmp_path / f"IMG_{i:04d}.{fmt}"
        arr = _frame(10 + 3 * i)
        if fmt == "fits":
            AstroImage(data=arr).save_fits(p)
        elif fmt == "tiff":
            import tifffile
            tifffile.imwrite(p, (arr * 65535).astype(np.uint16))
        elif fmt == "png":
            Image.fromarray((arr * 255).astype(np.uint8), "L").save(p)
        paths.append(p)
    return paths


def test_trail_covers_every_star_position(tmp_path):
    paths = _write_session(tmp_path, n=8)
    result = trail_stack(paths, cosmetic=False)
    assert result.n_frames == 8
    for i in range(8):
        assert result.image.data[24, 10 + 3 * i] > 0.5, f"star position {i} lost"
    # sky between trail points stays dark — nothing was averaged away
    assert result.image.data[40, 30] < 0.15


def test_hot_pixel_repaired_statistically(tmp_path):
    paths = _write_session(tmp_path, n=8)
    result = trail_stack(paths, cosmetic=True)
    assert result.n_hot_pixels >= 1
    assert result.image.data[HOT] < 0.3, "hot pixel survived cosmetic repair"
    # the real trail is untouched
    assert result.image.data[24, 10] > 0.5


def test_master_dark_subtraction(tmp_path):
    paths = _write_session(tmp_path, n=6)
    dark = AstroImage(data=np.full((H, W), 0.0, dtype=np.float32))
    dark.data[HOT] = 0.8
    result = trail_stack(paths, master_dark=dark, cosmetic=False)
    assert result.image.data[HOT] < 0.1
    assert result.image.data[24, 10] > 0.5


def test_mixed_formats_and_collect(tmp_path):
    _write_session(tmp_path, n=3, fmt="png")
    (tmp_path / "notes.txt").write_text("x")
    frames = collect_frames([tmp_path])
    assert len(frames) == 3  # the .txt is ignored
    assert frames == sorted(frames)
    result = trail_stack(frames, cosmetic=False)
    assert result.n_frames == 3
    assert result.image.data[24, 10] > 0.4


def test_from_file_tiff_is_linear_png_is_not(tmp_path):
    [tiff] = _write_session(tmp_path, n=1, fmt="tiff")
    img = AstroImage.from_file(tiff)
    assert img.linear and img.data.dtype == np.float32
    assert abs(float(img.data[24, 10]) - 0.9) < 0.01

    png_dir = tmp_path / "png"
    png_dir.mkdir()
    [png] = _write_session(png_dir, n=1, fmt="png")
    img = AstroImage.from_file(png)
    assert not img.linear
    assert 0.0 <= float(img.data.max()) <= 1.0


def test_raw_needs_rawpy_or_loads(tmp_path):
    try:
        import rawpy  # noqa: F401
        pytest.skip("rawpy installed; error-path not reachable")
    except ImportError:
        pass
    p = tmp_path / "IMG_0001.cr2"
    p.write_bytes(b"not a real raw")
    with pytest.raises(ImportError, match="umbra-noctis\\[dslr\\]"):
        AstroImage.from_file(p)


def test_mismatched_frame_skipped(tmp_path):
    paths = _write_session(tmp_path, n=4)
    odd = tmp_path / "IMG_9999.fits"
    AstroImage(data=np.zeros((10, 10), dtype=np.float32)).save_fits(odd)
    result = trail_stack(paths + [odd], cosmetic=False)
    assert result.n_frames == 4
    assert result.n_skipped == 1
