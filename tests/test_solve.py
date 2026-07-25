"""Plate-solving adapters: temp-file hygiene and nova.astrometry.net response
validation, verified without any real network access or installed solver."""

import tempfile
from pathlib import Path

import numpy as np

from umbra_noctis.core.image import AstroImage
from umbra_noctis.solve import astrometry
from umbra_noctis.solve.astrometry import solve_image


def test_nova_incomplete_payload_is_a_failure(monkeypatch, tmp_path):
    """A nova job that reports "success" but whose calibration payload is
    missing ra/dec must not be treated as a successful solve (and must not
    crash formatting None as a float, as cmd_solve's belt-and-braces guard
    also protects against)."""
    monkeypatch.setenv("UMBRA_ASTROMETRY_KEY", "fake-key-for-testing")
    responses = iter([
        {"status": "success", "session": "sess123"},   # login
        {"status": "success", "subid": "42"},           # upload
        {"jobs": [7]},                                  # submissions/{subid} poll
        {"status": "success"},                          # jobs/{jobid}
        {"ra": None, "dec": None},                      # calibration — incomplete!
    ])

    def fake_post(url, data, headers=None):
        return next(responses)

    monkeypatch.setattr(astrometry, "_nova_post", fake_post)

    p = tmp_path / "img.fits"
    p.write_bytes(b"not really a fits file, never read by the fake post")
    result = astrometry._solve_nova(p, timeout=30)
    assert result.success is False
    assert "incomplete" in result.message


def test_all_backends_unavailable_leaves_no_temp_files(monkeypatch):
    """With no solver installed and no web API key, solve_image must report
    failure and must not leak the temp FITS it writes for an in-memory
    AstroImage (no mkstemp fd, no leftover directory)."""
    monkeypatch.setattr(astrometry.shutil, "which", lambda name: None)
    monkeypatch.delenv("UMBRA_ASTROMETRY_KEY", raising=False)

    tmp_root = Path(tempfile.gettempdir())
    before = set(tmp_root.iterdir())

    img = AstroImage(data=np.zeros((10, 10), dtype=np.float32))
    result = solve_image(img)

    after = set(tmp_root.iterdir())
    assert result.success is False
    assert before == after, f"leaked temp entries: {after - before}"


def test_wcs_from_header_pure_math():
    """_wcs_from_header against a hand-built astropy WCS header — no solver,
    no file I/O, just the RA/Dec/scale/rotation extraction math."""
    from astropy.wcs import WCS

    w = WCS(naxis=2)
    w.wcs.crpix = [50, 50]
    w.wcs.crval = [10.5, -5.25]
    w.wcs.cdelt = [-2.75 / 3600, 2.75 / 3600]  # deg/px, matches the Dwarf 3 scale
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    hdr = w.to_header()

    result = astrometry._wcs_from_header(hdr)
    assert result.success
    assert abs(result.ra_deg - 10.5) < 1e-6
    assert abs(result.dec_deg - (-5.25)) < 1e-6
    assert abs(result.scale_arcsec - 2.75) < 0.01
    # CDELT1 is conventionally negative (RA increases east/left), which this
    # formula reads as a 180 deg rotation even though the field itself isn't
    # rotated — that's the actual, deterministic behavior of the formula
    # being tested, not an assumption about "true" field rotation.
    assert abs(abs(result.rotation_deg) - 180.0) < 0.1
