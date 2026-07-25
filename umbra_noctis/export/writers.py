"""Image export: 16-bit TIFF/PNG, JPEG, FITS, and comparison images."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import tifffile
from PIL import Image

from ..core.image import AstroImage
from ..process.display import auto_stretch_display


def _to_uint(data: np.ndarray, bits: int) -> np.ndarray:
    clipped = np.clip(data, 0.0, 1.0)
    if bits == 16:
        return (clipped * 65535.0 + 0.5).astype(np.uint16)
    return (clipped * 255.0 + 0.5).astype(np.uint8)


def _write_sidecar(img: AstroImage, path: Path) -> None:
    """Write a ``<output>.umbra.json`` provenance sidecar next to a
    display-format export (JPEG/TIFF/PNG lose the FITS-only history/meta
    otherwise, so "every step recorded" was only true for FITS)."""
    sidecar = {
        "sidecar_version": 1,
        "output": path.name,
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "software": "Umbra Noctis",
        "source": str(img.source_path) if img.source_path else None,
        "meta": {k: v for k, v in img.meta.items() if isinstance(v, (str, int, float, bool))},
        "history": img.history,
    }
    Path(str(path) + ".umbra.json").write_text(json.dumps(sidecar, indent=2, default=str))


def export_image(img: AstroImage, path: str | Path, quality: int = 92,
                 autostretch_if_linear: bool = True, resize_long_edge: int = 0,
                 sidecar: bool = True) -> Path:
    """Export to the format implied by the extension.

    - ``.tif/.tiff``  16-bit TIFF (best for further editing elsewhere)
    - ``.png``        16-bit PNG
    - ``.jpg/.jpeg``  8-bit JPEG at ``quality``
    - ``.fits``       32-bit float FITS (full fidelity)

    Linear data exported to a display format is autostretched first (disable
    with ``autostretch_if_linear=False`` if you really want a black JPEG).

    A ``<output>.umbra.json`` provenance sidecar (history + metadata) is
    written next to every non-FITS export unless ``sidecar=False`` — FITS
    already carries this in its header, so it's skipped there.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    data = img.data

    if suffix in (".fits", ".fit"):
        img.save_fits(path)
        return path

    if img.linear and autostretch_if_linear:
        data = auto_stretch_display(data)

    if resize_long_edge and max(data.shape[:2]) > resize_long_edge:
        import cv2
        scale = resize_long_edge / max(data.shape[:2])
        data = cv2.resize(data, (int(data.shape[1] * scale), int(data.shape[0] * scale)),
                          interpolation=cv2.INTER_AREA)

    if suffix in (".tif", ".tiff"):
        tifffile.imwrite(path, _to_uint(data, 16), photometric=(
            "rgb" if data.ndim == 3 else "minisblack"))
    elif suffix == ".png":
        arr = _to_uint(data, 16)
        mode = "RGB" if data.ndim == 3 else "I;16"
        if data.ndim == 3:
            # Pillow has no native 16-bit RGB PNG; use 8-bit there, 16-bit for mono
            Image.fromarray(_to_uint(data, 8), "RGB").save(path, optimize=True)
        else:
            Image.fromarray(arr, mode).save(path, optimize=True)
    elif suffix in (".jpg", ".jpeg"):
        arr = _to_uint(data, 8)
        mode = "RGB" if data.ndim == 3 else "L"
        Image.fromarray(arr, mode).save(path, quality=quality, optimize=True)
    else:
        raise ValueError(f"Unknown export format: {suffix}")
    if sidecar:
        _write_sidecar(img, path)
    return path


def save_comparison(before: AstroImage, after: AstroImage, path: str | Path,
                    labels: tuple[str, str] = ("Before", "After")) -> Path:
    """Side-by-side before/after JPEG — ready for a forum post."""
    from PIL import ImageDraw

    def prep(im: AstroImage):
        d = auto_stretch_display(im.data) if im.linear else np.clip(im.data, 0, 1)
        arr = _to_uint(d, 8)
        if arr.ndim == 2:
            arr = np.repeat(arr[..., None], 3, axis=2)
        return arr

    a, b = prep(before), prep(after)
    h = min(a.shape[0], b.shape[0])

    def fit(arr):
        import cv2
        scale = h / arr.shape[0]
        return cv2.resize(arr, (int(arr.shape[1] * scale), h))

    a, b = fit(a), fit(b)
    gap = 4
    canvas = np.zeros((h, a.shape[1] + b.shape[1] + gap, 3), dtype=np.uint8)
    canvas[:, :a.shape[1]] = a
    canvas[:, a.shape[1] + gap:] = b
    pil = Image.fromarray(canvas)
    draw = ImageDraw.Draw(pil)
    draw.text((12, 12), labels[0], fill=(255, 255, 100))
    draw.text((a.shape[1] + gap + 12, 12), labels[1], fill=(255, 255, 100))
    pil.save(Path(path), quality=90)
    return Path(path)
