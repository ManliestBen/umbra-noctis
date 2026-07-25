"""Plate solving adapters.

Umbra Noctis does not bundle astrometric index files (they are gigabytes);
instead it drives whichever solver you have, in this order:

1. **ASTAP** (``astap`` binary) — fast, small database, recommended.
2. **astrometry.net local** (``solve-field``) — the classic.
3. **nova.astrometry.net web API** — no install needed; set an API key with
   the ``UMBRA_ASTROMETRY_KEY`` environment variable (free at nova.astrometry.net).

The result is a WCS-bearing FITS header written back onto the image, which
enables annotation and photometric work.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from astropy.io import fits
from astropy.wcs import WCS

from ..core.image import AstroImage

# Dwarf 3 telephoto: 3840 px × 2 µm on 150 mm -> ~2.75 arcsec/px, FOV ~2.9°×1.7°
DWARF3_SCALE_ARCSEC = 2.75


@dataclass
class SolveResult:
    success: bool
    solver: str
    ra_deg: float | None = None
    dec_deg: float | None = None
    scale_arcsec: float | None = None
    rotation_deg: float | None = None
    wcs: object | None = None
    message: str = ""


def solve_image(img_or_path: AstroImage | str | Path, timeout: int = 120) -> SolveResult:
    """Try every available solver in order. See module docstring."""
    if isinstance(img_or_path, AstroImage):
        # The whole solver loop runs inside this directory's lifetime, so any
        # sidecar files a backend writes next to the temp FITS (ASTAP's
        # .wcs/.ini, for a path we made up ourselves) are swept away with it —
        # no leaked fd, no full-size image copy left behind in /tmp.
        with tempfile.TemporaryDirectory(prefix="umbra_solve_img_") as tmpdir:
            path = Path(tmpdir) / "image.fits"
            img_or_path.save_fits(path, bits=16)
            return _run_solvers(path, timeout)
    return _run_solvers(Path(img_or_path), timeout)


def _run_solvers(path: Path, timeout: int) -> SolveResult:
    for solver in (_solve_astap, _solve_field, _solve_nova):
        try:
            result = solver(path, timeout)
        except Exception as exc:
            result = SolveResult(False, solver.__name__, message=str(exc))
        if result.success:
            return result
    return SolveResult(False, "none",
                       message="No solver succeeded. Install ASTAP or solve-field, or set "
                               "UMBRA_ASTROMETRY_KEY for the web API (see docs/PLATE_SOLVING.md).")


def _wcs_from_header(hdr) -> SolveResult:
    w = WCS(hdr)
    if not w.has_celestial:
        return SolveResult(False, "wcs", message="no celestial WCS in solution")
    ra, dec = float(hdr.get("CRVAL1", 0)), float(hdr.get("CRVAL2", 0))
    try:
        import numpy as np
        from astropy.wcs.utils import proj_plane_pixel_scales
        scale = float(proj_plane_pixel_scales(w.celestial).mean() * 3600)
        cd = w.celestial.pixel_scale_matrix
        rot = float(np.degrees(np.arctan2(cd[1, 0], cd[0, 0])))
    except Exception:
        scale, rot = None, None
    return SolveResult(True, "", ra_deg=ra, dec_deg=dec, scale_arcsec=scale,
                       rotation_deg=rot, wcs=w)


def _solve_astap(path: Path, timeout: int) -> SolveResult:
    exe = shutil.which("astap") or shutil.which("astap_cli")
    if not exe:
        return SolveResult(False, "astap", message="astap not installed")
    wcs_out = path.with_suffix(".wcs")
    ini = path.with_suffix(".ini")
    # ASTAP writes these sidecars next to the input; if we didn't already
    # have one there before calling it, we clean up after ourselves — the
    # input path may be a real file the caller owns, not a temp of ours.
    wcs_existed, ini_existed = wcs_out.exists(), ini.exists()
    try:
        proc = subprocess.run(
            [exe, "-f", str(path), "-r", "30", "-z", "0"],
            capture_output=True, timeout=timeout, text=True)
        if proc.returncode != 0 or not (wcs_out.exists() or ini.exists()):
            return SolveResult(False, "astap", message=proc.stderr[:300] or "no solution")
        hdr = fits.Header.fromtextfile(wcs_out) if wcs_out.exists() else _ini_to_header(ini)
        r = _wcs_from_header(hdr)
        r.solver = "astap"
        return r
    finally:
        if not wcs_existed and wcs_out.exists():
            wcs_out.unlink()
        if not ini_existed and ini.exists():
            ini.unlink()


def _ini_to_header(ini: Path):
    hdr = fits.Header()
    for line in ini.read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            try:
                hdr[k.strip()[:8]] = float(v.strip())
            except ValueError:
                pass
    return hdr


def _solve_field(path: Path, timeout: int) -> SolveResult:
    exe = shutil.which("solve-field")
    if not exe:
        return SolveResult(False, "solve-field", message="astrometry.net not installed")
    with tempfile.TemporaryDirectory(prefix="umbra_solve_") as outdir_name:
        outdir = Path(outdir_name)
        proc = subprocess.run(
            [exe, str(path), "--overwrite", "--no-plots", "--dir", str(outdir),
             "--scale-units", "arcsecperpix",
             "--scale-low", str(DWARF3_SCALE_ARCSEC * 0.5),
             "--scale-high", str(DWARF3_SCALE_ARCSEC * 2.0)],
            capture_output=True, timeout=timeout, text=True)
        solved = list(outdir.glob("*.wcs"))
        if proc.returncode != 0 or not solved:
            return SolveResult(False, "solve-field", message=proc.stderr[:300] or "no solution")
        with fits.open(solved[0]) as hdul:
            r = _wcs_from_header(hdul[0].header)
        r.solver = "solve-field"
        return r


_NOVA = "https://nova.astrometry.net/api/"


def _nova_post(url, data, headers=None):
    """The one HTTP call nova solving makes — a module-level seam so tests
    can monkeypatch it instead of hitting the network."""
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _solve_nova(path: Path, timeout: int) -> SolveResult:
    key = os.environ.get("UMBRA_ASTROMETRY_KEY")
    if not key:
        return SolveResult(False, "nova", message="UMBRA_ASTROMETRY_KEY not set")

    login = _nova_post(
        _NOVA + "login",
        urllib.parse.urlencode({"request-json": json.dumps({"apikey": key})}).encode())
    if login.get("status") != "success":
        return SolveResult(False, "nova", message="login failed")
    session = login["session"]

    boundary = "umbraboundary"
    payload = json.dumps({"session": session, "publicly_visible": "n",
                          "scale_units": "arcsecperpix",
                          "scale_lower": DWARF3_SCALE_ARCSEC * 0.5,
                          "scale_upper": DWARF3_SCALE_ARCSEC * 2.0})
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"request-json\"\r\n\r\n"
        f"{payload}\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"{path.name}\"\r\nContent-Type: application/octet-stream\r\n\r\n"
    ).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    up = _nova_post(_NOVA + "upload", body,
                    {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    if up.get("status") != "success":
        return SolveResult(False, "nova", message="upload failed")
    subid = up["subid"]

    deadline = time.time() + timeout
    jobid = None
    while time.time() < deadline:
        sub = _nova_post(_NOVA + f"submissions/{subid}", b"")
        jobs = [j for j in sub.get("jobs", []) if j]
        if jobs:
            jobid = jobs[0]
            status = _nova_post(_NOVA + f"jobs/{jobid}", b"").get("status")
            if status == "success":
                info = _nova_post(_NOVA + f"jobs/{jobid}/calibration/", b"")
                try:
                    ra_deg = float(info.get("ra"))
                    dec_deg = float(info.get("dec"))
                except (TypeError, ValueError):
                    return SolveResult(
                        False, "nova",
                        message=f"web solve returned incomplete calibration: {info!r}")
                return SolveResult(True, "nova",
                                   ra_deg=ra_deg, dec_deg=dec_deg,
                                   scale_arcsec=info.get("pixscale"),
                                   rotation_deg=info.get("orientation"))
            if status == "failure":
                return SolveResult(False, "nova", message="web solve failed")
        time.sleep(5)
    return SolveResult(False, "nova", message="web solve timed out")
