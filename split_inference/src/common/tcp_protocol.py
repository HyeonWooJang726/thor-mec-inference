"""Bounded JSON framing and little-endian FP32 payloads; no network pickle."""

import hashlib
import json
import math
from pathlib import Path
import re
import struct
import time

VERSION = 1
MAX_HEADER_BYTES = 16384
DEFAULT_MAX_PAYLOAD = 8 * 1024 * 1024
MANIFEST_PATH = Path(__file__).resolve().parents[2] / 'manifests/efficientnet_v2_s_p0_p9.json'
MANIFEST = json.loads(MANIFEST_PATH.read_text())
SHAPES = {p['index']: p['expected_shape'] for p in MANIFEST['points']}
IDENTITY_KEYS = ('state_dict_sha256', 'manifest_sha256', 'partitions_sha256')


class ProtocolError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ProtocolError(message)


def definition_identity():
    module = Path(__file__).with_name('efficientnet_v2_s_partitions.py')
    return {'manifest_sha256': hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest(),
            'partitions_sha256': hashlib.sha256(module.read_bytes()).hexdigest()}


def check_identity(header, expected):
    for key in IDENTITY_KEYS:
        require(header.get(key) == expected[key], f'{key} mismatch; inference prohibited')


def header(kind, request_id, partition=-1, **extra):
    shape = SHAPES.get(partition, []) if kind == 'infer' else [1, 1000] if kind == 'result' else []
    return {'protocol_version': VERSION, 'kind': kind, 'request_id': request_id,
            'partition_point': partition, 'dtype': 'float32', 'byte_order': 'little',
            'shape': shape, 'payload_bytes': math.prod(shape) * 4 if shape else 0, **extra}


def validate(h, max_payload=DEFAULT_MAX_PAYLOAD):
    require(type(h) is dict, 'header must be an object')
    require(type(h.get('protocol_version')) is int and h['protocol_version'] == VERSION, 'protocol version')
    require(type(h.get('request_id')) is str and 0 < len(h['request_id']) <= 128, 'request ID')
    require(h.get('dtype') == 'float32' and h.get('byte_order') == 'little', 'dtype/byte order')
    kind, point = h.get('kind'), h.get('partition_point')
    require(type(kind) is str and kind in {'hello', 'ready', 'infer', 'result', 'timings', 'error'}, 'message kind')
    require(type(point) is int, 'partition type')
    if kind in {'infer', 'result', 'timings'}:
        require(0 <= point <= 8, 'network partition must be P0-P8; P9 is local-only')
    else:
        require(point == -1, 'control partition must be -1')
    expected = SHAPES[point] if kind == 'infer' else [1, 1000] if kind == 'result' else []
    shape = h.get('shape')
    require(type(shape) is list and all(type(n) is int for n in shape) and shape == expected, 'activation shape')
    size = h.get('payload_bytes')
    require(type(size) is int and 0 <= size <= max_payload, 'payload limit/type')
    require(size == (math.prod(expected) * 4 if expected else 0), 'payload size/shape mismatch')
    if kind in {'hello', 'ready', 'infer', 'result', 'timings'}:
        for key in IDENTITY_KEYS:
            require(type(h.get(key)) is str and re.fullmatch('[0-9a-f]{64}', h[key]) is not None, key)
    if kind == 'infer':
        require(h.get('phase') in ('warmup', 'measurement'), 'request phase')


def _unique_object(pairs):
    result = {}
    for k, v in pairs:
        require(k not in result, 'duplicate JSON key')
        result[k] = v
    return result


def _bad_constant(value):
    raise ProtocolError('nonfinite JSON constant: ' + value)


def encode(h, payload=b'', max_payload=DEFAULT_MAX_PAYLOAD):
    validate(h, max_payload)
    require(len(payload) == h['payload_bytes'], 'actual payload length mismatch')
    data = json.dumps(h, separators=(',', ':'), allow_nan=False).encode('utf-8')
    require(0 < len(data) <= MAX_HEADER_BYTES, 'header length limit')
    return struct.pack('!I', len(data)) + data + payload


def send_frame(sock, h, payload=b'', max_payload=DEFAULT_MAX_PAYLOAD):
    data = encode(h, payload, max_payload)
    start = time.monotonic_ns()
    sock.sendall(data)
    return (time.monotonic_ns() - start) / 1e6


def recv_frame(sock, max_payload=DEFAULT_MAX_PAYLOAD):
    """Return header, payload, active receive ms (idle wait for first byte excluded).

    A finite socket timeout bounds first-byte wait and the remaining entire frame.
    Header schema and byte limits are checked BEFORE reading/allocating payload.
    """
    timeout = sock.gettimeout()
    require(timeout is not None and timeout > 0, 'finite positive socket timeout required')
    first = sock.recv(1)
    if not first:
        raise EOFError('peer closed before frame')
    start = time.monotonic_ns()
    deadline = time.monotonic() + timeout

    def exact(n):
        result = bytearray()
        while len(result) < n:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('frame deadline exceeded')
            sock.settimeout(remaining)
            chunk = sock.recv(n - len(result))
            if not chunk:
                raise EOFError('truncated frame')
            result.extend(chunk)
        return bytes(result)

    try:
        length = struct.unpack('!I', first + exact(3))[0]
        require(0 < length <= MAX_HEADER_BYTES, 'header length limit')
        try:
            h = json.loads(exact(length), object_pairs_hook=_unique_object, parse_constant=_bad_constant)
        except (UnicodeError, ValueError, RecursionError) as exc:
            raise ProtocolError('invalid JSON header: ' + str(exc)) from exc
        validate(h, max_payload)
        payload = exact(h['payload_bytes'])
        return h, payload, (time.monotonic_ns() - start) / 1e6
    finally:
        sock.settimeout(timeout)
