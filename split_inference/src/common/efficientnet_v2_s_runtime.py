"""Shared model loading, identity, and CUDA helpers for the two endpoints."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

import numpy as np
import torch
import torchvision

from .efficientnet_v2_s_partitions import EfficientNetV2SPartitions
from .tcp_protocol import definition_identity, require

ROOT = Path(__file__).resolve().parents[3]


def state_hash(model):
    """Same parameter+buffer hash as the Edge suffix profile, canonical little endian."""
    digest = hashlib.sha256()
    for name, value in sorted(model.state_dict().items()):
        digest.update(json.dumps([name, str(value.dtype), list(value.shape)], separators=(',', ':')).encode() + b'\n')
        array = value.detach().cpu().contiguous().numpy()
        digest.update(array.astype(array.dtype.newbyteorder('<'), copy=False).tobytes(order='C'))
    return digest.hexdigest()


def load_model(path):
    require(torch.cuda.is_available(), 'CUDA required')
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = True
    model = torchvision.models.efficientnet_v2_s(weights=None).float().eval()
    # Only a local, explicitly supplied state_dict file is loaded; never network pickle.
    state = torch.load(Path(path), map_location='cpu', weights_only=True)
    require(isinstance(state, dict), 'file must contain a bare state_dict')
    expected = model.state_dict()
    require(set(state) == set(expected), 'state_dict keys mismatch')
    for key, value in state.items():
        require(isinstance(value, torch.Tensor) and value.dtype == expected[key].dtype
                and value.shape == expected[key].shape, f'invalid state tensor {key}')
        require(torch.isfinite(value).all().item(), f'nonfinite state tensor {key}')
    model.load_state_dict(state, strict=True)
    identity = {'state_dict_sha256': state_hash(model), **definition_identity()}
    return model.cuda().eval(), identity


class GpuTimer:
    def __init__(self):
        self.start = torch.cuda.Event(enable_timing=True)
        self.end = torch.cuda.Event(enable_timing=True)
        self.start.record()
        self.end.record()
        self.end.synchronize()

    def run(self, operation):
        self.start.record()
        result = operation()
        self.end.record()
        self.end.synchronize()
        duration = self.start.elapsed_time(self.end)
        require(np.isfinite(duration) and duration >= 0, 'invalid CUDA Event time')
        return result, duration


def to_bytes(tensor):
    return tensor.detach().to('cpu', dtype=torch.float32).contiguous().numpy().astype('<f4', copy=False).tobytes()


def from_bytes(payload, shape):
    array = np.frombuffer(payload, dtype='<f4').reshape(shape).astype(np.float32, copy=True)
    require(np.isfinite(array).all(), 'nonfinite tensor payload')
    return torch.from_numpy(array)


def snapshot():
    data = {'python': sys.version, 'executable': sys.executable, 'hostname': platform.node(),
            'platform': platform.platform(), 'torch': torch.__version__, 'torchvision': torchvision.__version__,
            'cuda': torch.version.cuda, 'cudnn': torch.backends.cudnn.version(),
            'gpu': torch.cuda.get_device_name(0), 'capability': list(torch.cuda.get_device_capability(0)),
            'settings': {'dtype': 'float32', 'tf32': False, 'cudnn_benchmark': True,
                         'power_clock_changes': 'none', 'clock_lock': 'unavailable; not configured by this code'},
            'cpu_clock': 'unavailable: not sampled', 'emc_clock': 'unavailable: not sampled'}
    for key, cmd in [('nvidia_smi', ['nvidia-smi', '-q']), ('git_commit', ['git', 'rev-parse', 'HEAD'])]:
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=15, cwd=ROOT)
            data[key] = {'command': cmd, 'exit_code': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr}
        except (OSError, subprocess.TimeoutExpired) as exc:
            data[key] = {'unavailable': str(exc)}
    return data


def new_output(root, prefix):
    path = Path(root) / (prefix + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ'))
    path.mkdir(parents=True, exist_ok=False)
    return path


def save_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')
