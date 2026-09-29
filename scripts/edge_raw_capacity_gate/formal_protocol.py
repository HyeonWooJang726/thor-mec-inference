"""RAW640 v1 framing. No sockets opened and no GPU access on import."""
import hashlib
import json
import platform
import struct
import sys
from pathlib import Path

import numpy as np

MAGIC = b'R640'
HEADER = struct.Struct('!4sBQII')
HELLO, READY, REQUEST, RESPONSE, END, FINAL = range(1, 7)
RAW_BYTES = 691200
OUTPUT_BYTES = (300 * 7 + 300 * 4) * 4
PORT = 5000
ORDER = [(1, 8), (1, 16), (1, 24), (1, 40),
         (2, 24), (2, 40), (2, 8), (2, 16),
         (3, 40), (3, 8), (3, 16), (3, 24)]
PROFILER_SHA = '355ec6f2ee6cdc2867755e11cdb499bed71f8ef2a315b858f36c17827c38bd46'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1048576), b''):
            h.update(b)
    return h.hexdigest()


def save(path, value):
    with Path(path).open('x') as f:
        json.dump(value, f, indent=2, allow_nan=False)
        f.write('\n')


def provenance():
    here = Path(__file__).parent
    return dict(python=sys.version, executable=sys.executable, numpy=np.__version__,
                hostname=platform.node(), platform=platform.platform(),
                source_sha256={p.name: sha(p) for p in sorted(here.glob('formal_*.py'))},
                profiler_sha256=sha(here / 'profile_edge_concurrency.py'))


def load_runtime_helpers():
    if sha(Path(__file__).with_name('profile_edge_concurrency.py')) != PROFILER_SHA:
        raise RuntimeError('frozen NumPy profiler dependency hash mismatch')
    import profile_edge_concurrency
    return profile_edge_concurrency


def recv_exact(sock, n):
    data = bytearray(n)
    view = memoryview(data)
    offset = 0
    while offset < n:
        block = sock.recv(n - offset)
        if not block:
            raise EOFError(f'truncated frame: wanted {n}, received {offset}')
        view[offset:offset + len(block)] = block
        offset += len(block)
    return bytes(data)


def send_message(sock, kind, request_id=0, metadata=None, payload=b''):
    meta = json.dumps(metadata or {}, separators=(',', ':'), allow_nan=False).encode()
    validate_sizes(kind, len(meta), len(payload))
    sock.sendall(HEADER.pack(MAGIC, kind, request_id, len(meta), len(payload)))
    sock.sendall(meta)
    if payload:
        sock.sendall(payload)


def validate_sizes(kind, meta_size, payload_size):
    if kind not in range(1, 7) or not 2 <= meta_size <= 65536:
        raise ValueError('invalid message kind or metadata length')
    expected = RAW_BYTES if kind == REQUEST else OUTPUT_BYTES if kind == RESPONSE else 0
    if payload_size != expected:
        raise ValueError(f'invalid payload length {payload_size} for kind {kind}')


def recv_message(sock):
    magic, kind, rid, ml, pl = HEADER.unpack(recv_exact(sock, HEADER.size))
    if magic != MAGIC:
        raise ValueError('protocol magic/version mismatch')
    validate_sizes(kind, ml, pl)
    meta = json.loads(recv_exact(sock, ml))
    if not isinstance(meta, dict):
        raise ValueError('metadata must be an object')
    return kind, rid, meta, recv_exact(sock, pl)


def encode_outputs(outputs):
    chunks = []
    for name, shape in [('pred_logits', (1, 300, 7)), ('pred_boxes', (1, 300, 4))]:
        value = outputs[name]
        if value.shape != shape or value.dtype != np.float32 or not np.isfinite(value).all():
            raise ValueError('invalid TensorRT output: ' + name)
        chunks.append(np.asarray(value, dtype='<f4').tobytes(order='C'))
    return b''.join(chunks)


def decode_outputs(payload):
    if len(payload) != OUTPUT_BYTES:
        raise ValueError('invalid response output length')
    data = np.frombuffer(payload, dtype='<f4')
    if not np.isfinite(data).all():
        raise ValueError('nonfinite response')
    return dict(pred_logits=data[:2100].reshape(1, 300, 7),
                pred_boxes=data[2100:].reshape(1, 300, 4))


def arrivals(start, rate, seconds):
    # Integer timeline, independent of sender/receiver execution or completion.
    return [start + i * 1_000_000_000 // rate for i in range(rate * seconds)]
