"""AstroImage: the single image type every part of Umbra Noctis operates on.

Design rules:
- Pixel data is always float32 in a nominal [0, 1] range.
- ``data`` is either 2-D (mono, or an un-demosaiced CFA mosaic when ``cfa`` is
  set) or 3-D H×W×3 RGB.
- Every processing operation returns a NEW AstroImage and appends a history
  record, so any output can be reproduced from its inputs.
"""

from __future__ import annotations

import copy as _copy
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from astropy.io import fits

from .stats import luminance as _shared_luminance

# FITS keywords we normalize into AstroImage.meta, with fallback aliases.
_META_KEYS = {
    "exposure_s": ("EXPTIME", "EXPOSURE", "EXP"),
    "gain": ("GAIN", "EGAIN"),
    "date_obs": ("DATE-OBS", "DATE_OBS", "DATE"),
    "target": ("OBJECT", "TARGET"),
    "filter": ("FILTER", "FILT"),
    "instrument": ("INSTRUME", "INSTRUMENT", "CAMERA"),
    "telescope": ("TELESCOP",),
    "ra": ("RA", "OBJCTRA", "CRVAL1"),
    "dec": ("DEC", "OBJCTDEC", "CRVAL2"),
    "temperature_c": ("CCD-TEMP", "CCDTEMP", "TEMP"),
    "binning": ("XBINNING", "BINNING"),
}

_CFA_KEYS = ("BAYERPAT", "BAYER", "COLORTYP", "CFAPAT")
_VALID_CFA = {"RGGB", "BGGR", "GRBG", "GBRG"}

