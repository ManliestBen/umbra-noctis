"""Lucky-imaging (planetary/lunar) stacking, verified against a synthetic
video: mostly Gaussian-blurred frames of one static scene, plus a handful
of sharp ones the sharpness scorer must find and keep."""

import cv2
import numpy as np

from umbra_noctis.planetary.lucky import lucky_stack

SIZE = 200


def _make_video(path, n_frames=20, n_sharp=5, blur_ksize=15):
    """Write an mp4v video of one static scene: the last ``n_sharp`` frames
    are the crisp original, every earlier frame is heavily Gaussian-blurred
    (same scene, same position — no motion, so alignment is a no-op and the
    test isolates sharpness scoring)."""
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, 10.0, (SIZE, SIZE))
    assert writer.isOpened(), "cv2.VideoWriter failed to open — codec unavailable"

    rng = np.random.default_rng(0)
    base = np.zeros((SIZE, SIZE, 3), dtype=np.uint8)
    cv2.circle(base, (SIZE // 2, SIZE // 2), SIZE // 3, (200, 200, 200), -1)
    for _ in range(40):  # textured dots inside the disc give blur something to erase
        x, y = rng.integers(SIZE // 4, 3 * SIZE // 4, size=2)
        cv2.circle(base, (int(x), int(y)), 3, (30, 30, 30), -1)

    for i in range(n_frames):
        sharp = i >= n_frames - n_sharp
        frame = base.copy() if sharp else cv2.GaussianBlur(base, (blur_ksize, blur_ksize), 0)
        writer.write(frame)
    writer.release()


def _laplacian_var(bgr_or_rgb_uint8_gray: np.ndarray) -> float:
    return float(cv2.Laplacian(bgr_or_rgb_uint8_gray.astype(np.float32) / 255.0, cv2.CV_32F).var())


def test_lucky_stack_picks_sharp_frames(tmp_path):
    video = tmp_path / "video.mp4"
    _make_video(video, n_frames=20, n_sharp=5)

    result = lucky_stack(video, keep_fraction=0.25)  # 25% of 20 = 5
    assert result.n_frames_total == 20
    assert result.n_frames_used == 5

    cap = cv2.VideoCapture(str(video))
    ok, blurred_frame = cap.read()  # frame 0 is one of the blurred ones
    cap.release()
    assert ok
    blurred_sharpness = _laplacian_var(cv2.cvtColor(blurred_frame, cv2.COLOR_BGR2GRAY))

    stacked_u8 = (np.clip(result.image.data, 0, 1) * 255).astype(np.uint8)
    stacked_gray = cv2.cvtColor(stacked_u8, cv2.COLOR_RGB2GRAY)
    stacked_sharpness = _laplacian_var(stacked_gray)

    assert stacked_sharpness > blurred_sharpness, (
        f"stack of the sharp frames ({stacked_sharpness:.4f}) should be sharper "
        f"than a single blurred frame ({blurred_sharpness:.4f})")


def test_lucky_stack_truncation_and_release(tmp_path):
    video = tmp_path / "video.mp4"
    _make_video(video, n_frames=20, n_sharp=5)

    result = lucky_stack(video, max_frames=10)
    assert result.n_frames_total == 10
