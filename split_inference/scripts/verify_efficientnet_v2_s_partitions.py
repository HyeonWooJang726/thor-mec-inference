"""CUDA correctness only: one model, one seeded input, every official split."""

import inspect
import json
import sys

import torch
import torchvision
from torchvision.models.efficientnet import FusedMBConv, MBConv

from split_inference.src.common.efficientnet_v2_s_partitions import (
    EfficientNetV2SPartitions,
)


def check_tensor(tensor, expected_shape):
    assert list(tensor.shape) == expected_shape, (list(tensor.shape), expected_shape)
    assert tensor.dtype == torch.float32, tensor.dtype
    assert tensor.is_cuda, tensor.device
    assert torch.isfinite(tensor).all().item(), "Nonfinite tensor"


def main():
    torch.manual_seed(0)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = False
    print(json.dumps({
        "python": sys.version, "torch": torch.__version__,
        "torchvision": torchvision.__version__, "cuda": torch.version.cuda,
        "cudnn": torch.backends.cudnn.version(), "seed": 0,
        "tf32": False, "cudnn_benchmark": False,
        "rtol": 1e-5, "atol": 1e-6, "relative_error_floor": 1e-8,
    }), flush=True)
    assert torch.cuda.is_available(), "CUDA unavailable"
    print("GPU:", torch.cuda.get_device_name(0), flush=True)
    model = torchvision.models.efficientnet_v2_s(weights=None).float().cuda().eval()
    print("MODEL_STRUCTURE", model, sep="\n", flush=True)
    print("MODEL_SOURCE", inspect.getfile(type(model)), flush=True)
    for method in (type(model)._forward_impl, FusedMBConv.forward, MBConv.forward):
        print(inspect.getsource(method), flush=True)
    partitions = EfficientNetV2SPartitions(model)
    assert partitions.model is model
    assert {id(p) for p in partitions.parameters()} == {id(p) for p in model.parameters()}
    assert all(not module.training for module in model.modules()), "eval required"
    for index, stage in enumerate(model.features):
        print("FEATURE_STAGE", index, type(stage).__name__, len(stage), flush=True)
    print("DROPOUT", model.classifier[0], "training=", model.classifier[0].training, flush=True)

    # Observe the ORIGINAL forward, including the functional flatten boundary.
    # Clones preserve observations across any subsequent in-place activations.
    observed = {}
    order = []
    handles = []

    def record_module(name, point=None):
        def hook(module, args, output):
            order.append(name)
            if point is not None:
                observed[point] = output.detach().clone()
        return hook

    def record_classifier_input(module, args):
        observed[8] = args[0].detach().clone()

    for index, stage in enumerate(model.features):
        handles.append(stage.register_forward_hook(
            record_module(f"features.{index}", index + 1 if index < 7 else None)
        ))
    handles.append(model.avgpool.register_forward_hook(record_module("avgpool")))
    handles.append(model.classifier.register_forward_pre_hook(record_classifier_input))
    handles.append(model.classifier.register_forward_hook(record_module("classifier", 9)))

    with torch.inference_mode():
        x = torch.randn((1, 3, 384, 384), device="cuda", dtype=torch.float32)
        observed[0] = x.clone()
        try:
            reference = model(x)
            torch.cuda.synchronize()
        finally:
            for handle in handles:
                handle.remove()
        assert order == [f"features.{i}" for i in range(8)] + ["avgpool", "classifier"], order
        check_tensor(reference, [1, 1000])
        print("REFERENCE", list(reference.shape), "max_abs=", reference.abs().max().item(), flush=True)
        for boundary in partitions.manifest["points"]:
            point = boundary["index"]
            check_tensor(observed[point], boundary["expected_shape"])
            activation = partitions.prefix(x, point)
            check_tensor(activation, boundary["expected_shape"])
            torch.testing.assert_close(activation, observed[point], rtol=1e-5, atol=1e-6)
            metadata = {
                "point": boundary["id"], "before": boundary["before"],
                "after": boundary["after"], "shape": list(activation.shape),
                "dtype": str(activation.dtype), "numel": activation.numel(),
                "bytes": activation.numel() * activation.element_size(),
            }
            output = partitions.suffix(activation, point)
            torch.cuda.synchronize()
            check_tensor(output, [1, 1000])
            diff = (output - reference).abs()
            metadata.update({
                "output_shape": list(output.shape),
                "max_abs_diff": diff.max().item(),
                "max_rel_diff": (diff / reference.abs().clamp_min(1e-8)).max().item(),
            })
            print("PARTITION", json.dumps(metadata), flush=True)
            torch.testing.assert_close(output, reference, rtol=1e-5, atol=1e-6)
    print("ALL_P0_P9_PASS", flush=True)


if __name__ == "__main__":
    main()