# Everything ``from_file`` can open, grouped by decoder.
FITS_SUFFIXES = {".fits", ".fit", ".fts"}
RAW_SUFFIXES = {".cr2", ".cr3", ".crw", ".nef", ".nrw", ".arw", ".dng",
                ".raf", ".orf", ".rw2", ".pef", ".srw"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
FRAME_SUFFIXES = FITS_SUFFIXES | RAW_SUFFIXES | IMAGE_SUFFIXES

# EXIF tags we normalize into AstroImage.meta (JPEG/TIFF from DSLRs).
_EXIF_KEYS = {
    "exposure_s": 0x829A,   # ExposureTime
    "gain": 0x8827,         # ISOSpeedRatings — closest analog to gain
    "instrument": 0x0110,   # Model
    "date_obs": 0x9003,     # DateTimeOriginal
}


@dataclass
class AstroImage:
    """An image plus everything we know about it."""

    data: np.ndarray
    meta: dict = field(default_factory=dict)
    fits_header: fits.Header | None = None
    cfa: str | None = None  # e.g. "RGGB" when data is a raw CFA mosaic
    linear: bool = True
    history: list = field(default_factory=list)
    source_path: Path | None = None

    # ------------------------------------------------------------------ shape
    @property
    def is_color(self) -> bool:
        return self.data.ndim == 3

    @property
    def height(self) -> int:
        return self.data.shape[0]

    @property
    def width(self) -> int:
        return self.data.shape[1]

    def luminance(self) -> np.ndarray:
        """Rec.709 luminance for color images; the data itself for mono."""
        return _shared_luminance(self.data)

    # ------------------------------------------------------------------- I/O
    @classmethod
    def from_fits(cls, path: str | Path) -> AstroImage:
        """Load a FITS file (Dwarf 3 sub, master, or stacked result).

        Integer data is scaled to [0, 1] by its dtype range. 3-plane cubes
        (3×H×W, as some stacked outputs use) are converted to H×W×3.
        """
        path = Path(path)
        with fits.open(path, memmap=False) as hdul:
            hdu = next((h for h in hdul if h.data is not None), None)
            if hdu is None:
                raise ValueError(f"No image data in {path}")
            raw = hdu.data
            header = hdu.header.copy()

        if raw.dtype.kind in "ui":
            scale = float(np.iinfo(raw.dtype).max)
            data = raw.astype(np.float32) / scale
        else:
            data = raw.astype(np.float32)
            # Float FITS from unknown pipelines: normalize only if clearly not 0..1
            if data.size and float(np.nanmax(data)) > 1.5:
                data = data / float(np.nanmax(data))
        data = np.nan_to_num(data, nan=0.0, posinf=1.0, neginf=0.0)

        if data.ndim == 3 and data.shape[0] == 3:  # planes-first cube -> H×W×3
            data = np.moveaxis(data, 0, -1)

        meta: dict[str, Any] = {}
        for key, aliases in _META_KEYS.items():
            for alias in aliases:
                if alias in header:
                    meta[key] = header[alias]
                    break

        cfa = None
        if data.ndim == 2:
            for key in _CFA_KEYS:
                val = str(header.get(key, "")).strip().upper()
                if val in _VALID_CFA:
                    cfa = val
                    break

        return cls(
            data=np.ascontiguousarray(data),
            meta=meta,
            fits_header=header,
            cfa=cfa,
            linear=True,
            source_path=path,
        )

    @classmethod
    def from_file(cls, path: str | Path) -> AstroImage:
        """Load any supported frame: FITS, camera raw (CR2/CR3/NEF/ARW/DNG/...),
        JPEG, PNG, or TIFF. This is the loader every pipeline should use so
        that DSLR frames work everywhere Dwarf 3 FITS frames do.
        """
        path = Path(path)
        suffix = path.suffix.lower()
        if suffix in FITS_SUFFIXES:
            return cls.from_fits(path)
        if suffix in RAW_SUFFIXES:
            return cls._from_camera_raw(path)
        if suffix in IMAGE_SUFFIXES:
            return cls._from_image_file(path)
        raise ValueError(f"Unsupported frame format '{suffix}' ({path})")

    @classmethod
    def _from_camera_raw(cls, path: Path) -> AstroImage:
        """Decode a DSLR/mirrorless raw file to linear RGB via rawpy/libraw."""
        try:
            import rawpy
        except ImportError:
            raise ImportError(
                f"Reading {path.suffix} camera raw files requires the 'rawpy' "
                "package. Install it with: pip install 'umbra-noctis[dslr]'"
            ) from None
        with rawpy.imread(str(path)) as raw:
            rgb = raw.postprocess(gamma=(1, 1), no_auto_bright=True,
                                  output_bps=16, use_camera_wb=True)
        data = np.ascontiguousarray(rgb.astype(np.float32) / 65535.0)
        img = cls(data=data, linear=True, source_path=path)
        img.record("load_raw", {"file": path.name})
        return img

    @classmethod
    def _from_image_file(cls, path: Path) -> AstroImage:
        """Load a JPEG/PNG/TIFF. Display-referred formats are flagged
        non-linear; EXIF exposure/ISO is carried into ``meta`` when present."""
        import tifffile
        from PIL import Image

        suffix = path.suffix.lower()
        meta: dict[str, Any] = {}
        if suffix in (".tif", ".tiff"):
            raw = tifffile.imread(path)
        else:
            with Image.open(path) as pil:
                try:
                    exif = pil.getexif()
                    merged = dict(exif) | dict(exif.get_ifd(0x8769))
                    for key, tag in _EXIF_KEYS.items():
                        if tag in merged:
                            val = merged[tag]
                            meta[key] = float(val) if key in ("exposure_s", "gain") \
                                else str(val)
                except Exception:
                    pass
                raw = np.asarray(pil.convert("RGB") if pil.mode not in
                                 ("L", "I;16", "I", "F", "RGB") else pil)

        if raw.dtype.kind in "ui":
            data = raw.astype(np.float32) / float(np.iinfo(raw.dtype).max)
        else:
            data = raw.astype(np.float32)
            if data.size and float(np.nanmax(data)) > 1.5:
                data = data / float(np.nanmax(data))
        data = np.nan_to_num(data, nan=0.0, posinf=1.0, neginf=0.0)
        if data.ndim == 3 and data.shape[2] > 3:  # drop alpha
            data = data[..., :3]

        # 16-bit TIFFs from astro tools are usually linear; 8-bit and JPEG are
        # display-referred (already gamma-encoded).
        linear = suffix in (".tif", ".tiff") and raw.dtype.itemsize > 1
        img = cls(data=np.ascontiguousarray(data), meta=meta,
                  linear=linear, source_path=path)
        img.record("load_image", {"file": path.name})
        return img

    def save_fits(self, path: str | Path, bits: int = 32) -> Path:
        """Write to FITS. ``bits=16`` writes uint16 (interchange), 32 writes
        float32 (full precision, recommended for intermediates)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.data
        if data.ndim == 3:  # store color as 3×H×W cube, the FITS convention
            data = np.moveaxis(data, -1, 0)
        if bits == 16:
            out = np.clip(data, 0.0, 1.0)
            out = (out * 65535.0 + 0.5).astype(np.uint16)
        else:
            out = data.astype(np.float32)

        header = fits.Header()
        if self.fits_header is not None:
            for card in self.fits_header.cards:
                try:
                    if card.keyword not in ("SIMPLE", "BITPIX", "NAXIS", "NAXIS1",
                                            "NAXIS2", "NAXIS3", "EXTEND", "BZERO",
                                            "BSCALE"):
                        header.append(card)
                except Exception:
                    continue
        if self.cfa:
            header["BAYERPAT"] = self.cfa
        header["SWCREATE"] = "Umbra Noctis"
        for entry in self.history:
            header.add_history(json.dumps(entry, default=str)[:70])

        fits.PrimaryHDU(data=out, header=header).writeto(path, overwrite=True)
        return path

    # -------------------------------------------------------------- lineage
    def copy(self) -> AstroImage:
        return AstroImage(
            data=self.data.copy(),
            meta=dict(self.meta),
            fits_header=self.fits_header.copy() if self.fits_header is not None else None,
            cfa=self.cfa,
            linear=self.linear,
            history=_copy.deepcopy(self.history),
            source_path=self.source_path,
        )

    def with_data(self, data: np.ndarray, **changes) -> AstroImage:
        """New image with replaced pixels; metadata/history carried forward."""
        img = self.copy()
        img.data = np.ascontiguousarray(data.astype(np.float32))
        for key, value in changes.items():
            setattr(img, key, value)
        return img

    def record(self, op: str, params: dict) -> None:
        self.history.append({
            "op": op,
            "params": params,
            "time": datetime.now(UTC).isoformat(timespec="seconds"),
        })

    def history_json(self) -> str:
        return json.dumps(self.history, indent=2, default=str)
