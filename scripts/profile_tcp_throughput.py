#!/usr/bin/env python3

import argparse
import csv
import socket
import statistics
import time
from pathlib import Path


READY = b"R"
ACK = b"A"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Repeated TCP throughput characterization with application ACK."
    )

    parser.add_argument(
        "--mode",
        choices=("send", "receive"),
        required=True,
    )
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument(
        "--total-bytes",
        type=int,
        default=256 * 1024 * 1024,
    )
    parser.add_argument(
        "--chunk-bytes",
        type=int,
        default=1024 * 1024,
    )
    parser.add_argument(
        "--interval-s",
        type=float,
        default=2.0,
    )
    parser.add_argument("--csv", required=True)

    args = parser.parse_args()

    if args.runs < 1:
        parser.error("--runs must be >= 1")
    if args.total_bytes < 1:
        parser.error("--total-bytes must be >= 1")
    if args.chunk_bytes < 1:
        parser.error("--chunk-bytes must be >= 1")
    if args.interval_s < 0:
        parser.error("--interval-s must be >= 0")

    return args


def write_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fields = [
        "run",
        "role",
        "bytes",
        "elapsed_s",
        "throughput_mbps",
        "throughput_mib_s",
        "peer",
    ]

    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def print_summary(role, rows):
    values = [row["throughput_mbps"] for row in rows]

    print()
    print(f"===== {role.upper()} SUMMARY =====")
    print(f"runs: {len(values)}")
    print(f"mean_Mbps: {statistics.mean(values):.6f}")
    print(f"median_Mbps: {statistics.median(values):.6f}")
    print(f"min_Mbps: {min(values):.6f}")
    print(f"max_Mbps: {max(values):.6f}")

    if len(values) > 1:
        print(
            f"stdev_Mbps: "
            f"{statistics.stdev(values):.6f}"
        )


def receive(args):
    rows = []

    with socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM,
    ) as listener:
        listener.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_REUSEADDR,
            1,
        )
        listener.bind((args.host, args.port))
        listener.listen(1)

        print(
            f"READY receiver={args.host}:{args.port} "
            f"runs={args.runs} "
            f"bytes_per_run={args.total_bytes}"
        )

        for run in range(1, args.runs + 1):
            conn, addr = listener.accept()

            with conn:
                conn.settimeout(60)

                print(
                    f"RUN {run}/{args.runs} "
                    f"client={addr[0]}:{addr[1]}"
                )

                conn.sendall(READY)

                received = 0
                first_data_ns = None
                last_data_ns = None

                while received < args.total_bytes:
                    data = conn.recv(
                        min(
                            args.chunk_bytes,
                            args.total_bytes - received,
                        )
                    )

                    if not data:
                        break

                    now_ns = time.monotonic_ns()

                    if first_data_ns is None:
                        first_data_ns = now_ns

                    received += len(data)
                    last_data_ns = now_ns

                if received != args.total_bytes:
                    raise RuntimeError(
                        f"run {run}: incomplete transfer: "
                        f"{received} != {args.total_bytes}"
                    )

                extra = conn.recv(1)

                if extra:
                    raise RuntimeError(
                        f"run {run}: unexpected extra payload"
                    )

                if first_data_ns is None or last_data_ns is None:
                    raise RuntimeError(
                        f"run {run}: no payload received"
                    )

                elapsed_s = (
                    last_data_ns - first_data_ns
                ) / 1e9

                mbps = (
                    received * 8
                    / elapsed_s
                    / 1e6
                )

                mib_s = (
                    received
                    / elapsed_s
                    / 1024
                    / 1024
                )

                conn.sendall(ACK)

                row = {
                    "run": run,
                    "role": "receiver",
                    "bytes": received,
                    "elapsed_s": elapsed_s,
                    "throughput_mbps": mbps,
                    "throughput_mib_s": mib_s,
                    "peer": addr[0],
                }

                rows.append(row)

                print(
                    f"RESULT run={run} PASS "
                    f"bytes={received} "
                    f"elapsed_s={elapsed_s:.6f} "
                    f"throughput_Mbps={mbps:.6f} "
                    f"throughput_MiB_s={mib_s:.6f}"
                )

    write_csv(args.csv, rows)
    print_summary("receiver", rows)
    print(f"csv: {args.csv}")


def send(args):
    rows = []

    chunk = b"\0" * args.chunk_bytes

    for run in range(1, args.runs + 1):
        with socket.create_connection(
            (args.host, args.port),
            timeout=10,
        ) as conn:
            conn.settimeout(60)

            ready = conn.recv(1)

            if ready != READY:
                raise RuntimeError(
                    f"run {run}: invalid READY byte: {ready!r}"
                )

            sent = 0
            start_ns = time.monotonic_ns()

            while sent < args.total_bytes:
                size = min(
                    args.chunk_bytes,
                    args.total_bytes - sent,
                )
                conn.sendall(chunk[:size])
                sent += size

            conn.shutdown(socket.SHUT_WR)

            ack = conn.recv(1)

            end_ns = time.monotonic_ns()

            if ack != ACK:
                raise RuntimeError(
                    f"run {run}: invalid ACK byte: {ack!r}"
                )

            elapsed_s = (
                end_ns - start_ns
            ) / 1e9

            mbps = (
                sent * 8
                / elapsed_s
                / 1e6
            )

            mib_s = (
                sent
                / elapsed_s
                / 1024
                / 1024
            )

            row = {
                "run": run,
                "role": "sender_ack_completion",
                "bytes": sent,
                "elapsed_s": elapsed_s,
                "throughput_mbps": mbps,
                "throughput_mib_s": mib_s,
                "peer": args.host,
            }

            rows.append(row)

            print(
                f"RESULT run={run} PASS "
                f"bytes={sent} "
                f"elapsed_s={elapsed_s:.6f} "
                f"throughput_Mbps={mbps:.6f} "
                f"throughput_MiB_s={mib_s:.6f}"
            )

        if run < args.runs and args.interval_s > 0:
            time.sleep(args.interval_s)

    write_csv(args.csv, rows)
    print_summary("sender_ack_completion", rows)
    print(f"csv: {args.csv}")


def main():
    args = parse_args()

    if args.mode == "receive":
        receive(args)
    else:
        send(args)


if __name__ == "__main__":
    main()
