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


def _gray(frame: np.ndarray) -> np.ndarray:
    """One grayscale formula everywhere: OpenCV's BGR2GRAY (Rec. 601
    luma), used identically for sharpness scoring, subject cropping, and
    alignment so all three agree on what "brightness" means."""
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0


def lucky_stack(video_path: str | Path, keep_fraction: float = 0.25,
                max_frames: int = 2000, crop_to_subject: bool = True,
                progress=None) -> LuckyResult:
    """Stack the sharpest frames of a planetary/lunar video (MP4/AVI).

    ``keep_fraction=0.25`` keeps the best 25% — a good default for average
    seeing; drop to 0.1 in poor seeing, raise to 0.5 in excellent seeing.

    Two passes over the video, so at most one decoded frame is resident at
    a time (a 2000-frame 1080p capture would otherwise need ~50 GB): pass 1
    opens the capture, scores every frame's sharpness, and releases the
    capture (even on error); pass 2 re-opens the file, decodes sequentially,
    and accumulates only the chosen frames into a running sum, again
    releasing the capture in a ``finally``.

    Reference-frame change from the single-pass version: the alignment
    reference is now the FIRST chosen frame encountered in playback order,
    not necessarily the single sharpest one. Finding the true sharpest
    frame during a sequential pass would mean either buffering every
    chosen frame until it turns up (defeating the point of streaming) or
    decoding the file a third time — in practice, any frame in the top
    ``keep_fraction`` is a perfectly good alignment target.
    """
    # ------------------------------------------------------------ pass 1
    scores: list[float] = []
    n_total = 0
    truncated = False
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"Cannot open video {video_path}")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if n_total >= max_frames:
                truncated = True  # this frame exists but is past the cap
                break
            scores.append(_sharpness(_gray(frame)))
            n_total += 1
            if progress and n_total % 50 == 0:
                progress("read", n_total, max_frames)
    finally:
        cap.release()
    if n_total == 0:
        raise ValueError("Video contains no readable frames")
    if truncated and progress:
        progress("truncated", n_total, max_frames)

    order = np.argsort(scores)[::-1]
    n_keep = max(1, int(n_total * keep_fraction))
    chosen = set(int(i) for i in order[:n_keep])

    # ------------------------------------------------------------ pass 2
    cap2 = cv2.VideoCapture(str(video_path))
    if not cap2.isOpened():
        raise ValueError(f"Cannot re-open video {video_path} for the alignment pass")
    acc = None
    weight = 0.0
    ref_gray_crop = None
    x0 = y0 = x1 = y1 = 0
    n_processed = 0
    try:
        for idx in range(n_total):
            ok, frame = cap2.read()
            if not ok:
                break
            if idx not in chosen:
                continue
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
            gray = _gray(frame)

            if acc is None:
                # First chosen frame encountered: becomes the alignment
                # reference and defines the subject crop (see docstring).
                if crop_to_subject:
                    ys, xs = np.nonzero(gray > gray.max() * 0.15)
                    if len(xs) > 100:
                        pad = 60
                        x0, x1 = max(0, xs.min() - pad), min(rgb.shape[1], xs.max() + pad)
                        y0, y1 = max(0, ys.min() - pad), min(rgb.shape[0], ys.max() + pad)
                    else:
                        x0, y0, x1, y1 = 0, 0, rgb.shape[1], rgb.shape[0]
                else:
                    x0, y0, x1, y1 = 0, 0, rgb.shape[1], rgb.shape[0]
                ref_gray_crop = gray[y0:y1, x0:x1].astype(np.float64)
                acc = np.zeros_like(rgb)

            g = gray[y0:y1, x0:x1]
            try:
                (dx, dy), _ = cv2.phaseCorrelate(ref_gray_crop, g.astype(np.float64))
            except cv2.error:
                dx = dy = 0.0
            m = np.float32([[1, 0, -dx], [0, 1, -dy]])
            aligned = cv2.warpAffine(rgb, m, (rgb.shape[1], rgb.shape[0]),
                                     flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
            acc += aligned
            weight += 1.0
            n_processed += 1
            if progress:
                progress("stack", n_processed, n_keep)
    finally:
        cap2.release()

    if acc is None:
        raise ValueError("Could not re-read the chosen frames during the alignment pass")

    stacked = (acc / weight)[y0:y1, x0:x1]
    img = AstroImage(data=np.clip(stacked, 0, 1).astype(np.float32), linear=False)
    img.meta["source_video"] = str(video_path)
    img.record("lucky_stack", {"keep_fraction": keep_fraction,
                               "n_used": n_keep, "n_total": n_total})
    return LuckyResult(image=img, n_frames_total=n_total,
                       n_frames_used=n_keep, sharpness=scores)
