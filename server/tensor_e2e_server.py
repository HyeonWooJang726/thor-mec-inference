#!/usr/bin/env python3

import argparse
import ctypes
import hashlib
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np
import tensorrt as trt


INPUT_SHAPE = (1, 3, 640, 640)
LOGITS_SHAPE = (1, 300, 7)
BOXES_SHAPE = (1, 300, 4)

FLOAT32_BYTES = 4
INPUT_BYTES = int(np.prod(INPUT_SHAPE)) * FLOAT32_BYTES
LOGITS_BYTES = int(np.prod(LOGITS_SHAPE)) * FLOAT32_BYTES
BOXES_BYTES = int(np.prod(BOXES_SHAPE)) * FLOAT32_BYTES
OUTPUT_BYTES = LOGITS_BYTES + BOXES_BYTES


class TensorRTRunner:
    def __init__(self, engine_path):
        self.logger = trt.Logger(trt.Logger.ERROR)
        trt.init_libnvinfer_plugins(self.logger, "")

        with open(engine_path, "rb") as handle, trt.Runtime(self.logger) as runtime:
            self.engine = runtime.deserialize_cuda_engine(handle.read())

        if self.engine is None:
            raise RuntimeError("TensorRT engine deserialization failed")

        self.context = self.engine.create_execution_context()
        if self.context is None:
            raise RuntimeError("TensorRT execution context creation failed")

        self.cuda = ctypes.CDLL("libcudart.so")

        self.cuda.cudaMalloc.argtypes = [
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_size_t,
        ]
        self.cuda.cudaMalloc.restype = ctypes.c_int

        self.cuda.cudaFree.argtypes = [ctypes.c_void_p]
        self.cuda.cudaFree.restype = ctypes.c_int

        self.cuda.cudaMemcpy.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_int,
        ]
        self.cuda.cudaMemcpy.restype = ctypes.c_int

        self.cuda.cudaDeviceSynchronize.argtypes = []
        self.cuda.cudaDeviceSynchronize.restype = ctypes.c_int

        names = [
            self.engine.get_tensor_name(i)
            for i in range(self.engine.num_io_tensors)
        ]

        expected_names = ["inputs", "pred_logits", "pred_boxes"]
        if names != expected_names:
            raise RuntimeError(f"unexpected TensorRT tensor names: {names}")

        self.shapes = {
            name: tuple(self.engine.get_tensor_shape(name))
            for name in names
        }

        expected_shapes = {
            "inputs": INPUT_SHAPE,
            "pred_logits": LOGITS_SHAPE,
            "pred_boxes": BOXES_SHAPE,
        }

        if self.shapes != expected_shapes:
            raise RuntimeError(
                f"unexpected TensorRT tensor shapes: {self.shapes}"
            )

        for name in names:
            dtype = np.dtype(
                trt.nptype(self.engine.get_tensor_dtype(name))
            )
            if dtype != np.dtype(np.float32):
                raise RuntimeError(
                    f"unexpected TensorRT dtype for {name}: {dtype}"
                )

        self.host_outputs = {
            "pred_logits": np.empty(LOGITS_SHAPE, dtype=np.float32),
            "pred_boxes": np.empty(BOXES_SHAPE, dtype=np.float32),
        }

        self.device = {}

        try:
            for name, shape in expected_shapes.items():
                size = int(np.prod(shape)) * FLOAT32_BYTES
                pointer = ctypes.c_void_p()

                self._check(
                    self.cuda.cudaMalloc(
                        ctypes.byref(pointer),
                        size,
                    ),
                    f"cudaMalloc({name})",
                )

                self.device[name] = (pointer, size)

                if not self.context.set_tensor_address(
                    name,
                    pointer.value,
                ):
                    raise RuntimeError(
                        f"set_tensor_address failed: {name}"
                    )

        except Exception:
            self.close()
            raise

    @staticmethod
    def _check(status, operation):
        if status != 0:
            raise RuntimeError(
                f"{operation} failed with CUDA error {status}"
            )

    def infer(self, tensor):
        if tensor.shape != INPUT_SHAPE:
            raise RuntimeError(
                f"unexpected input shape: {tensor.shape}"
            )

        if tensor.dtype != np.float32:
            raise RuntimeError(
                f"unexpected input dtype: {tensor.dtype}"
            )

        if not tensor.flags.c_contiguous:
            raise RuntimeError("input tensor is not C-contiguous")

        pointer, size = self.device["inputs"]

        self._check(
            self.cuda.cudaMemcpy(
                pointer,
                ctypes.c_void_p(tensor.ctypes.data),
                size,
                1,
            ),
            "input cudaMemcpy",
        )

        if not self.context.execute_async_v3(stream_handle=0):
            raise RuntimeError("TensorRT execute_async_v3 failed")

        self._check(
            self.cuda.cudaDeviceSynchronize(),
            "cudaDeviceSynchronize",
        )

        for name, output in self.host_outputs.items():
            pointer, size = self.device[name]

            self._check(
                self.cuda.cudaMemcpy(
                    ctypes.c_void_p(output.ctypes.data),
                    pointer,
                    size,
                    2,
                ),
                f"{name} cudaMemcpy",
            )

        return self.host_outputs

    def close(self):
        for pointer, _size in getattr(self, "device", {}).values():
            self.cuda.cudaFree(pointer)

        if hasattr(self, "device"):
            self.device.clear()


