"""Export the Terrain Diffusion 90 m model bundle using TD's Python environment."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch

import torch
from terrain_diffusion.inference.world_pipeline import WorldPipeline
from terrain_diffusion.models.edm_unet import EDMUnet2D
from terrain_diffusion.models.mp_layers import MPConv, normalize
from terrain_diffusion.onnx.export import export_model
from terrain_diffusion.scheduler.dpmsolver import EDMDPMSolverMultistepScheduler

_CONV2D = torch.nn.functional.conv2d
_SNR = [0.2, 0.2, 1.0, 0.2, 1.0]
_STAGES = {"coarse": (64, 11, 6), "base": (64, 5, 5), "decoder": (512, 5, 1)}


def _static_padding(value, weight, bias=None, stride=1, padding=0, dilation=1, groups=1):
    if isinstance(padding, (tuple, list)) and len(padding) == 1:
        padding = padding[0]
    if isinstance(padding, torch.Tensor):
        padding = int(padding)
    return _CONV2D(value, weight, bias, stride, padding, dilation, groups)


def _normalized_conv(layer, value, gain=1):
    """Use weights normalized once before export rather than normalizing on the GPU."""
    weight = layer.weight * (gain / layer.weight[0].numel() ** 0.5)
    if weight.ndim == 2:
        return torch.nn.functional.linear(value, weight)
    padding = 0 if layer.no_padding else int(weight.shape[-1]) // 2
    return torch.nn.functional.conv2d(value, weight, padding=padding, groups=layer.groups)


def _schedule() -> dict:
    scheduler = EDMDPMSolverMultistepScheduler(sigma_min=0.002, sigma_max=80, sigma_data=0.5)
    scheduler.set_timesteps(20)
    if scheduler.config.solver_order != 2 or scheduler.config.algorithm_type != "dpmsolver++":
        raise ValueError("The browser requires the second-order DPM-Solver++ schedule")
    basis = torch.eye(3, dtype=torch.float32)
    steps = []
    for index, (time, sigma) in enumerate(zip(scheduler.timesteps, scheduler.sigmas, strict=False)):
        if index:
            scheduler.model_outputs[-1] = basis[2]
        next_sample = scheduler.step(basis[1], time, basis[0]).prev_sample
        steps.append(
            {
                "scale": scheduler.precondition_inputs(torch.ones(1), sigma).item(),
                "noise": scheduler.trigflow_precondition_noise(sigma).item(),
                "next": next_sample.tolist(),
                "history": scheduler.model_outputs[-1].tolist()[:2],
            }
        )
    return {
        "sigmaMax": scheduler.sigmas[0].item(),
        "sigmaData": scheduler.config.sigma_data,
        "labels": torch.log(torch.tan(torch.atan(torch.tensor(_SNR))) / 8).tolist(),
        "steps": steps,
    }


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def export_bundle(snapshot: Path, output: Path, device: str) -> None:
    world = WorldPipeline(**WorldPipeline.load_config(str(snapshot)))
    if (
        world.native_resolution != 90
        or world.latent_compression != 8
        or world.kwargs["coarse_pooling"] != 1
    ):
        raise ValueError("The browser requires the Terrain Diffusion 90 m model")
    output.mkdir(parents=True, exist_ok=False)
    models = {}
    for stage, (size, inputs, outputs) in _STAGES.items():
        model = (
            EDMUnet2D.from_pretrained(str(snapshot), subfolder=f"{stage}_model").eval().to(device)
        )
        if model.config.in_channels != inputs or model.config.out_channels != outputs:
            raise ValueError(f"Unexpected channel count in {stage}")
        with torch.no_grad():
            for layer in model.modules():
                if isinstance(layer, MPConv):
                    layer.weight.copy_(normalize(layer.weight))
        model_path = output / f"{stage}.onnx"
        with (
            patch.object(MPConv, "forward", _normalized_conv),
            patch.object(torch.nn.functional, "conv2d", _static_padding),
        ):
            export_model(model, model_path, device=device, image_size=size)
        models[stage] = {"sha256": _digest(model_path), "bytes": model_path.stat().st_size}
        del model
    manifest = {
        "version": 1,
        "snapshot": snapshot.name,
        **_schedule(),
        "snr": _SNR,
        "means": world.kwargs["coarse_means"],
        "stds": world.kwargs["coarse_stds"],
        "residualMean": world.kwargs["residual_mean"],
        "residualStd": world.kwargs["residual_std"],
        "models": models,
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"VITE_TD_MODEL_SHA256={_digest(manifest_path)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path, help="Local, versioned TD 90 m checkpoint directory")
    parser.add_argument("output", type=Path, help="New model-bundle directory under exports/")
    parser.add_argument("--device", default="cpu", choices=("cpu", "cuda"))
    args = parser.parse_args()
    for variable in ("PYTORCH_CUDA_ALLOC_CONF", "PYTORCH_ALLOC_CONF"):
        os.environ.pop(variable, None)
    torch.set_num_threads(2)
    export_bundle(args.snapshot, args.output, args.device)


if __name__ == "__main__":
    main()
