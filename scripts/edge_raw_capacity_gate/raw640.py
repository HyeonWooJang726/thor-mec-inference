"""Lossless RAW640 wire semantics; no inference or system configuration changes."""
import cv2
import numpy as np

SHAPE = (360, 640, 3)
PAYLOAD_BYTES = 691200


def remaining_preprocess(raw):
    if len(raw) != PAYLOAD_BYTES:
        raise ValueError('RAW640 byte count mismatch')
    bgr = np.frombuffer(raw, dtype=np.uint8).reshape(SHAPE)
    padded = np.zeros((640, 640, 3), dtype=np.uint8)
    padded[:360] = bgr
    rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
    normalized = rgb.astype(np.float32) / np.float32(255.0)
    return np.ascontiguousarray(normalized.transpose(2, 0, 1)[None])


def serialize(frame):
    return cv2.resize(frame, (640, 360), interpolation=cv2.INTER_LINEAR).tobytes(order='C')
