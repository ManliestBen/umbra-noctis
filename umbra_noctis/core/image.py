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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
from astropy.io import fits

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


@dataclass
class AstroImage:
    """An image plus everything we know about it."""

    data: np.ndarray
    meta: dict = field(default_factory=dict)
    fits_header: Optional[fits.Header] = None
    cfa: Optional[str] = None  # e.g. "RGGB" when data is a raw CFA mosaic
    linear: bool = True
    history: list = field(default_factory=list)
    source_path: Optional[Path] = None

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
        if self.is_color:
            d = self.data
            return 0.2126 * d[..., 0] + 0.7152 * d[..., 1] + 0.0722 * d[..., 2]
        return self.data

    # ------------------------------------------------------------------- I/O
    @classmethod
    def from_fits(cls, path: str | Path) -> "AstroImage":
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

    def save_fits(self, path: str | Path, bits: int = 32) -> Path:
        """Write to FITS. ``bits=16`` writes uint16 (interchange), 32 writes
        float32 (full precision, recommended for intermediates)."""
        path = Path(path)
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
    def copy(self) -> "AstroImage":
        return AstroImage(
            data=self.data.copy(),
            meta=dict(self.meta),
            fits_header=self.fits_header.copy() if self.fits_header is not None else None,
            cfa=self.cfa,
            linear=self.linear,
            history=_copy.deepcopy(self.history),
            source_path=self.source_path,
        )

    def with_data(self, data: np.ndarray, **changes) -> "AstroImage":
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
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })

    def history_json(self) -> str:
        return json.dumps(self.history, indent=2, default=str)
