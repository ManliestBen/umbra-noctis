"""Lucky imaging: planetary/lunar stacking from Dwarf 3 video captures.

The atmosphere blurs each video frame differently; a few frames are "lucky"
and sharp. The pipeline: score every frame's sharpness -> keep the best N% ->
align them (phase correlation on the planet/feature) -> average -> wavelet
sharpen (use the ``sharpen`` op, scale="fine", afterwards).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from ..core.image import AstroImage


@dataclass
class LuckyResult:
    image: AstroImage
    n_frames_total: int
    n_frames_used: int
    sharpness: list = field(default_factory=list)


def _sharpness(gray: np.ndarray) -> float:
    """Variance of the Laplacian — the standard focus/seeing metric."""
    return float(cv2.Laplacian(gray, cv2.CV_32F).var())


def lucky_stack(video_path: str | Path, keep_fraction: float = 0.25,
                max_frames: int = 2000, crop_to_subject: bool = True,
                progress=None) -> LuckyResult:
    """Stack the sharpest frames of a planetary/lunar video (MP4/AVI).

    ``keep_fraction=0.25`` keeps the best 25% — a good default for average
    seeing; drop to 0.1 in poor seeing, raise to 0.5 in excellent seeing.
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"Cannot open video {video_path}")

    frames: list[np.ndarray] = []
    scores: list[float] = []
    while len(frames) < max_frames:
        ok, frame = cap.read()
        if not ok:
            break
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        frames.append(rgb)
        scores.append(_sharpness(gray))
        if progress and len(frames) % 50 == 0:
            progress("read", len(frames), max_frames)
    cap.release()
    if not frames:
        raise ValueError("Video contains no readable frames")

    order = np.argsort(scores)[::-1]
    n_keep = max(1, int(len(frames) * keep_fraction))
    chosen = order[:n_keep]

    # Reference = sharpest frame. Align others by phase correlation on luminance.
    ref = frames[chosen[0]]
    ref_gray = ref.mean(axis=2)

    if crop_to_subject:
        ys, xs = np.nonzero(ref_gray > ref_gray.max() * 0.15)
        if len(xs) > 100:
            pad = 60
            x0, x1 = max(0, xs.min() - pad), min(ref.shape[1], xs.max() + pad)
            y0, y1 = max(0, ys.min() - pad), min(ref.shape[0], ys.max() + pad)
        else:
            x0, y0, x1, y1 = 0, 0, ref.shape[1], ref.shape[0]
    else:
        x0, y0, x1, y1 = 0, 0, ref.shape[1], ref.shape[0]

    ref_crop = ref_gray[y0:y1, x0:x1]
    acc = np.zeros_like(frames[0])
    weight = 0.0
    for i, idx in enumerate(chosen):
        f = frames[idx]
        g = f.mean(axis=2)[y0:y1, x0:x1]
        try:
            (dx, dy), _ = cv2.phaseCorrelate(ref_crop.astype(np.float64),
                                             g.astype(np.float64))
        except cv2.error:
            dx = dy = 0.0
        m = np.float32([[1, 0, -dx], [0, 1, -dy]])
        aligned = cv2.warpAffine(f, m, (f.shape[1], f.shape[0]),
                                 flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        acc += aligned
        weight += 1.0
        if progress:
            progress("stack", i + 1, n_keep)

    stacked = (acc / weight)[y0:y1, x0:x1]
    img = AstroImage(data=np.clip(stacked, 0, 1).astype(np.float32), linear=False)
    img.meta["source_video"] = str(video_path)
    img.record("lucky_stack", {"keep_fraction": keep_fraction,
                               "n_used": n_keep, "n_total": len(frames)})
    return LuckyResult(image=img, n_frames_total=len(frames),
                       n_frames_used=n_keep, sharpness=scores)
