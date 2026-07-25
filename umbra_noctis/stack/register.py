"""Frame registration.

Solves a similarity transform (translation + rotation + scale) from each frame
to a reference frame — rotation support is mandatory for the Dwarf 3, whose
alt-az mode guarantees field rotation between subs.

Primary solver: ``astroalign`` (triangle star-pattern matching, robust to
large offsets). Fallback: phase correlation (translation only) so a sparse
field never hard-fails.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

try:
    import astroalign as _aa
    _HAVE_AA = True
except ImportError:  # pragma: no cover
    _HAVE_AA = False

from ..core.image import AstroImage


@dataclass
class Transform:
    """Similarity transform mapping frame coordinates -> reference coordinates."""
    rotation_deg: float
    scale: float
    dx: float
    dy: float
    matrix: np.ndarray          # 3×3 homogeneous
    method: str                 # "stars" | "phase" | "identity"
    n_matched: int = 0

    @classmethod
    def identity(cls) -> Transform:
        return cls(0.0, 1.0, 0.0, 0.0, np.eye(3), "identity")


def _lum(img: AstroImage) -> np.ndarray:
    lum = img.luminance()
    if img.cfa:
        # Superpixel: bin the CFA 2×2 so star patterns aren't mosaic-corrupted.
        h, w = lum.shape[0] // 2 * 2, lum.shape[1] // 2 * 2
        lum = lum[:h, :w].reshape(h // 2, 2, w // 2, 2).mean(axis=(1, 3))
    return np.ascontiguousarray(lum, dtype=np.float32)


def _solve_stars(src: np.ndarray, ref: np.ndarray) -> Transform | None:
    if not _HAVE_AA:
        return None
    try:
        tform, (matched_src, _) = _aa.find_transform(src, ref,
                                                     detection_sigma=5, max_control_points=75)
    except Exception:
        return None
    m = np.eye(3)
    m[:2, :] = tform.params[:2, :]
    return Transform(
        rotation_deg=float(np.degrees(tform.rotation)),
        scale=float(tform.scale),
        dx=float(tform.translation[0]),
        dy=float(tform.translation[1]),
        matrix=m,
        method="stars",
        n_matched=len(matched_src),
    )


def _solve_phase(src: np.ndarray, ref: np.ndarray) -> Transform:
    """Translation-only fallback via FFT phase correlation."""
    f0 = np.fft.rfft2(ref - ref.mean())
    f1 = np.fft.rfft2(src - src.mean())
    cross = f0 * np.conj(f1)
    cross /= np.abs(cross) + 1e-12
    corr = np.fft.irfft2(cross, s=ref.shape)
    peak = np.unravel_index(np.argmax(corr), corr.shape)
    dy, dx = peak
    if dy > ref.shape[0] // 2:
        dy -= ref.shape[0]
    if dx > ref.shape[1] // 2:
        dx -= ref.shape[1]
    m = np.eye(3)
    m[0, 2], m[1, 2] = dx, dy
    return Transform(0.0, 1.0, float(dx), float(dy), m, "phase")


def solve_transform(frame: AstroImage, reference: AstroImage) -> Transform:
    src, ref = _lum(frame), _lum(reference)
    t = _solve_stars(src, ref)
    if t is None:
        t = _solve_phase(src, ref)
    if frame.cfa:  # solved on 2×2 superpixels — scale translation back up
        t = Transform(t.rotation_deg, t.scale, t.dx * 2, t.dy * 2,
                      _scale_matrix(t.matrix, 2.0), t.method, t.n_matched)
    return t


def _scale_matrix(m: np.ndarray, factor: float) -> np.ndarray:
    s = np.diag([factor, factor, 1.0])
    return s @ m @ np.linalg.inv(s)


def warp(data: np.ndarray, transform: Transform, order: int = 1,
         output_shape: tuple | None = None, upscale: float = 1.0) -> np.ndarray:
    """Apply a transform (frame -> reference coords) to pixel data.

    ``upscale`` > 1 renders onto a finer grid (used by drizzle integration).
    Out-of-footprint pixels are filled with NaN so stacking can ignore them.
    """
    m = transform.matrix.copy()
    if upscale != 1.0:
        m = np.diag([upscale, upscale, 1.0]) @ m
    inv = np.linalg.inv(m)

    shape = output_shape or data.shape[:2]
    if upscale != 1.0 and output_shape is None:
        shape = (int(data.shape[0] * upscale), int(data.shape[1] * upscale))

    # scipy affine_transform maps output->input as (row, col); our matrix is (x, y)
    A = np.array([[inv[1, 1], inv[1, 0]], [inv[0, 1], inv[0, 0]]])
    offset = np.array([inv[1, 2], inv[0, 2]])

    def _one(plane):
        return ndimage.affine_transform(
            plane.astype(np.float32), A, offset=offset, output_shape=shape,
            order=order, mode="constant", cval=np.nan)

    if data.ndim == 3:
        return np.stack([_one(data[..., c]) for c in range(data.shape[2])], axis=-1)
    return _one(data)


def pick_reference(qualities: list) -> int:
    """Index of the best reference frame: highest composite quality score."""
    if not qualities:
        return 0
    best = max(range(len(qualities)),
               key=lambda i: getattr(qualities[i], "score", 0.0))
    return best


def register_frames(frames: list[AstroImage], reference_index: int = 0,
                    progress=None) -> list[Transform]:
    """Solve transforms for every frame against the chosen reference."""
    ref = frames[reference_index]
    out: list[Transform] = []
    for i, frame in enumerate(frames):
        if i == reference_index:
            out.append(Transform.identity())
        else:
            out.append(solve_transform(frame, ref))
        if progress:
            progress(i + 1, len(frames))
    return out
