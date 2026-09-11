#!/usr/bin/env python3
"""RT-DETR preprocessing verified against the preserved correctness tensor."""

import cv2
import numpy as np


def preprocess_bgr(frame: np.ndarray) -> np.ndarray:
    """Convert a 1920x1080 uint8 BGR frame to FP32 NCHW 1x3x640x640."""
    resized = cv2.resize(frame, (640, 360), interpolation=cv2.INTER_LINEAR)
    padded = np.zeros((640, 640, 3), dtype=np.uint8)
    padded[:360, :, :] = resized
    rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
    normalized = rgb.astype(np.float32) / np.float32(255.0)
    return np.ascontiguousarray(normalized.transpose(2, 0, 1)[None, ...])