class SmokeHTTPServer(HTTPServer):
    allow_reuse_address = True


class InferenceHandler(BaseHTTPRequestHandler):
    server_version = "ThorMECTensorSmoke/1.0"

    def do_POST(self):
        if self.path != "/infer":
            self.send_error(404)
            return

        request_id = self.headers.get("X-Request-ID", "unknown")

        try:
            content_length = int(
                self.headers.get("Content-Length", "-1")
            )
        except ValueError:
            self.send_error(400, "invalid Content-Length")
            return

        if content_length != INPUT_BYTES:
            self.send_error(
                400,
                f"expected {INPUT_BYTES} input bytes, "
                f"got {content_length}",
            )
            return

        body = self.rfile.read(content_length)

        if len(body) != INPUT_BYTES:
            self.send_error(
                400,
                f"incomplete request body: {len(body)} bytes",
            )
            return

        input_sha256 = hashlib.sha256(body).hexdigest()

        tensor = np.frombuffer(
            body,
            dtype=np.float32,
        ).reshape(INPUT_SHAPE)

        if not np.isfinite(tensor).all():
            self.send_error(
                400,
                "input tensor contains non-finite values",
            )
            return

        tensor = np.ascontiguousarray(tensor)

        inference_start_ns = time.monotonic_ns()

        try:
            outputs = self.server.runner.infer(tensor)
        except Exception as exc:
            print(
                f"ERROR request_id={request_id}: {exc}",
                flush=True,
            )
            self.send_error(500, str(exc))
            return

        inference_end_ns = time.monotonic_ns()

        logits = outputs["pred_logits"]
        boxes = outputs["pred_boxes"]

        if not np.isfinite(logits).all():
            self.send_error(
                500,
                "pred_logits contains non-finite values",
            )
            return

        if not np.isfinite(boxes).all():
            self.send_error(
                500,
                "pred_boxes contains non-finite values",
            )
            return

        response_body = (
            logits.tobytes(order="C")
            + boxes.tobytes(order="C")
        )

        if len(response_body) != OUTPUT_BYTES:
            self.send_error(
                500,
                f"unexpected output size: {len(response_body)}",
            )
            return

        output_sha256 = hashlib.sha256(
            response_body
        ).hexdigest()

        self.send_response(200)
        self.send_header(
            "Content-Type",
            "application/octet-stream",
        )
        self.send_header(
            "Content-Length",
            str(len(response_body)),
        )
        self.send_header(
            "X-Request-ID",
            request_id,
        )
        self.send_header(
            "X-Input-SHA256",
            input_sha256,
        )
        self.send_header(
            "X-Output-SHA256",
            output_sha256,
        )
        self.end_headers()
        self.wfile.write(response_body)

        print(
            f"PASS request_id={request_id} "
            f"input_sha256={input_sha256} "
            f"input_bytes={INPUT_BYTES} "
            f"output_sha256={output_sha256} "
            f"output_bytes={OUTPUT_BYTES} "
            f"inference_ns="
            f"{inference_end_ns - inference_start_ns}",
            flush=True,
        )

    def log_message(self, fmt, *args):
        print(
            f"CLIENT {self.client_address[0]} "
            f"{fmt % args}",
            flush=True,
        )


def main():
    parser = argparse.ArgumentParser(
        description="Single-request tensor E2E integration smoke server."
    )
    parser.add_argument("--engine", required=True)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    runner = TensorRTRunner(args.engine)

    server = SmokeHTTPServer(
        (args.host, args.port),
        InferenceHandler,
    )
    server.runner = runner

    print(
        f"READY host={args.host} port={args.port}",
        flush=True,
    )
    print(
        f"INPUT shape={INPUT_SHAPE} "
        f"dtype=float32 bytes={INPUT_BYTES}",
        flush=True,
    )
    print(
        f"OUTPUT pred_logits={LOGITS_SHAPE} "
        f"pred_boxes={BOXES_SHAPE} "
        f"bytes={OUTPUT_BYTES}",
        flush=True,
    )
    print(
        "MODE single-process C=1 integration smoke; "
        "timing is diagnostic only",
        flush=True,
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("SHUTDOWN", flush=True)
    finally:
        server.server_close()
        runner.close()


if __name__ == "__main__":
    main()
