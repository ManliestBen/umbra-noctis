"""Meteor scanner, new editing ops, trail upgrades, and the built-in guide —
all verified against synthetic ground truth."""

from pathlib import Path

import cv2
import numpy as np
import pytest

import umbra_noctis.process  # noqa: F401 — registers ops
from umbra_noctis.core.image import AstroImage
from umbra_noctis.core.ops import OPS, apply_op
from umbra_noctis.detect import scan_for_meteors
from umbra_noctis.stack.trails import trail_stack

H, W = 240, 320
RNG = np.random.default_rng(42)
STARS = (RNG.uniform(0, 1, (25, 2)) * [H - 1, W - 1]).astype(int)


def _sky(noise_seed: int) -> np.ndarray:
    rng = np.random.default_rng(noise_seed)
    data = rng.normal(0.05, 0.008, size=(H, W)).astype(np.float32)
    for y, x in STARS:  # static star field, identical in every frame
        data[y, x] = 0.7
    return data


def _write(tmp_path, name, arr):
    p = tmp_path / name
    AstroImage(data=np.clip(arr, 0, 1)).save_fits(p)
    return p


def _night(tmp_path, n=9):
    return [_write(tmp_path, f"F{i:03d}.fits", _sky(i)) for i in range(n)]


# ------------------------------------------------------------- meteor scan
def test_meteor_frame_flagged(tmp_path):
    paths = _night(tmp_path)
    arr = _sky(4)
    cv2.line(arr, (40, 60), (200, 150), 0.9, 2)      # one bright streak
    _write(tmp_path, "F004.fits", arr)
    results = scan_for_meteors(paths)
    verdicts = {r.path.name: r.verdict for r in results}
    assert verdicts["F004.fits"] == "meteor"
    assert sum(v == "meteor" for v in verdicts.values()) == 1
    hit = next(r for r in results if r.verdict == "meteor")
    assert hit.longest.length > 100


def test_satellite_track_rejected(tmp_path):
    paths = _night(tmp_path)
    # a satellite: colinear segments marching across 3 consecutive frames
    for i, (a, b) in enumerate([((10, 20), (90, 60)), ((100, 65), (180, 105)),
                                ((190, 110), (270, 150))]):
        arr = _sky(3 + i)
        cv2.line(arr, a, b, 0.9, 2)
        _write(tmp_path, f"F{3 + i:03d}.fits", arr)
    results = scan_for_meteors(paths)
    for r in results:
        assert r.verdict != "meteor", f"{r.path.name} misclassified as meteor"
    assert any(r.verdict == "satellite" for r in results)


def test_clean_night_stays_clean(tmp_path):
    results = scan_for_meteors(_night(tmp_path, n=6))
    assert all(r.verdict == "clean" for r in results)


# ---------------------------------------------------------- trail upgrades
def _trail_frames(tmp_path, n=6):
    paths = []
    for i in range(n):
        arr = np.full((40, 60), 0.03, dtype=np.float32)
        arr[20, 8 + 4 * i] = 0.9   # star hops 4 px per frame → 2-3 px gaps
        paths.append(_write(tmp_path, f"T{i:02d}.fits", arr))
    return paths


def test_fade_dims_the_past(tmp_path):
    paths = _trail_frames(tmp_path)
    plain = trail_stack(paths, cosmetic=False, fill_gaps=False)
    faded = trail_stack(paths, cosmetic=False, fill_gaps=False, fade=0.1)
    oldest, newest = (20, 8), (20, 8 + 4 * 5)
    assert faded.image.data[newest] == pytest.approx(
        plain.image.data[newest], abs=1e-5)          # head stays bright
    assert faded.image.data[oldest] < plain.image.data[oldest] * 0.75


def test_gap_fill_bridges_dashes(tmp_path):
    paths = _trail_frames(tmp_path)
    gap_px = (20, 10)  # between star positions 8 and 12
    open_ = trail_stack(paths, cosmetic=False, fill_gaps=False)
    filled = trail_stack(paths, cosmetic=False, fill_gaps=True)
    assert open_.image.data[gap_px] < 0.1
    assert filled.image.data[gap_px] > 0.3


def test_mean_image_is_average(tmp_path):
    paths = _trail_frames(tmp_path, n=4)
    result = trail_stack(paths, cosmetic=False, fill_gaps=False)
    assert result.mean_image is not None
    # a pixel lit in exactly one of four frames averages to ~1/4 brightness
    assert result.mean_image.data[20, 8] == pytest.approx(
        (0.9 + 3 * 0.03) / 4, abs=0.01)


# -------------------------------------------------------------- new ops
def test_defringe_kills_purple_halo_keeps_star():
    data = np.full((50, 50, 3), 0.05, dtype=np.float32)
    data[25, 25] = [1.0, 1.0, 1.0]            # white star core
    data[25, 26] = [0.5, 0.1, 0.5]            # purple fringe beside it
    data[10, 10] = [0.5, 0.1, 0.5]            # same color far from any star
    img = AstroImage(data=data, linear=False)
    out = apply_op(img, "defringe", amount=1.0)
    r, g, b = out.data[25, 26]
    assert r - g < 0.1 and b - g < 0.1, "fringe next to star not neutralized"
    assert out.data[25, 25, 0] > 0.9, "star core damaged"
    far = out.data[10, 10]
    assert far[0] - far[1] > 0.3, "purple away from stars should survive"


def test_vignette_correct_lifts_corners():
    yy, xx = np.mgrid[0:120, 0:160]
    r2 = ((yy - 60) / 60.0) ** 2 + ((xx - 80) / 80.0) ** 2
    data = (0.4 * (1.0 - 0.5 * r2)).astype(np.float32)  # radial falloff
    img = AstroImage(data=data)
    out = apply_op(img, "vignette_correct", strength=1.0)
    center, corner = float(out.data[60, 80]), float(out.data[5, 5])
    assert corner / center > 0.9, "corner not lifted to match center"
    before = float(img.data[5, 5]) / float(img.data[60, 80])
    assert corner / center > before + 0.2


# ---------------------------------------------------------------- guide
def test_guide_covers_every_command_and_new_features():
    from umbra_noctis.guide import render, topics
    text = render("all")
    for cmd in ("demo-data", "umbra info", "umbra import", "umbra library",
                "umbra grade", "umbra stack", "umbra auto", "umbra process",
                "umbra ops", "umbra solve", "umbra planetary", "umbra trails",
                "umbra meteor-scan", "umbra guide", "umbra gui"):
        assert cmd in text, f"guide never mentions {cmd}"
    for feature in ("defringe", "vignette_correct", "--fade", "--foreground",
                    "--align", "--copy-to"):
        assert feature in text, f"guide never mentions {feature}"
    assert len(topics()) >= 7
    # generated ops reference stays in sync with the registry
    ops_text = render("ops")
    for name in OPS:
        assert f"`{name}`" in ops_text
    with pytest.raises(KeyError):
        render("no-such-topic")


def test_operations_doc_covers_every_op():
    """docs/OPERATIONS.md is a hand-committed snapshot of `umbra ops
    --markdown` — pin it against the live registry so it can't go stale
    again the way it did before (missing defringe/vignette_correct)."""
    ops_doc = (Path(__file__).parent.parent / "docs" / "OPERATIONS.md").read_text()
    for name in OPS:
        assert f"`{name}`" in ops_doc, f"docs/OPERATIONS.md is stale: missing {name}"
