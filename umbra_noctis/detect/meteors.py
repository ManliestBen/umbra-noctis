"""Meteor quick-scan: find the few frames in a night that contain a streak.

A meteor-shower session produces hundreds of near-identical frames; culling
them by eye is the worst part of the workflow. This scanner streams through a
folder and flags frames containing transient streaks:

1. Each frame's luminance is compared against the *maximum* of its two
   neighbors — anything static (stars, hot pixels, skyglow, landscape)
   cancels, because a star that drifted a pixel between frames is still
   covered by the neighbor maximum. What survives appeared in ONE frame only.
2. The residual is thresholded robustly (median + k·MAD) and line segments
   are extracted with a probabilistic Hough transform.
3. Streaks that continue along the same line in consecutive frames are
   reclassified as satellites/aircraft — those cross the sky over many
   exposures, while a real meteor lives and dies inside a single one.

Everything runs on downscaled luminance, so a 400-frame DSLR night scans in
about the time of a coffee refill, holding only three small frames in memory.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from ..core.image import AstroImage
from ..core.stats import robust_sigma


@dataclass
class Streak:
    """One detected line segment, in full-resolution pixel coordinates."""
    x0: float
    y0: float
    x1: float
    y1: float
    length: float
    angle_deg: float           # 0..180, measured from +x axis
    brightness: float          # mean residual brightness along the segment

    @property
    def midpoint(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2.0, (self.y0 + self.y1) / 2.0)


@dataclass
class FrameScan:
    """Scan result for one frame."""
    path: Path
    index: int
    streaks: list[Streak] = field(default_factory=list)
    verdict: str = "clean"     # "meteor" | "satellite" | "clean"

    @property
    def longest(self) -> Streak | None:
        return max(self.streaks, key=lambda s: s.length, default=None)


def _luminance_small(path: Path, max_width: int = 1024) -> tuple[np.ndarray, float]:
    """Load a frame's luminance downscaled for detection; returns (lum, scale)
    where full_res_coord = detected_coord / scale."""
    img = AstroImage.from_file(path)
    lum = img.luminance()
    if img.cfa:  # 2×2 superpixel binning removes the CFA checkerboard
        h, w = lum.shape[0] // 2 * 2, lum.shape[1] // 2 * 2
        lum = lum[:h, :w].reshape(h // 2, 2, w // 2, 2).mean(axis=(1, 3))
    scale = 0.5 if img.cfa else 1.0
    if lum.shape[1] > max_width:
        f = max_width / lum.shape[1]
        lum = cv2.resize(lum, (max_width, int(lum.shape[0] * f)),
                         interpolation=cv2.INTER_AREA)
        scale *= f
    return np.ascontiguousarray(lum, dtype=np.float32), scale


def _find_streaks(residual: np.ndarray, scale: float, k_sigma: float,
                  min_length: float) -> list[Streak]:
    med = float(np.median(residual))
    mad = robust_sigma(residual, eps=1e-6)
    mask = ((residual - med) > k_sigma * mad).astype(np.uint8) * 255
    # connect the dashes a defocused or faint streak breaks into
    mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    min_len_small = max(8, int(min_length * scale))
    lines = cv2.HoughLinesP(mask, 1, np.pi / 180, threshold=20,
                            minLineLength=min_len_small, maxLineGap=6)
    if lines is None:
        return []
    streaks = []
    for x0, y0, x1, y1 in np.asarray(lines).reshape(-1, 4):
        length = math.hypot(x1 - x0, y1 - y0)
        angle = math.degrees(math.atan2(y1 - y0, x1 - x0)) % 180.0
        n = max(int(length), 2)
        xs = np.linspace(x0, x1, n).astype(int)
        ys = np.linspace(y0, y1, n).astype(int)
        bright = float(residual[ys.clip(0, residual.shape[0] - 1),
                                xs.clip(0, residual.shape[1] - 1)].mean())
        streaks.append(Streak(x0 / scale, y0 / scale, x1 / scale, y1 / scale,
                              length / scale, angle, bright))
    # Longest first; keep a handful — dozens of Hough hits on one streak are
    # fragments of the same event.
    streaks.sort(key=lambda s: -s.length)
    return streaks[:8]


def _colinear(a: Streak, b: Streak, angle_tol: float = 8.0,
              dist_tol: float = 40.0) -> bool:
    """True if ``b`` lies along the same sky path as ``a`` (satellite track)."""
    da = abs(a.angle_deg - b.angle_deg)
    if min(da, 180.0 - da) > angle_tol:
        return False
    # distance of b's midpoint from the infinite line through a
    dx, dy = a.x1 - a.x0, a.y1 - a.y0
    norm = math.hypot(dx, dy)
    if norm < 1e-6:
        return False
    mx, my = b.midpoint
    dist = abs(dy * (mx - a.x0) - dx * (my - a.y0)) / norm
    return dist < dist_tol


def scan_for_meteors(paths: list[str | Path], min_length: float = 40.0,
                     k_sigma: float = 6.0, max_width: int = 1024,
                     progress=None, log=None) -> list[FrameScan]:
    """Scan ``paths`` (chronological order) for transient streaks.

    ``min_length`` — shortest streak worth reporting, in full-res pixels.
    ``k_sigma`` — detection threshold above the residual's noise floor.
    Returns one :class:`FrameScan` per frame; check ``verdict``.
    """
    paths = [Path(p) for p in paths]
    results = [FrameScan(path=p, index=i) for i, p in enumerate(paths)]
    if len(paths) < 3:
        if log:
            log("Need at least 3 frames to separate streaks from stars")
        return results

    prev_lum, scale = _luminance_small(paths[0], max_width)
    cur_lum, _ = _luminance_small(paths[1], max_width)

    # Frame 0 has no frame before it — compared against its one neighbor
    # (frame 1) alone, instead of being structurally unscannable forever.
    if prev_lum.shape == cur_lum.shape:
        residual0 = prev_lum - cur_lum
        results[0].streaks = _find_streaks(residual0, scale, k_sigma, min_length)
        if results[0].streaks:
            results[0].verdict = "meteor"
    elif log:
        log(f"SKIP shape mismatch: {paths[0].name} {prev_lum.shape} != "
            f"{paths[1].name} {cur_lum.shape}")

    for i in range(1, len(paths) - 1):
        next_lum, _ = _luminance_small(paths[i + 1], max_width)
        if cur_lum.shape == prev_lum.shape == next_lum.shape:
            residual = cur_lum - np.maximum(prev_lum, next_lum)
            results[i].streaks = _find_streaks(residual, scale, k_sigma, min_length)
            if results[i].streaks:
                results[i].verdict = "meteor"
        elif log:
            log(f"SKIP shape mismatch at frame {i} ({paths[i].name}): "
                f"prev={prev_lum.shape} cur={cur_lum.shape} next={next_lum.shape}")
        prev_lum, cur_lum = cur_lum, next_lum
        if progress:
            progress("scan", i + 1, len(paths))
    if progress:
        progress("scan", len(paths), len(paths))

    # Last frame has no frame after it — same single-neighbor treatment,
    # using the values the streaming loop above already holds: cur_lum is
    # now the last frame's luminance, prev_lum the one before it.
    last = len(paths) - 1
    if prev_lum.shape == cur_lum.shape:
        residual_last = cur_lum - prev_lum
        results[last].streaks = _find_streaks(residual_last, scale, k_sigma, min_length)
        if results[last].streaks:
            results[last].verdict = "meteor"
    elif log:
        log(f"SKIP shape mismatch: {paths[last - 1].name} {prev_lum.shape} != "
            f"{paths[last].name} {cur_lum.shape}")

    # Satellite/aircraft pass: a streak whose line continues in an adjacent
    # frame is a track, not a meteor.
    for i, cur in enumerate(results):
        if cur.verdict != "meteor":
            continue
        for j in (i - 1, i + 1):
            if 0 <= j < len(results) and results[j].streaks:
                if any(_colinear(a, b) for a in cur.streaks
                       for b in results[j].streaks):
                    cur.verdict = "satellite"
                    break
    for r in results:
        if r.verdict == "satellite":
            for j in (r.index - 1, r.index + 1):
                if 0 <= j < len(results) and results[j].verdict == "meteor" and \
                        any(_colinear(a, b) for a in r.streaks
                            for b in results[j].streaks):
                    results[j].verdict = "satellite"

    n_meteor = sum(1 for r in results if r.verdict == "meteor")
    n_sat = sum(1 for r in results if r.verdict == "satellite")
    if log:
        log(f"{n_meteor} meteor candidate(s), {n_sat} satellite/aircraft "
            f"track(s) in {len(paths)} frames")
    return results


def annotate_scan(scan: FrameScan, out_path: str | Path) -> Path:
    """Write a JPEG of the frame with its detected streaks outlined."""
    from ..export import export_image
    img = AstroImage.from_file(scan.path)
    if img.cfa:
        from ..stack.integrate import demosaic
        img = demosaic(img, "bilinear")
    out_path = Path(out_path)
    export_image(img, out_path, resize_long_edge=2000)
    jpeg = cv2.imread(str(out_path))
    if jpeg is None:
        raise RuntimeError(f"could not re-read {out_path} for annotation")
    f = max(jpeg.shape[:2]) / max(img.height, img.width)
    for s in scan.streaks:
        p0 = (int(s.x0 * f), int(s.y0 * f))
        p1 = (int(s.x1 * f), int(s.y1 * f))
        cv2.line(jpeg, p0, p1, (0, 0, 255), 2, cv2.LINE_AA)
        cv2.putText(jpeg, f"{s.length:.0f}px", (p0[0] + 6, p0[1] - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 1, cv2.LINE_AA)
    cv2.imwrite(str(out_path), jpeg)
    return out_path
