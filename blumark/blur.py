from __future__ import annotations

import cv2
import numpy as np

from .utils import Rect

MIN_SIGMA = 0.6
SIGMA_PER_STRENGTH = 0.6
DOWNSCALE_SIGMA_STEP = 4


def blur_patch(
    frame: np.ndarray, rect: Rect, strength: int = 25, feather: int = 0
) -> tuple[np.ndarray, int, int] | None:
    frame_height, frame_width = frame.shape[:2]
    x, y, width, height = rect
    left, top = max(0, int(x)), max(0, int(y))
    right, bottom = min(frame_width, int(x + width)), min(frame_height, int(y + height))
    if right - left < 2 or bottom - top < 2:
        return None

    feather = int(feather)
    sigma = max(MIN_SIGMA, strength * SIGMA_PER_STRENGTH)
    margin = int(sigma * 3) + feather

    region_left, region_top = max(0, left - margin), max(0, top - margin)
    region_right = min(frame_width, right + margin)
    region_bottom = min(frame_height, bottom + margin)
    region = frame[region_top:region_bottom, region_left:region_right].copy()
    region_height, region_width = region.shape[:2]

    factor = max(1, int(sigma // DOWNSCALE_SIGMA_STEP))
    if factor > 1:
        small = cv2.resize(
            region,
            (max(1, region_width // factor), max(1, region_height // factor)),
            interpolation=cv2.INTER_AREA,
        )
        small = cv2.GaussianBlur(small, (0, 0), sigma / factor)
        blurred = cv2.resize(small, (region_width, region_height), interpolation=cv2.INTER_LINEAR)
    else:
        blurred = cv2.GaussianBlur(region, (0, 0), sigma)

    inner_left, inner_top = left - region_left, top - region_top
    inner_right, inner_bottom = right - region_left, bottom - region_top

    if feather <= 0:
        return blurred[inner_top:inner_bottom, inner_left:inner_right], left, top

    mask = np.zeros((region_height, region_width), dtype=np.float32)
    mask[inner_top:inner_bottom, inner_left:inner_right] = 1.0
    mask = cv2.GaussianBlur(mask, (0, 0), feather / 2.0)[..., None]
    mixed = blurred.astype(np.float32) * mask + region.astype(np.float32) * (1.0 - mask)
    return (mixed + 0.5).astype(np.uint8), region_left, region_top


def apply_blur(frame: np.ndarray, rect: Rect, strength: int = 25, feather: int = 0) -> np.ndarray:
    result = blur_patch(frame, rect, strength, feather)
    if result is not None:
        patch, x, y = result
        patch_height, patch_width = patch.shape[:2]
        frame[y:y + patch_height, x:x + patch_width] = patch
    return frame
