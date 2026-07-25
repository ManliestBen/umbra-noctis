"""Per-frame quality metrics, scoring, and automatic sub rejection.

Metrics per frame:
- ``n_stars``      how many stars were detected (clouds collapse this)
- ``fwhm``         median star size in pixels (focus/seeing; lower is better)
- ``ellipticity``  median star elongation 0..1 (trailing; lower is better)
- ``background``   median sky level 0..1 (clouds/moonlight raise it)
- ``noise``        robust background RMS
- ``score``        composite 0..100, comparable *within* one session

Auto-rejection compares each frame against the session's own robust median:
a frame is rejected when any metric deviates by more than ``k`` MADs. This
adapts to the night — no absolute thresholds to tune.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from ..core.image import AstroImage
from ..core.stats import robust_sigma
from ..core.stats import robust_z as _robust_z
from .stars import detect_stars


@dataclass
class FrameQuality:
    path: str
    n_stars: int
    fwhm: float
    ellipticity: float
    background: float
    noise: float
    score: float = 0.0
    accepted: bool = True
    reject_reasons: list = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["reject_reasons"] = self.reject_reasons or []
        return d


def grade_frame(img: AstroImage, path: str | Path = "") -> FrameQuality:
    """Compute quality metrics for one frame (works on CFA or RGB data)."""
    lum = img.luminance()
    stars = detect_stars(lum)
    med = float(np.median(lum))
    mad = robust_sigma(lum)  # default eps=1e-9 — deliberate: this site had none before
    if len(stars) >= 3:
        fwhm = float(np.median(stars["fwhm"]))
        ecc = float(np.median(stars["ellipticity"]))
    else:
        fwhm, ecc = float("nan"), float("nan")
    return FrameQuality(
        path=str(path or img.source_path or ""),
        n_stars=int(len(stars)),
        fwhm=fwhm,
        ellipticity=ecc,
        background=med,
        noise=mad,
    )


def grade_session(frames: list[str | Path], k: float = 3.5,
                  min_star_fraction: float = 0.3,
                  progress=None) -> list[FrameQuality]:
    """Grade every frame in a session and mark rejects.

    Rejection rules (any one triggers):
    - star count below ``min_star_fraction`` × session median  → "clouds"
    - FWHM more than ``k`` MADs above median                   → "soft/defocus"
    - ellipticity more than ``k`` MADs above median            → "trailing"
    - background more than ``k`` MADs above median             → "bright sky"
    Scores are 0–100 percentile-composites within the session.
    """
    results: list[FrameQuality] = []
    for i, path in enumerate(frames):
        q = grade_frame(AstroImage.from_file(path), path)
        results.append(q)
        if progress:
            progress(i + 1, len(frames))
    if not results:
        return results

    n_stars = np.array([q.n_stars for q in results], dtype=float)
    fwhm = np.array([q.fwhm for q in results])
    ecc = np.array([q.ellipticity for q in results])
    bg = np.array([q.background for q in results])

    star_med = max(np.nanmedian(n_stars), 1.0)
    z_fwhm, z_ecc, z_bg = _robust_z(fwhm), _robust_z(ecc), _robust_z(bg)

    for i, q in enumerate(results):
        reasons = []
        if n_stars[i] < min_star_fraction * star_med:
            reasons.append("clouds (few stars)")
        if np.isfinite(z_fwhm[i]) and z_fwhm[i] > k:
            reasons.append("soft focus / poor seeing")
        if np.isfinite(z_ecc[i]) and z_ecc[i] > k:
            reasons.append("star trailing")
        if z_bg[i] > k:
            reasons.append("bright background")
        q.reject_reasons = reasons
        q.accepted = not reasons

    score_qualities(results)
    return results


def score_qualities(results: list[FrameQuality]) -> list[FrameQuality]:
    """Composite 0-100 quality score, rank-based so it is robust to outliers.

    Sets ``score`` in place on every :class:`FrameQuality` in ``results`` and
    returns the same list. Used by :func:`grade_session` and by
    ``stack.integrate`` when it grades frames itself.
    """
    if not results:
        return results
    n_stars = np.array([q.n_stars for q in results], dtype=float)
    fwhm = np.array([q.fwhm for q in results])
    ecc = np.array([q.ellipticity for q in results])
    bg = np.array([q.background for q in results])

    def pct_rank(vals, invert=False):
        v = np.where(np.isfinite(vals), vals, np.nanmax(vals) if np.isfinite(vals).any() else 0)
        order = v.argsort()
        ranks = np.empty_like(order, dtype=float)
        ranks[order] = np.linspace(0, 1, len(v)) if len(v) > 1 else [0.5]
        return 1.0 - ranks if invert else ranks

    score = (0.35 * pct_rank(n_stars)
             + 0.30 * pct_rank(fwhm, invert=True)
             + 0.20 * pct_rank(ecc, invert=True)
             + 0.15 * pct_rank(bg, invert=True))
    for q, s in zip(results, score, strict=False):
        q.score = round(float(s) * 100, 1)
    return results


def select_best(results: list[FrameQuality], fraction: float = 0.8) -> list[FrameQuality]:
    """Keep the best ``fraction`` of accepted frames by composite score."""
    accepted = [q for q in results if q.accepted]
    accepted.sort(key=lambda q: q.score, reverse=True)
    n = max(1, int(round(len(accepted) * fraction)))
    keep = set(id(q) for q in accepted[:n])
    for q in results:
        if q.accepted and id(q) not in keep:
            q.accepted = False
            q.reject_reasons = (q.reject_reasons or []) + [f"below best-{int(fraction*100)}% cut"]
    return [q for q in results if q.accepted]
