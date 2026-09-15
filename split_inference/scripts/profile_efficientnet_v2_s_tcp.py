"""Single-flight device-side inference latency client; formal or loopback pilot."""
import os
os.environ['TORCH_ALLOW_TF32_CUBLAS_OVERRIDE'] = '0'
os.environ['NVIDIA_TF32_OVERRIDE'] = '0'
import argparse
from pathlib import Path

from split_inference.src.common import split_tensor_protocol as wire
from split_inference.src.common.efficientnet_v2_s_profile_runtime import execute, client_session


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--zip', type=Path, required=True)
    parser.add_argument('--host', default='192.168.0.6')
    parser.add_argument('--port', type=int, default=5000)
    parser.add_argument('--timeout', type=float, default=3600)
    parser.add_argument('--max-payload-bytes', type=int, default=wire.MAX_PAYLOAD)
    parser.add_argument('--verify-payload', action='store_true', required=True)
    parser.add_argument('--profile-mode', choices=['formal', 'pilot'], default='formal')
    parser.add_argument('--profile-run-id', required=True)
    parser.add_argument('--output', type=Path, required=True, help='New, nonexistent output directory')
    args = parser.parse_args()
    wire.require(0 < args.port <= 65535, 'port range')
    execute(args, 'client', client_session)


if __name__ == '__main__':
    main()
