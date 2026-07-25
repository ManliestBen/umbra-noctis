"""Characterization tests for the CLI surface (umbra_noctis.cli), driven
in-process via ``main(argv)``. cli.py is the highest-churn file in the repo
and had zero tests before this — these lock in "the command runs and
produces the artifact/output substring it claims to," not exact prose."""

import numpy as np
import pytest
from PIL import Image

from umbra_noctis.cli import main
from umbra_noctis.core.image import AstroImage
from umbra_noctis.synth import make_star_field


def test_demo_data_creates_dirs(tmp_path):
    d = tmp_path / "demo"
    main(["demo-data", str(d), "--frames", "5"])
    assert d.exists()
    assert list(d.glob("DWARF_RAW_*"))
    assert list(d.glob("DWARF_DARK_*"))


def test_info_prints_target_and_frame_count(tmp_path, capsys):
    d = tmp_path / "demo"
    main(["demo-data", str(d), "--frames", "5"])
    light_dir = next(d.glob("DWARF_RAW_*"))
    capsys.readouterr()  # discard demo-data's own output

    main(["info", str(light_dir)])
    out = capsys.readouterr().out
    assert "M 42" in out
    assert "5 ×" in out


def test_import_and_library_targets(tmp_path, capsys):
    d = tmp_path / "demo"
    main(["demo-data", str(d), "--frames", "4"])
    db = tmp_path / "lib.db"
    capsys.readouterr()

    main(["import", str(d), "--db", str(db)])
    out = capsys.readouterr().out
    assert "new" in out
    assert db.exists()

    main(["library", "targets", "--db", str(db)])
    out = capsys.readouterr().out
    assert "M42" in out or "M 42" in out


def test_grade_prints_verdict_table(tmp_path, capsys):
    d = tmp_path / "demo"
    main(["demo-data", str(d), "--frames", "6"])
    light_dir = next(d.glob("DWARF_RAW_*"))
    capsys.readouterr()

    main(["grade", str(light_dir)])
    out = capsys.readouterr().out
    assert "verdict" in out
    assert "OK" in out or "REJECT" in out


def test_ops_contains_defringe(capsys):
    main(["ops"])
    out = capsys.readouterr().out
    assert "defringe" in out


def test_guide_lists_topics_and_faq_nonzero(capsys):
    main(["guide"])
    out = capsys.readouterr().out
    assert "nightscape" in out
    capsys.readouterr()

    main(["guide", "faq"])
    out = capsys.readouterr().out
    assert len(out.strip()) > 0


def test_process_autostretch_creates_output(tmp_path):
    fits_path = tmp_path / "stack.fits"
    AstroImage(data=make_star_field(seed=1)).save_fits(fits_path)
    out = tmp_path / "out.jpg"

    main(["process", str(fits_path), "-o", str(out), "--op", "autostretch"])
    assert out.exists() and out.stat().st_size > 500


def test_trails_on_tiny_pngs_creates_output(tmp_path):
    frame_dir = tmp_path / "frames"
    frame_dir.mkdir()
    for i in range(4):
        arr = np.full((20, 30), 30, dtype=np.uint8)
        arr[10, 5 + i] = 200
        Image.fromarray(arr, "L").save(frame_dir / f"F{i:02d}.png")
    out = tmp_path / "trails.jpg"

    main(["trails", str(frame_dir), "-o", str(out)])
    assert out.exists() and out.stat().st_size > 200


def test_error_path_nonexistent_info(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["info", "/nonexistent/path/that/does/not/exist"])
    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "error:" in err


def test_process_creates_missing_output_dir(tmp_path):
    """export_image/save_fits now mkdir their destination's parent — a
    first-run typo'd/not-yet-created output directory shouldn't raise."""
    fits_path = tmp_path / "stack.fits"
    AstroImage(data=make_star_field(seed=2)).save_fits(fits_path)
    out = tmp_path / "does" / "not" / "exist" / "out.jpg"

    main(["process", str(fits_path), "-o", str(out)])
    assert out.exists()
