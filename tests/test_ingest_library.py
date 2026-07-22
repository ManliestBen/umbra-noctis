import numpy as np

from umbra_noctis.core.image import AstroImage
from umbra_noctis.ingest import discover_sessions, parse_session
from umbra_noctis.library import Library, resolve_target
from umbra_noctis.synth import write_demo_session


def test_parse_session_from_folder_name(tmp_path):
    light_dir, dark_dir = write_demo_session(tmp_path, n_lights=5, n_darks=3)

    s = parse_session(light_dir)
    assert s.kind == "light"
    assert s.lens == "TELE"
    assert s.target == "M 42"
    assert s.exposure_s == 15.0
    assert s.gain == 80
    assert s.frame_count == 5
    assert s.integration_s == 75.0
    assert len(s.stacked) == 1
    assert s.shots_info["shotsTaken"] == 5

    d = parse_session(dark_dir)
    assert d.kind == "dark"
    assert d.frame_count == 3


def test_discover_sessions(tmp_path):
    write_demo_session(tmp_path, n_lights=4, n_darks=2)
    sessions = discover_sessions(tmp_path)
    assert len(sessions) == 2
    kinds = {s.kind for s in sessions}
    assert kinds == {"light", "dark"}


def test_fits_roundtrip(tmp_path):
    light_dir, _ = write_demo_session(tmp_path, n_lights=1, n_darks=1)
    img = AstroImage.from_fits(sorted(light_dir.glob("0*.fits"))[0])
    assert img.data.dtype == np.float32
    assert 0.0 <= img.data.min() and img.data.max() <= 1.0
    assert img.meta["exposure_s"] == 15.0

    out = tmp_path / "roundtrip.fits"
    img.record("test_op", {"a": 1})
    img.save_fits(out, bits=16)
    back = AstroImage.from_fits(out)
    assert back.data.shape == img.data.shape
    assert np.allclose(back.data, img.data, atol=2.0 / 65535)


def test_resolve_target():
    assert resolve_target("m 31")["canonical"] == "M31"
    assert resolve_target("Andromeda")["canonical"] == "M31"
    assert resolve_target("NGC0253")["canonical"] == "NGC 253"
    assert resolve_target("ngc7000")["display"].startswith("North America")
    assert resolve_target("Some Weird Name")["canonical"] == "Some Weird Name"
    assert "galaxy" == resolve_target("m101")["kind"]


def test_library_import_and_dedup(tmp_path):
    light_dir, dark_dir = write_demo_session(tmp_path / "data", n_lights=4, n_darks=2)
    lib = Library(db_path=tmp_path / "lib.db")

    s = parse_session(light_dir)
    sid, new = lib.import_session(s)
    assert new
    assert lib.session(sid)["target"] == "M42"
    assert len(lib.frames(sid)) == 4

    # Re-import of the same folder: same row, not duplicated
    sid2, new2 = lib.import_session(s)
    assert not new2 or sid2 == sid
    assert len(lib.sessions()) == 1

    lib.import_session(parse_session(dark_dir))
    summary = lib.targets_summary()
    assert len(summary) == 1  # darks excluded
    assert summary[0]["frames"] == 4

    lib.set_rating(sid, 4)
    assert lib.session(sid)["rating"] == 4
    lib.close()
