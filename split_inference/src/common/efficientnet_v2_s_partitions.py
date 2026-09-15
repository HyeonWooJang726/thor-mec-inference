"""Project-defined P0–P9 execution using one existing TorchVision model."""

import json
from pathlib import Path

import torch
from torch import nn
from torchvision.models.efficientnet import FusedMBConv, MBConv
from torchvision.ops.misc import Conv2dNormActivation


MANIFEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "manifests/efficientnet_v2_s_p0_p9.json"
)


class EfficientNetV2SPartitions(nn.Module):
    """Prefix includes G1…Gp; suffix includes G(p+1)…G9.

    The supplied model is retained by reference, with no copies or new weights.
    Callers control device, dtype, eval and inference_mode on that same model.
    P0 prefix and P9 suffix are identity operations.
    """

    def __init__(self, model: nn.Module):
        super().__init__()
        self.model = model
        self.manifest = json.loads(MANIFEST_PATH.read_text())
        self._check_structure()

    def _check_structure(self):
        m = self.model
        if len(m.features) != 8:
            raise ValueError("Official groups require exactly features[0:8]")
        for index in (0, 7):
            if not isinstance(m.features[index], Conv2dNormActivation):
                raise ValueError(f"features[{index}] must be Conv2dNormActivation")
        for index in range(1, 7):
            stage = m.features[index]
            block_type = FusedMBConv if index <= 3 else MBConv
            if not isinstance(stage, nn.Sequential) or not len(stage):
                raise ValueError(f"features[{index}] must be a nonempty stage")
            if not all(isinstance(block, block_type) for block in stage):
                raise ValueError(f"features[{index}] must contain {block_type.__name__}")
        if not isinstance(m.avgpool, nn.AdaptiveAvgPool2d):
            raise ValueError("Expected model.avgpool to be AdaptiveAvgPool2d")
        if m.avgpool.output_size not in (1, (1, 1)):
            raise ValueError("Expected global average pooling")
        if not isinstance(m.classifier, nn.Sequential) or len(m.classifier) != 2:
            raise ValueError("Expected classifier = Dropout -> Linear")
        if not isinstance(m.classifier[0], nn.Dropout):
            raise ValueError("Expected classifier[0] to be Dropout")
        linear = m.classifier[1]
        if not isinstance(linear, nn.Linear) or (linear.in_features, linear.out_features) != (1280, 1000):
            raise ValueError("Expected classifier[1] to be Linear(1280, 1000)")
        groups = self.manifest["groups"]
        if [g["id"] for g in groups] != [f"G{i}" for i in range(1, 10)]:
            raise ValueError("Manifest must define ordered G1–G9")
        for group in groups:
            for operation in group["operations"]:
                if "module" in operation:
                    m.get_submodule(operation["module"])
                elif operation != {"op": "flatten", "start_dim": 1}:
                    raise ValueError(f"Unsupported manifest operation: {operation}")

    @staticmethod
    def _check_point(point: int):
        if type(point) is not int or not 0 <= point <= 9:
            raise ValueError("point must be an integer in [0, 9]")

    def _run(self, x: torch.Tensor, start: int, stop: int) -> torch.Tensor:
        for group in self.manifest["groups"][start:stop]:
            for operation in group["operations"]:
                if "module" in operation:
                    x = self.model.get_submodule(operation["module"])(x)
                else:
                    x = torch.flatten(x, operation["start_dim"])
        return x

    def prefix(self, x: torch.Tensor, point: int) -> torch.Tensor:
        self._check_point(point)
        return self._run(x, 0, point)

    def suffix(self, activation: torch.Tensor, point: int) -> torch.Tensor:
        self._check_point(point)
        return self._run(activation, point, 9)

    def forward(self, x: torch.Tensor, point: int) -> torch.Tensor:
        return self.suffix(self.prefix(x, point), point)
