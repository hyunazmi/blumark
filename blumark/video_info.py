from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import cv2
    import numpy as np

DEFAULT_FPS = 30.0


@dataclass(frozen=True)
class VideoInfo:
    path: str
    width: int
    height: int
    fps: float
    frame_count: int

    @property
    def duration_ms(self) -> int:
        return int(self.frame_count / self.fps * 1000)


def open_video(path: str) -> tuple[cv2.VideoCapture, np.ndarray, VideoInfo]:
    import cv2

    capture = cv2.VideoCapture(path)
    try:
        if not capture.isOpened():
            raise ValueError(f"Could not open video:\n{path}")
        ok, frame = capture.read()
        if not ok:
            raise ValueError("Could not read the first frame of the video.")
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        if not math.isfinite(fps) or fps <= 0:
            fps = DEFAULT_FPS
        frame_count = max(int(capture.get(cv2.CAP_PROP_FRAME_COUNT)), 1)
    except Exception:
        capture.release()
        raise
    height, width = frame.shape[:2]
    return capture, frame, VideoInfo(path, width, height, fps, frame_count)


def probe(path: str) -> VideoInfo:
    capture, _, info = open_video(path)
    capture.release()
    return info
