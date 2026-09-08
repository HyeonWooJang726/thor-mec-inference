#!/usr/bin/env python3

import argparse
import hashlib
import time
import urllib.request

import numpy as np


INPUT_SHAPE = (1, 3, 640, 640)
LOGITS_SHAPE = (1, 300, 7)
BOXES_SHAPE = (1, 300, 4)

FLOAT32_BYTES = 4
INPUT_BYTES = int(np.prod(INPUT_SHAPE)) * FLOAT32_BYTES
LOGITS_BYTES = int(np.prod(LOGITS_SHAPE)) * FLOAT32_BYTES
BOXES_BYTES = int(np.prod(BOXES_SHAPE)) * FLOAT32_BYTES
OUTPUT_BYTES = LOGITS_BYTES + BOXES_BYTES


def main():
    parser = argparse.ArgumentParser(
        description="Single-request tensor E2E integration smoke client."
    )
    parser.add_argument("--url", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument(
        "--request-id",
        default="tensor-smoke-0001",
    )
    args = parser.parse_args()

    with open(args.input, "rb") as handle:
        request_body = handle.read()

    input_sha256 = hashlib.sha256(request_body).hexdigest()

    if len(request_body) != INPUT_BYTES:
        raise RuntimeError(
            f"input size mismatch: "
            f"{len(request_body)} != {INPUT_BYTES}"
        )

    if input_sha256 != args.expected_sha256:
        raise RuntimeError(
            f"input SHA256 mismatch: "
            f"{input_sha256} != {args.expected_sha256}"
        )

    request = urllib.request.Request(
        args.url,
        data=request_body,
        method="POST",
        headers={
            "Content-Type": "application/octet-stream",
            "X-Request-ID": args.request_id,
        },
    )

    start_ns = time.monotonic_ns()

    with urllib.request.urlopen(
        request,
        timeout=30,
    ) as response:
        status = response.status
        returned_request_id = response.headers.get("X-Request-ID")
        server_input_sha256 = response.headers.get("X-Input-SHA256")
        server_output_sha256 = response.headers.get("X-Output-SHA256")
        response_body = response.read()

    end_ns = time.monotonic_ns()

    if status != 200:
        raise RuntimeError(
            f"unexpected HTTP status: {status}"
        )

    if returned_request_id != args.request_id:
        raise RuntimeError(
            f"request ID mismatch: {returned_request_id}"
        )

    if server_input_sha256 != input_sha256:
        raise RuntimeError(
            "server-reported input SHA256 mismatch"
        )

    if len(response_body) != OUTPUT_BYTES:
        raise RuntimeError(
            f"output size mismatch: "
            f"{len(response_body)} != {OUTPUT_BYTES}"
        )

    client_output_sha256 = hashlib.sha256(
        response_body
    ).hexdigest()

    if server_output_sha256 != client_output_sha256:
        raise RuntimeError(
            "output SHA256 mismatch"
        )

    logits = np.frombuffer(
        response_body[:LOGITS_BYTES],
        dtype=np.float32,
    ).reshape(LOGITS_SHAPE)

    boxes = np.frombuffer(
        response_body[LOGITS_BYTES:],
        dtype=np.float32,
    ).reshape(BOXES_SHAPE)

    if not np.isfinite(logits).all():
        raise RuntimeError(
            "pred_logits contains non-finite values"
        )

    if not np.isfinite(boxes).all():
        raise RuntimeError(
            "pred_boxes contains non-finite values"
        )

    print("RESULT: PASS")
    print(f"request_id: {args.request_id}")
    print(f"HTTP status: {status}")
    print(f"input SHA256: {input_sha256}")
    print(f"input bytes: {len(request_body)}")
    print(
        f"pred_logits: shape={logits.shape} "
        f"dtype={logits.dtype}"
    )
    print(
        f"pred_boxes: shape={boxes.shape} "
        f"dtype={boxes.dtype}"
    )
    print(f"output SHA256: {client_output_sha256}")
    print(f"output bytes: {len(response_body)}")
    print(
        f"client monotonic E2E ns: "
        f"{end_ns - start_ns}"
    )
    print(
        "NOTE: E2E timing is an integration-smoke "
        "diagnostic, not a formal performance result."
    )


if __name__ == "__main__":
    main()
