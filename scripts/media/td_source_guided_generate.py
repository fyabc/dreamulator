"""Run bounded source-latent TD experiments in an installed upstream TD environment.

Pass --inputs, --output, --world-model and --autoencoder as absolute paths. Run from
the upstream terrain-diffusion checkout, at commit e8dcb4b, with its GPU environment.
Fine cases test AE round trips and SDEdit-inspired consistency editing. Coarse cases
test low-frequency projection between the two upstream consistency steps. These are
experimental adapters, not production modes or reproductions of DDPM samplers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import torch
from infinite_tensor import InfiniteTensor, TensorWindow
from scipy.ndimage import distance_transform_edt, gaussian_filter
from terrain_diffusion.data.laplacian_encoder import laplacian_decode, laplacian_encode
from terrain_diffusion.inference.world_pipeline import WorldPipeline, linear_weight_window
from terrain_diffusion.models.edm_autoencoder import EDMAutoencoder
from terrain_diffusion.scheduler.dpmsolver import EDMDPMSolverMultistepScheduler

RESIDUAL_STD = 1.1678
PAD = 512
SIZE = 2048
AE_HASH = "bd3d81e93fc514deb0ab8494f2212d956f42bca1e76eb547da93bd66e539ff8a"
FINE = ("earth_alps_360m", "earth_himalaya_360m", "external_350m")
COARSE = ("earth_alps_46km_upscaled", "nacrea_coarse_50km")


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path: Path, array: np.ndarray) -> None:
    if not np.isfinite(array).all():
        raise ValueError(f"Nonfinite array: {path.name}")
    np.save(path, np.asarray(array, dtype=np.float32), allow_pickle=False)


def prepare(inputs: Path, output: Path, name: str) -> tuple[dict, np.ndarray]:
    src, case = inputs / name, output / name
    case.mkdir(parents=True, exist_ok=True)
    meta = json.loads((src / "input.json").read_text(encoding="utf-8"))
    a = np.load(src / "source.meters.npy", mmap_mode="r", allow_pickle=False)
    if a.ndim != 2 or min(a.shape) < SIZE or not np.isfinite(a).all():
        raise ValueError(
            "A finite two-dimensional source of at least 2048 pixels per side is required"
        )
    cy, cx = meta.get("crop_center_fraction", [0.5, 0.5])
    y = max(0, min(a.shape[0] - SIZE, int(cy * a.shape[0] - SIZE / 2) // 256 * 256))
    x = max(0, min(a.shape[1] - SIZE, int(cx * a.shape[1] - SIZE / 2) // 256 * 256))
    hashes = {}
    for filename in (
        "source.meters.npy",
        "donor.meters.npy",
        "cosine.meters.npy",
        "cosine.frequency-delta.npy",
        "truth.meters.npy",
    ):
        if not (src / filename).exists():
            continue
        expected = meta.get("hashes", {}).get(filename)
        actual = file_hash(src / filename)
        if expected and expected != actual:
            raise ValueError(f"Input hash mismatch: {filename}")
        hashes[filename] = actual
        arr = np.load(src / filename, mmap_mode="r", allow_pickle=False)
        save(case / filename, arr[y : y + SIZE, x : x + SIZE])
    info = {k: meta[k] for k in ("pixel_km", "native_km", "preserve_wavelength_km", "source_kind")}
    info.update(
        case=name,
        crop_origin_px=[y, x],
        parent_shape=list(a.shape),
        parent_input_json_sha256=file_hash(src / "input.json"),
        parent_hashes=hashes,
        crop_center_fraction=[0.5, 0.5],
    )
    distance = distance_transform_edt(np.pad(a > 0, 1))[1:-1, 1:-1] * meta["pixel_km"]
    t = np.clip(
        np.maximum(distance - meta["pixel_km"], 0) / (meta["preserve_wavelength_km"] / 2), 0, 1
    ).astype(np.float32)
    weight = t * t * (3 - 2 * t)
    save(case / "parent-coast-weight.npy", weight[y : y + SIZE, x : x + SIZE])
    (case / "input.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    return info, np.load(case / "source.meters.npy", allow_pickle=False)


@torch.no_grad()
def encode(ae: EDMAutoencoder, source: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    padded = np.pad(source, PAD, mode="edge")
    encoded = np.sign(padded) * np.sqrt(np.abs(padded))
    residual, low = laplacian_encode(encoded, padded.shape[0] // 8, sigma=5)
    residual = residual / RESIDUAL_STD
    n = padded.shape[0]
    means = np.zeros((4, n // 8, n // 8), np.float32)
    weights = np.zeros((n // 8, n // 8), np.float32)
    weight = linear_weight_window(64, "cpu", torch.float32).numpy()
    for y in range(0, n - 511, 256):
        for x in range(0, n - 511, 256):
            inp = torch.from_numpy(residual[y : y + 512, x : x + 512])[None, None].cuda()
            mu, logvar = ae.preencode(inp)
            z = ae.postencode(mu, logvar, use_mode=True)[0].cpu().numpy()
            means[:, y // 8 : y // 8 + 64, x // 8 : x // 8 + 64] += z * weight
            weights[y // 8 : y // 8 + 64, x // 8 : x // 8 + 64] += weight
    if np.any(weights <= 0):
        raise ValueError("Encoder overlap did not cover the full context")
    means /= weights
    rebuilt = np.zeros((n, n), np.float32)
    full_weights = np.zeros((n, n), np.float32)
    weight_hr = linear_weight_window(512, "cpu", torch.float32).numpy()
    for y in range(0, n - 511, 256):
        for x in range(0, n - 511, 256):
            z = torch.from_numpy(means[:, y // 8 : y // 8 + 64, x // 8 : x // 8 + 64])[None].cuda()
            dec = ae.decode(z)[0, 0].cpu().numpy() * RESIDUAL_STD
            rebuilt[y : y + 512, x : x + 512] += dec * weight_hr
            full_weights[y : y + 512, x : x + 512] += weight_hr
    rebuilt /= full_weights
    sqrt_height = laplacian_decode(rebuilt, low)
    roundtrip = np.sign(sqrt_height) * sqrt_height**2
    latent = np.concatenate([means, ((low + 31.4) / 38.6)[None]], axis=0)
    return latent, roundtrip[PAD:-PAD, PAD:-PAD]


def frozen(world: WorldPipeline, field: np.ndarray, tile: int, name: str) -> InfiniteTensor:
    def read(ctx):
        _, i, j = ctx
        yy = np.clip(np.arange(i * tile, (i + 1) * tile), 0, field.shape[1] - 1)
        xx = np.clip(np.arange(j * tile, (j + 1) * tile), 0, field.shape[2] - 1)
        data = field[:, yy[:, None], xx[None, :]]
        return torch.from_numpy(np.concatenate([data, np.ones((1, tile, tile), np.float32)]))

    return InfiniteTensor(
        shape=(field.shape[0] + 1, None, None),
        f=read,
        output_window=TensorWindow(
            size=(field.shape[0] + 1, tile, tile), stride=(field.shape[0] + 1, tile, tile)
        ),
        tile_store=world.tile_store,
        tensor_id=name,
    )


def condition(source: np.ndarray) -> np.ndarray:
    """Derive height statistics only from supplied source; climate is held constant."""
    p = np.pad(source, PAD, mode="edge")
    h = np.sign(p) * np.sqrt(np.abs(p))
    blocks = h.reshape(h.shape[0] // 256, 256, h.shape[1] // 256, 256).transpose(0, 2, 1, 3)
    stats = np.empty((6, blocks.shape[0], blocks.shape[1]), np.float32)
    stats[0] = blocks.mean(axis=(2, 3))
    stats[1] = np.percentile(blocks, 5, axis=(2, 3))
    # These are upstream-unit controls, not a climate prediction for each world.
    stats[2:] = np.array([15.87, 619.26, 833.12, 69.40], np.float32)[:, None, None]
    return stats


def stage(
    world: WorldPipeline,
    previous: InfiniteTensor,
    sigma: float,
    name: str,
    reference: np.ndarray | None = None,
    wavelength_px: float = 0,
) -> InfiniteTensor:
    scheduler = EDMDPMSolverMultistepScheduler(sigma_min=0.002, sigma_max=80, sigma_data=0.5)
    angle = torch.atan(torch.tensor(sigma / 0.5))
    weight = linear_weight_window(64, "cpu", torch.float32)
    means = torch.tensor([14.99, 11.65, 15.87, 619.26, 833.12, 69.40, 0.66])
    stds = torch.tensor([21.72, 21.78, 10.40, 452.29, 738.09, 34.59, 0.47])
    histogram = torch.tensor([world.kwargs["histogram_raw"]])
    low = None
    smooth_sigma = wavelength_px * np.sqrt(np.log(2)) / (np.sqrt(2) * np.pi)
    if reference is not None:
        low = gaussian_filter(reference, (0, smooth_sigma, smooth_sigma), mode="nearest")

    def infer(ctxs, samples, conds):
        outputs = world._latent_inference(
            ctxs,
            samples,
            conds,
            angle,
            scheduler,
            weight,
            histogram,
            means,
            stds,
            seed_offset=5819 if sigma == 80 else 5820,
        )
        return outputs

    window = TensorWindow(size=(6, 64, 64), stride=(6, 32, 32))
    tensor = InfiniteTensor(
        shape=(6, None, None),
        f=infer,
        output_window=window,
        args=(previous, world.coarse),
        args_windows=(window, TensorWindow(size=(7, 4, 4), stride=(7, 1, 1), offset=(0, -1, -1))),
        batch_size=[1, 2, 4, 8, 16],
        tile_store=world.tile_store,
        tensor_id=name,
    )
    if low is None:
        return tensor
    halo = int(np.ceil(4 * smooth_sigma))

    def project(ctx, sample):
        data = (sample[:-1] / sample[-1:]).numpy()
        filtered = gaussian_filter(data, (0, smooth_sigma, smooth_sigma), mode="nearest")
        correction = (data - filtered)[:, halo : halo + 32, halo : halo + 32]
        _, i, j = ctx
        yy = np.clip(np.arange(i * 32, i * 32 + 32), 0, low.shape[1] - 1)
        xx = np.clip(np.arange(j * 32, j * 32 + 32), 0, low.shape[2] - 1)
        result = correction + low[:, yy[:, None], xx[None, :]]
        return torch.from_numpy(np.concatenate([result, np.ones((1, 32, 32), np.float32)]))

    return InfiniteTensor(
        shape=(6, None, None),
        f=project,
        output_window=TensorWindow(size=(6, 32, 32), stride=(6, 32, 32)),
        args=(tensor,),
        args_windows=(
            TensorWindow(
                size=(6, 32 + 2 * halo, 32 + 2 * halo), stride=(6, 32, 32), offset=(0, -halo, -halo)
            ),
        ),
        tile_store=world.tile_store,
        tensor_id=name + "_projected",
    )


def roundtrip_gate(source: np.ndarray, rebuilt: np.ndarray, pixel_km: float) -> dict:
    sigma = 1.4375 * np.sqrt(np.log(2)) / (np.sqrt(2) * np.pi * pixel_km)
    ga = np.gradient(gaussian_filter(source, sigma))
    gb = np.gradient(gaussian_filter(rebuilt, sigma))
    norm = np.hypot(*ga) * np.hypot(*gb)
    valid = norm > 1
    cosine = (ga[0] * gb[0] + ga[1] * gb[1]) / np.maximum(norm, 1e-12)
    rmse = float(np.sqrt(np.mean((source - rebuilt).astype(np.float64) ** 2)))
    alignment = float(cosine[valid].mean())
    return dict(
        rmse_m=rmse, slope_cosine_at_1_4375km=alignment, passed=rmse < 50 and alignment > 0.95
    )


@torch.no_grad()
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("inputs", "output", "world-model", "autoencoder"):
        parser.add_argument("--" + flag, type=Path, required=True)
    parser.add_argument("--round", choices=("fine", "coarse"), required=True)
    parser.add_argument("--cases", nargs="*")
    args = parser.parse_args()
    if file_hash(args.autoencoder / "diffusion_pytorch_model.safetensors") != AE_HASH:
        raise ValueError("Autoencoder weight hash differs from the fixed experiment")
    torch.set_num_threads(8)
    torch.manual_seed(42)
    ae = EDMAutoencoder.from_pretrained(str(args.autoencoder), local_files_only=True).cuda().eval()
    world = WorldPipeline.from_pretrained(
        str(args.world_model),
        seed=42,
        torch_compile=False,
        latents_batch_size=[1, 2, 4, 8, 16],
        caching_strategy="direct",
        cache_limit=4 << 30,
        residual_std=RESIDUAL_STD,
        cond_snr=[0.05, 0.2, 1.0, 0.2, 1.0],
    ).to("cuda")
    for name in args.cases or (FINE if args.round == "fine" else COARSE):
        started = time.monotonic()
        meta, source = prepare(args.inputs, args.output, name)
        case = args.output / name
        latent, rebuilt = encode(ae, source)
        save(case / "ae-roundtrip.meters.npy", rebuilt)
        save(case / "source.latent.npy", latent)
        gate = roundtrip_gate(source, rebuilt, meta["pixel_km"])
        (case / "ae-gate.json").write_text(json.dumps(gate, indent=2) + "\n", encoding="utf-8")
        print(name, "AE", gate, flush=True)
        if args.round == "fine" and not gate["passed"]:
            continue
        arms = (
            ("decoder", "edit-0065", "edit-035")
            if args.round == "fine"
            else ("unprojected", "projected")
        )
        for arm in arms:
            start = time.monotonic()
            torch.cuda.reset_peak_memory_stats()
            world.bind(hdf5_file=None)
            world._init_tile_store(None, None, None, None)
            world.coarse = frozen(world, condition(source), 16, "source_coarse")
            ref = frozen(world, latent, 32, "source_latent")
            if arm == "decoder":
                world.latents = ref
            elif arm.startswith("edit"):
                world.latents = stage(world, ref, 0.065 if arm == "edit-0065" else 0.35, arm)
            else:
                zero = frozen(world, np.zeros_like(latent), 32, "zero_latent")
                kwargs = (
                    dict(reference=latent, wavelength_px=meta["native_km"] / (meta["pixel_km"] * 8))
                    if arm == "projected"
                    else {}
                )
                first = stage(world, zero, 80, "initial", **kwargs)
                world.latents = stage(world, first, 0.35, "second", **kwargs)
            world.residual = world._build_decoder_stage()
            result = world.get(PAD, PAD, PAD + SIZE, PAD + SIZE, with_climate=False)["elev"].numpy()
            repeat = world.get(PAD, PAD, PAD + SIZE, PAD + SIZE, with_climate=False)["elev"].numpy()
            max_repeat = float(np.max(np.abs(result - repeat)))
            if max_repeat != 0:
                raise ValueError(f"Cached repeat changed by {max_repeat} metres")
            save(case / f"{arm}.meters.npy", result)
            subwindow = world.get(PAD, PAD, PAD + 256, PAD + 256, with_climate=False)[
                "elev"
            ].numpy()
            receipt = dict(
                arm=arm,
                td_commit="e8dcb4b1a834ab2f6b1a6f5256ed7c9f2f3e8230",
                noise_sigma=0.065 if arm == "edit-0065" else 0.35 if arm == "edit-035" else None,
                sigma_data=0.5,
                projection_response_wavelength_km=meta["native_km"] if arm == "projected" else None,
                source_sha256=file_hash(case / "source.meters.npy"),
                elapsed_s=time.monotonic() - start,
                seed=42,
                residual_std=RESIDUAL_STD,
                encoder_revision=args.autoencoder.name,
                world_revision=args.world_model.name,
                peak_gpu_allocated_GiB=torch.cuda.max_memory_allocated() / 1024**3,
                cached_repeat_max_m=max_repeat,
                subwindow_query_max_difference_m=float(
                    np.max(np.abs(result[:256, :256] - subwindow))
                ),
                conditioning="source mean/p5 and fixed training-unit climate controls",
                output_sha256=file_hash(case / f"{arm}.meters.npy"),
            )
            (case / f"{arm}.receipt.json").write_text(
                json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
            )
            print(name, receipt, flush=True)
            world.close()
        print(name, "complete", time.monotonic() - started, flush=True)


if __name__ == "__main__":
    main()
