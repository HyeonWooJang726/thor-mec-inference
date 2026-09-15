"""Binary v2 FP32 tensor frames. Header integers are big endian; tensors are LE."""
from dataclasses import dataclass
from enum import IntEnum
import hashlib
import json
import math
from pathlib import Path
import socket
import struct
import time

MAGIC = b'ESFP'
VERSION = 2
HEADER = struct.Struct('!4sBBQbBBBHI4IQ')  # 48 bytes; four padded dimensions
MAX_PAYLOAD = 8 * 1024 * 1024
FP32_LE = 1
SHA256_FLAG = 1
MANIFEST_PATH = Path(__file__).resolve().parents[2] / 'manifests/efficientnet_v2_s_p0_p9.json'
POINTS = json.loads(MANIFEST_PATH.read_text())['points']
SHAPES = {p['index']: tuple(p['expected_shape']) for p in POINTS}
LOGITS_SHAPE = SHAPES[9]


class Kind(IntEnum):
    HELLO = 1
    READY = 2
    INFER = 3
    RESULT = 4
    CLOSE = 5
    BYE = 6
    ERROR = 7


class ProtocolError(ValueError):
    pass


class PeerClosed(EOFError):
    """Orderly EOF at a frame boundary (not a truncated frame)."""


def require(condition, message):
    if not condition:
        raise ProtocolError(message)


@dataclass(frozen=True)
class Header:
    kind: Kind
    request_id: int
    point: int = -1
    dtype: int = 0
    shape: tuple = ()
    payload_bytes: int = 0
    status: int = 0
    flags: int = 0


@dataclass(frozen=True)
class Frame:
    header: Header
    payload: bytes
    digest: bytes = b''


def validate(h, max_payload=MAX_PAYLOAD):
    require(type(max_payload) is int and 0 < max_payload <= MAX_PAYLOAD, 'maximum payload bound')
    require(h.kind in set(Kind), 'message type')
    require(type(h.request_id) is int and 0 <= h.request_id < 2**64, 'request_id range')
    require(type(h.payload_bytes) is int and 0 <= h.payload_bytes <= max_payload, 'payload bound')
    require(h.flags in (0, SHA256_FLAG), 'unsupported flags')
    if h.kind in (Kind.INFER, Kind.RESULT):
        require(type(h.point) is int and 0 <= h.point <= 8, 'offload requires P0-P8; P9 local-only')
        expected = SHAPES[h.point] if h.kind == Kind.INFER else LOGITS_SHAPE
        require(h.dtype == FP32_LE and h.shape == expected, 'FP32 dtype/shape mismatch')
        require(h.payload_bytes == math.prod(expected) * 4, 'payload size/shape mismatch')
        require(h.status == 0, 'tensor response status must be success')
    else:
        require(h.point == -1 and h.dtype == 0 and h.shape == () and h.flags == 0, 'control schema')
        require(h.payload_bytes == (96 if h.kind in (Kind.HELLO, Kind.READY) else 0), 'control payload size')
        require((h.kind == Kind.ERROR and h.status == 1) or (h.kind != Kind.ERROR and h.status == 0), 'status code')


def tensor_header(kind, request_id, point, verify_payload=False):
    require(kind in (Kind.INFER, Kind.RESULT), 'tensor message type')
    require(type(point) is int and 0 <= point <= 8, 'network P9 forbidden')
    shape = SHAPES[point] if kind == Kind.INFER else LOGITS_SHAPE
    return Header(kind, request_id, point, FP32_LE, shape, math.prod(shape) * 4,
                  flags=SHA256_FLAG if verify_payload else 0)


def control_header(kind, request_id=0):
    return Header(kind, request_id, payload_bytes=96 if kind in (Kind.HELLO, Kind.READY) else 0,
                  status=1 if kind == Kind.ERROR else 0)


def encode_header(h, max_payload=MAX_PAYLOAD):
    validate(h, max_payload)
    dims = h.shape + (0,) * (4 - len(h.shape))
    return HEADER.pack(MAGIC, VERSION, int(h.kind), h.request_id, h.point, h.dtype,
                       len(h.shape), h.flags, 0, h.status, *dims, h.payload_bytes)


def decode_header(data, max_payload=MAX_PAYLOAD):
    require(len(data) == HEADER.size, 'header length')
    magic, version, kind, rid, point, dtype, ndim, flags, reserved, status, *tail = HEADER.unpack(data)
    require(magic == MAGIC and version == VERSION, 'magic/version mismatch')
    require(reserved == 0 and ndim <= 4, 'reserved/dimension count')
    dims, size = tail[:4], tail[4]
    require(all(x == 0 for x in dims[ndim:]), 'unused dimensions must be zero')
    try:
        kind = Kind(kind)
    except ValueError as exc:
        raise ProtocolError('unknown message type') from exc
    h = Header(kind, rid, point, dtype, tuple(dims[:ndim]), size, status, flags)
    validate(h, max_payload)
    return h


def encode(h, payload=b'', max_payload=MAX_PAYLOAD):
    header = encode_header(h, max_payload)
    require(len(payload) == h.payload_bytes, 'actual payload length mismatch')
    # Optional smoke integrity only; zero per-request hashing when flags == 0.
    digest = hashlib.sha256(payload).digest() if h.flags & SHA256_FLAG else b''
    return header + payload + digest


def recv_exact(sock, size, deadline, clean_eof=False):
    result = bytearray()
    while len(result) < size:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('frame deadline exceeded')
        sock.settimeout(remaining)
        chunk = sock.recv(size - len(result))
        if not chunk:
            if clean_eof and not result:
                raise PeerClosed('peer closed at frame boundary')
            raise EOFError(f'premature EOF: expected {size}, received {len(result)} bytes')
        result.extend(chunk)
    return bytes(result)


def recv_frame(sock, max_payload=MAX_PAYLOAD):
    timeout = sock.gettimeout()
    require(timeout is not None and math.isfinite(timeout) and timeout > 0, 'finite socket timeout required')
    deadline = time.monotonic() + timeout
    try:
        h = decode_header(recv_exact(sock, HEADER.size, deadline, clean_eof=True), max_payload)
        payload = recv_exact(sock, h.payload_bytes, deadline)
        digest = recv_exact(sock, 32, deadline) if h.flags & SHA256_FLAG else b''
        if digest:
            require(hashlib.sha256(payload).digest() == digest, 'payload SHA-256 mismatch')
        return Frame(h, payload, digest)
    finally:
        sock.settimeout(timeout)


def send_frame(sock, h, payload=b'', max_payload=MAX_PAYLOAD):
    wire = encode(h, payload, max_payload)
    sock.sendall(wire)
    return len(wire)


def match_response(frame, kind, request_id, point=-1):
    h = frame.header
    require(h.kind == kind and h.status == 0, 'unexpected response/error status')
    require(h.request_id == request_id and h.point == point, 'response request_id/split mismatch')


def configure_socket(sock, timeout):
    require(math.isfinite(timeout) and timeout > 0, 'finite positive timeout')
    sock.settimeout(timeout)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)


def close_session(sock, request_id, max_payload=MAX_PAYLOAD):
    send_frame(sock, control_header(Kind.CLOSE, request_id), max_payload=max_payload)
    reply = recv_frame(sock, max_payload)
    match_response(reply, Kind.BYE, request_id)
