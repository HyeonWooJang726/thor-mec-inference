"""Official ImageNet runtime; shared grouping/timer/materialization are reused."""
import csv
import hashlib
import io
import json
from pathlib import Path
import zipfile

import torch
from PIL import Image
from torchvision.models import EfficientNet_V2_S_Weights, efficientnet_v2_s
from split_inference.scripts.profile_efficientnet_v2_s_imagenet import canonical_hash, file_hash
from .efficientnet_v2_s_runtime import (
    ROOT, EfficientNetV2SPartitions, GpuTimer, from_bytes, to_bytes, snapshot,
)
from .split_tensor_protocol import MANIFEST_PATH, SHAPES, require

EXPECTED_CANONICAL = 'dcac15dc687d43926f62a7942918dc73d11372abbb612352336b4d5840ca4710'
EXPECTED_CHECKPOINT = 'dd5fe13b1d60ec15317ccc8ca158186e134d3366c3dde9cb9a4e301f2dc66c74'
DOC = ROOT / 'split_inference/docs/imagenet_profile/20260915T112015Z'
SELECTION_HASH = 'f198e9fd3da063f0f4ae66dff1d6c76fdb66c7875abae88d462b37f96d338bc2'
EVIDENCE_HASH = '5706419efb22bd224d7c1b4bac5cceb22d479c3ec1336cc4e9cbb467301bf794'


def write_json(path, data):
    with Path(path).open('x') as f:
        json.dump(data, f, indent=2, allow_nan=False)
        f.write('\n')


def load_official(cache):
    """Load exactly once from an existing official hub cache; never download."""
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = True
    require(torch.cuda.is_available(), 'CUDA required')
    torch.hub.set_dir(str(cache))
    weights = EfficientNet_V2_S_Weights.IMAGENET1K_V1
    checkpoint = Path(cache) / 'checkpoints' / weights.url.rsplit('/', 1)[1]
    require(checkpoint.is_file(), f'Official cached checkpoint required: {checkpoint}')
    require(file_hash(checkpoint) == EXPECTED_CHECKPOINT, 'checkpoint hash mismatch')
    model = efficientnet_v2_s(weights=weights).float().eval()
    actual = canonical_hash(model.state_dict())
    require(actual == EXPECTED_CANONICAL, 'canonical model mismatch: inference prohibited')
    require(all(not module.training for module in model.modules()), 'eval required')
    definition = Path(__file__).with_name('efficientnet_v2_s_partitions.py')
    hashes = [actual, file_hash(MANIFEST_PATH), file_hash(definition)]
    identity = b''.join(bytes.fromhex(h) for h in hashes)
    metadata = {'architecture': 'efficientnet_v2_s', 'weight_enum': str(weights),
                'checkpoint': str(checkpoint), 'checkpoint_sha256': EXPECTED_CHECKPOINT,
                'canonical_sha256': actual, 'manifest_sha256': hashes[1], 'partitions_sha256': hashes[2],
                'transform': repr(weights.transforms()), 'precision': 'FP32', 'eval': True,
                'inference_mode': True, 'autocast': False, 'tf32': False, 'cudnn_benchmark': True}
    return model.cuda(), identity, metadata


def selected_input(zip_path, sample_id):
    require(type(sample_id) is int and 0 <= sample_id < 300, 'sample ID 0..299 required')
    selection = DOC / 'selected_imagenet_members.txt'
    evidence = DOC / 'selected_image_evidence.csv'
    require(file_hash(selection) == SELECTION_HASH and file_hash(evidence) == EVIDENCE_HASH, 'selection/evidence hash')
    members = selection.read_text().splitlines()
    with evidence.open() as f:
        records = list(csv.DictReader(f))
    require(len(members) == len(set(members)) == len(records) == 300, 'selection size/duplicates')
    require([r['member'] for r in records] == members, 'evidence order')
    member, record = members[sample_id], records[sample_id]
    with zipfile.ZipFile(zip_path) as archive:
        require(archive.namelist().count(member) == 1, 'missing/duplicate ZIP member')
        payload = archive.read(member)
    require(hashlib.sha256(payload).hexdigest() == record['jpeg_sha256'], 'JPEG evidence mismatch: ' + member)
    with Image.open(io.BytesIO(payload)) as image:
        image.load()
        tensor = EfficientNet_V2_S_Weights.IMAGENET1K_V1.transforms()(image.convert('RGB')).unsqueeze(0).contiguous()
    require(tuple(tensor.shape) == SHAPES[0] and tensor.dtype == torch.float32, 'input shape/dtype')
    require(hashlib.sha256(tensor.numpy().tobytes()).hexdigest() == record['preprocessed_fp32_sha256'], 'FP32 evidence mismatch: ' + member)
    return tensor, member, record


def check_tensor(tensor, point):
    require(tuple(tensor.shape) == SHAPES[point] and tensor.dtype == torch.float32, 'activation shape/dtype')
    require(torch.isfinite(tensor).all().item(), 'nonfinite tensor')
