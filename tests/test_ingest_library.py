import shutil

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


def test_linear_flag_roundtrip(tmp_path):
    # A stretched (non-linear) image saved to FITS and reloaded must come
    # back non-linear — previously the flag never left the object, so a
    # reloaded stretched image looked linear and got double-autostretched.
    stretched = AstroImage(data=np.full((8, 8), 0.5, dtype=np.float32), linear=False)
    out = tmp_path / "stretched.fits"
    stretched.save_fits(out)
    back = AstroImage.from_fits(out)
    assert back.linear is False

    linear_img = AstroImage(data=np.full((8, 8), 0.1, dtype=np.float32), linear=True)
    out2 = tmp_path / "linear.fits"
    linear_img.save_fits(out2)
    back2 = AstroImage.from_fits(out2)
    assert back2.linear is True


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
    assert (new2, sid2) == (False, sid)
    assert len(lib.sessions()) == 1

    lib.import_session(parse_session(dark_dir))
    summary = lib.targets_summary()
    assert len(summary) == 1  # darks excluded
    assert summary[0]["frames"] == 4

    lib.set_rating(sid, 4)
    assert lib.session(sid)["rating"] == 4
    lib.close()


def test_reimport_keeps_frames_attached(tmp_path):
    """Regression test for the lastrowid-after-UPSERT bug (fixed in plan 001):
    re-importing an already-cataloged folder must attach its frames to the
    SAME session id, not to whatever row lastrowid happened to point at."""
    light_dir, _ = write_demo_session(tmp_path, n_lights=4, n_darks=2)
    lib = Library(db_path=tmp_path / "lib.db")
    s = parse_session(light_dir)
    sid, _ = lib.import_session(s)

    sid2, new2 = lib.import_session(parse_session(light_dir))
    assert sid2 == sid
    assert new2 is False

    frames = lib.frames(sid)
    assert len(frames) == s.frame_count == 4
    assert all(f["session_id"] == sid for f in frames)
    lib.close()


def test_different_folder_same_data_both_kept(tmp_path):
    """A fingerprint match from a DIFFERENT folder must no longer be
    silently dropped — both copies are cataloged as their own sessions."""
    light_dir, _ = write_demo_session(tmp_path / "original", n_lights=4, n_darks=2)
    copy_root = tmp_path / "backup_copy"
    copy_root.mkdir()
    copy_dir = copy_root / light_dir.name
    shutil.copytree(light_dir, copy_dir)

    lib = Library(db_path=tmp_path / "lib.db")
    sid1, new1 = lib.import_session(parse_session(light_dir))
    sid2, new2 = lib.import_session(parse_session(copy_dir))

    assert new1
    assert new2 is True, "the copied folder is a genuinely new path and must be reported as new"
    assert sid1 != sid2
    assert len(lib.sessions()) == 2
    lib.close()


def test_schema_version_stamped(tmp_path):
    db_path = tmp_path / "lib.db"
    lib = Library(db_path=db_path)
    assert lib.conn.execute("PRAGMA user_version").fetchone()[0] == 1

    light_dir, _ = write_demo_session(tmp_path / "data", n_lights=3, n_darks=1)
    sid, _ = lib.import_session(parse_session(light_dir))
    lib.close()

    # Reopening must not reset the version or lose data.
    lib2 = Library(db_path=db_path)
    assert lib2.conn.execute("PRAGMA user_version").fetchone()[0] == 1
    assert lib2.session(sid) is not None
    assert len(lib2.frames(sid)) == 3
    lib2.close()


def test_malformed_folder_name_never_raises(tmp_path):
    folder = tmp_path / "DWARF_RAW_TELE_X_EXP_1.2.3_GAIN_80_2026-01-01-00-00-00-000"
    folder.mkdir()
    for i in range(3):
        AstroImage(data=np.zeros((8, 8), dtype=np.float32)).save_fits(folder / f"{i:04d}.fits")

    s = parse_session(folder)  # must not raise
    assert s.exposure_s is None
    assert s.parse_notes


def test_ms_exposure_converted(tmp_path):
    folder = tmp_path / "DWARF_RAW_TELE_X_EXP_500ms_GAIN_80_2026-01-01-00-00-00-000"
    folder.mkdir()
    for i in range(3):
        AstroImage(data=np.zeros((8, 8), dtype=np.float32)).save_fits(folder / f"{i:04d}.fits")

    s = parse_session(folder)
    assert s.exposure_s == 0.5


def test_bad_encoding_shotsinfo(tmp_path):
    light_dir, _ = write_demo_session(tmp_path, n_lights=3, n_darks=1)
    (light_dir / "shotsInfo.json").write_bytes(b"\xff\xfe{bad")

    s = parse_session(light_dir)  # must not raise
    assert s.frame_count == 3
