"""CPU-only protocol framing, validation, timeout and identity tests."""

import json
import socket
import struct
import threading
import unittest

from split_inference.src.common.tcp_protocol import (
    DEFAULT_MAX_PAYLOAD, MAX_HEADER_BYTES, ProtocolError, check_identity, encode,
    header, recv_frame, send_frame, validate,
)

IDENTITY = dict.fromkeys(('state_dict_sha256', 'manifest_sha256', 'partitions_sha256'), 'a' * 64)


class ProtocolTests(unittest.TestCase):
    def pair(self):
        a, b = socket.socketpair()
        a.settimeout(0.2)
        b.settimeout(0.2)
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        return a, b

    def request(self):
        return header('infer', 'test-request', 8, phase='measurement', **IDENTITY)

    def test_fragmented_and_back_to_back_frames(self):
        a, b = self.pair()
        h = self.request()
        payload = bytes(5120)
        wire = encode(h, payload) + encode(header('hello', 'next', **IDENTITY))
        errors = []

        def write():
            try:
                for offset in range(0, len(wire), 17):
                    a.sendall(wire[offset:offset + 17])
            except BaseException as exc:
                errors.append(exc)

        worker = threading.Thread(target=write)
        worker.start()
        try:
            actual, data, ms = recv_frame(b)
            self.assertEqual(actual, h)
            self.assertEqual(data, payload)
            self.assertGreaterEqual(ms, 0)
            self.assertEqual(recv_frame(b)[0]['request_id'], 'next')
        finally:
            worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertFalse(errors)

    def test_reject_invalid_schema_before_payload_read(self):
        for changes in [{'partition_point': 9}, {'partition_point': -1}, {'partition_point': True},
                        {'dtype': 'float16'}, {'byte_order': 'big'}, {'shape': [1, 1279]},
                        {'shape': [True, 1280]}, {'payload_bytes': 5119}, {'payload_bytes': -1},
                        {'payload_bytes': DEFAULT_MAX_PAYLOAD + 1}, {'payload_bytes': True},
                        {'protocol_version': 2}, {'protocol_version': True}, {'request_id': ''},
                        {'state_dict_sha256': 'bad'}, {'phase': 'unknown'}]:
            with self.subTest(changes=changes):
                a, b = self.pair()
                h = {**self.request(), **changes}
                blob = json.dumps(h).encode()
                a.sendall(struct.pack('!I', len(blob)) + blob)  # No payload supplied.
                with self.assertRaises(ProtocolError):
                    recv_frame(b)

    def test_oversized_or_empty_header(self):
        for size in (0, MAX_HEADER_BYTES + 1, 0xffffffff):
            a, b = self.pair()
            a.sendall(struct.pack('!I', size))
            with self.assertRaises(ProtocolError):
                recv_frame(b)

    def test_invalid_json(self):
        for data in (b'not-json', b'[]', b'{"a":1,"a":2}', b'{"x":NaN}', b'\xff'):
            a, b = self.pair()
            a.sendall(struct.pack('!I', len(data)) + data)
            with self.assertRaises(ProtocolError):
                recv_frame(b)

    def test_payload_size_on_send(self):
        with self.assertRaises(ProtocolError):
            encode(self.request(), bytes(5116))
        with self.assertRaises(ProtocolError):
            validate(self.request(), max_payload=4096)

    def test_truncated_frame(self):
        a, b = self.pair()
        a.sendall(encode(self.request(), bytes(5120))[:-1])
        a.shutdown(socket.SHUT_WR)
        with self.assertRaises(EOFError):
            recv_frame(b)

    def test_timeout_for_idle_and_partial_frame(self):
        for partial in (b'', b'\x00'):
            a, b = self.pair()
            b.settimeout(.02)
            if partial:
                a.sendall(partial)
            with self.assertRaises(TimeoutError):
                recv_frame(b)

    def test_identity_and_response_rules(self):
        check_identity(IDENTITY, IDENTITY)
        for key in IDENTITY:
            with self.assertRaises(ProtocolError):
                check_identity({**IDENTITY, key: 'b' * 64}, IDENTITY)
        h = header('result', 'id', 0, **IDENTITY)
        validate(h)
        self.assertEqual(h['shape'], [1, 1000])
        self.assertEqual(h['payload_bytes'], 4000)
        with self.assertRaises(ProtocolError):
            validate(header('infer', 'id', 9, phase='measurement', **IDENTITY))
        a, b = self.pair()
        send_frame(a, header('timings', 'id', 0, **IDENTITY))
        self.assertEqual(recv_frame(b)[1], b'')


if __name__ == '__main__':
    unittest.main()
