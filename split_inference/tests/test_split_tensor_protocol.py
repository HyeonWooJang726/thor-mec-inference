"""CPU-only binary framing tests; no models, datasets, GPUs or network services."""
from dataclasses import replace
import socket
import time
import unittest
from unittest.mock import patch
from split_inference.src.common import split_tensor_protocol as p


class FragmentSocket:
    def __init__(self, data=b'', chunk=7, timeout=.2, fail=False):
        self.data, self.position, self.chunk = data, 0, chunk
        self.timeout, self.fail, self.sent = timeout, fail, b''
        self.options = []
    def gettimeout(self):
        return self.timeout
    def settimeout(self, value):
        self.timeout = value
    def setsockopt(self, *value):
        self.options.append(value)
    def recv(self, size):
        if self.fail:
            raise TimeoutError('simulated socket timeout')
        chunk = self.data[self.position:self.position + min(size, self.chunk)]
        self.position += len(chunk)
        return chunk
    def sendall(self, data):
        self.sent += data


class BinaryProtocolTests(unittest.TestCase):
    def request(self, verify=False):
        return p.tensor_header(p.Kind.INFER, 123, 8, verify)
    def mutate(self, index, value):
        fields = list(p.HEADER.unpack(p.encode_header(self.request())))
        fields[index] = value
        return p.HEADER.pack(*fields)
    def test_header_round_trip_and_network_order(self):
        h = self.request()
        data = p.encode_header(h)
        self.assertEqual(len(data), 48)
        self.assertEqual(data[:6], b'ESFP\x02\x03')
        self.assertEqual(data[6:14], (123).to_bytes(8, 'big'))
        self.assertEqual(p.decode_header(data), h)
    def test_all_split_shapes_from_manifest(self):
        for point in range(9):
            h = p.tensor_header(p.Kind.INFER, point + 1, point)
            self.assertEqual(p.decode_header(p.encode_header(h)), h)
            self.assertEqual(h.shape, p.SHAPES[point])
        self.assertEqual(p.SHAPES[8], (1,1280))
        self.assertEqual(p.tensor_header(p.Kind.INFER, 1, 8).payload_bytes, 5120)
        self.assertEqual(p.tensor_header(p.Kind.RESULT, 1, 8).payload_bytes, 4000)
    def test_fragmented_persistent_frames(self):
        payload = b'\x01\x02\x03\x04' * 1280
        h = self.request()
        sock = FragmentSocket(p.encode(h, payload) + p.encode(replace(h, request_id=124), payload), chunk=3)
        for rid in (123,124):
            frame = p.recv_frame(sock)
            self.assertEqual(frame.header.request_id, rid)
            self.assertEqual(frame.payload, payload)
        self.assertEqual(sock.gettimeout(), .2)
    def test_premature_eof(self):
        complete = p.encode(self.request(), bytes(5120))
        for length in (1, 47, 48, len(complete)-1):
            with self.subTest(length=length), self.assertRaises(EOFError):
                p.recv_frame(FragmentSocket(complete[:length]))
    def test_clean_eof_distinct(self):
        with self.assertRaises(p.PeerClosed):
            p.recv_frame(FragmentSocket())
    def test_invalid_magic_version(self):
        for index,value in ((0,b'BAD!'),(1,3)):
            with self.subTest(index=index), self.assertRaises(p.ProtocolError):
                p.recv_frame(FragmentSocket(self.mutate(index,value)))
    def test_invalid_split_and_p9_network_rejected(self):
        for point in (-1,9,10):
            with self.subTest(point=point), self.assertRaises(p.ProtocolError):
                p.decode_header(self.mutate(4,point))
        with self.assertRaises(p.ProtocolError):
            p.tensor_header(p.Kind.INFER, 1, 9)
    def test_invalid_dtype(self):
        with self.assertRaises(p.ProtocolError):
            p.decode_header(self.mutate(5,2))
    def test_invalid_shape_and_dimension_padding(self):
        for index,value in ((11,1279),(6,5),(12,12)):
            with self.subTest(index=index), self.assertRaises(p.ProtocolError):
                p.decode_header(self.mutate(index,value))
    def test_payload_length_mismatch(self):
        with self.assertRaises(p.ProtocolError):
            p.encode(self.request(), bytes(5119))
        with self.assertRaises(p.ProtocolError):
            p.decode_header(self.mutate(14,5119))
    def test_oversized_payload_rejected_before_body(self):
        sock = FragmentSocket(self.mutate(14,p.MAX_PAYLOAD+1) + b'body')
        with self.assertRaises(p.ProtocolError):
            p.recv_frame(sock)
        self.assertEqual(sock.position, p.HEADER.size)
        with self.assertRaises(p.ProtocolError):
            p.decode_header(p.encode_header(self.request()), max_payload=4096)
    def test_request_id_response_matching(self):
        frame = p.Frame(p.tensor_header(p.Kind.RESULT,123,8),bytes(4000))
        p.match_response(frame,p.Kind.RESULT,123,8)
        for rid,point in ((124,8),(123,7)):
            with self.assertRaises(p.ProtocolError):
                p.match_response(frame,p.Kind.RESULT,rid,point)
        with self.assertRaises(p.ProtocolError):
            p.match_response(p.Frame(p.control_header(p.Kind.ERROR,123),b''),p.Kind.RESULT,123,8)
    def test_normal_close_bye(self):
        sock = FragmentSocket(p.encode(p.control_header(p.Kind.BYE,42)))
        p.close_session(sock,42)
        frame = p.recv_frame(FragmentSocket(sock.sent))
        self.assertEqual(frame.header,p.control_header(p.Kind.CLOSE,42))
        self.assertEqual(frame.payload,b'')
    def test_optional_digest_and_corruption(self):
        encoded = p.encode(self.request(True),bytes(5120))
        self.assertEqual(len(p.recv_frame(FragmentSocket(encoded)).digest),32)
        with self.assertRaises(p.ProtocolError):
            p.recv_frame(FragmentSocket(encoded[:-1]+bytes([encoded[-1]^1])))
    def test_default_path_performs_no_payload_hash(self):
        with patch.object(p.hashlib,'sha256',side_effect=AssertionError('unexpected hash')):
            frame = p.recv_frame(FragmentSocket(p.encode(self.request(),bytes(5120))))
            self.assertEqual(frame.digest,b'')
    def test_timeout_and_deadline(self):
        sock = FragmentSocket(fail=True)
        with self.assertRaises(TimeoutError):
            p.recv_frame(sock)
        self.assertEqual(sock.timeout,.2)
        with self.assertRaises(TimeoutError):
            p.recv_exact(FragmentSocket(),1,time.monotonic()-1)
        with self.assertRaises(p.ProtocolError):
            p.recv_frame(FragmentSocket(timeout=None))
    def test_control_identity_fixed_length(self):
        h = p.control_header(p.Kind.HELLO)
        self.assertEqual(p.recv_frame(FragmentSocket(p.encode(h,b'a'*96))).payload,b'a'*96)
        with self.assertRaises(p.ProtocolError):
            p.encode(h,b'a'*95)
    def test_nodelay_and_invalid_reserved_status(self):
        sock = FragmentSocket()
        p.configure_socket(sock,1)
        self.assertIn((socket.IPPROTO_TCP,socket.TCP_NODELAY,1),sock.options)
        for index,value in ((2,255),(7,2),(8,1),(9,1)):
            with self.subTest(index=index),self.assertRaises(p.ProtocolError):
                p.decode_header(self.mutate(index,value))


if __name__ == '__main__':
    unittest.main()
