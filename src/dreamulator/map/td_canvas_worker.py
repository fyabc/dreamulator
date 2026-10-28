"""td_canvas_worker — one GPU worker that generates a canvas's chunks with terrain-diffusion.

Runs **inside the terrain-diffusion venv** (launched by ``dreamulator canvas generate`` with that
venv's interpreter, cwd = the terrain-diffusion clone), so it imports nothing from dreamulator;
the shared conventions it needs are restated here and covered by tests on the main side.

The worker loads the model once, installs the five conditioning rasters from
``<canvas>/conditioning/`` (edge padding as upstream ``tiff_export``) and generates its share of
the manifest in ``canvas.json``: worker k of K takes the k-th contiguous slice of the row-major
list, so neighbouring chunks reuse cached latents.  Each chunk is written as int16 metres to
``chunks/r<ci:03d>_c<cj:03d>.npy`` via a temporary file and a rename, then its SHA-256 is
appended to ``chunks.sha256`` under an exclusive lock.  A chunk whose file exists and whose listed
checksum matches is skipped (resume).  ``--check`` also regenerates the first chunk of the next
worker's slice into ``chunks/check/`` (cross-process consistency; not listed).

Usage: <td-venv>/python td_canvas_worker.py <canvas_dir> <worker> <n_workers> [--check]
       [--only chunks.json]
       <td-venv>/python td_canvas_worker.py --prepare-coarse <reference> <candidate> <output>
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO

if TYPE_CHECKING:
    from collections.abc import Iterator

PX = 256
#: (file, channel, internal scale, default) as in upstream tiff_export
CHANNELS = [
    ("heightmap", 0, 1.0, -1000.0),
    ("temperature", 1, 1.0, None),
    ("temperature_std", 2, 100.0, None),
    ("precipitation", 3, 1.0, None),
    ("precipitation_cv", 4, 1.0, None),
]


def chunk_name(ci: int, cj: int) -> str:
    return f"r{ci:03d}_c{cj:03d}.npy"


def read_checksums(sha_file: Path) -> dict[str, str]:
    if not sha_file.exists():
        return {}
    out = {}
    for line in sha_file.read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, name = line.split(None, 1)
            out[name.strip()] = digest
    return out


def worker_slice(
    chunks: list[list[int]], k: int, n: int
) -> tuple[list[list[int]], list[int] | None]:
    """Worker k's contiguous share of the manifest, and the next share's first chunk (or None)."""
    per = (len(chunks) + n - 1) // n
    nxt = chunks[(k + 1) * per] if (k + 1) * per < len(chunks) else None
    return chunks[k * per : (k + 1) * per], nxt


def pending(canvas: Path, mine: list[list[int]]) -> list[tuple[int, int]]:
    """Chunks of ``mine`` without a file whose checksum is listed and matches."""
    done = read_checksums(canvas / "chunks.sha256")
    todo = []
    for i, j in mine:
        p = canvas / "chunks" / chunk_name(i, j)
        if p.exists() and done.get(p.name) == hashlib.sha256(p.read_bytes()).hexdigest():
            continue
        todo.append((i, j))
    return todo


def generation_queries(
    prefix: list[list[int]], todo: list[tuple[int, int]]
) -> Iterator[tuple[int, int, bool]]:
    """Replay history once, emitting targets at their last recorded query.

    Historical warmup and generation may both query a target. Save its final
    recorded result during replay: querying it again can rebuild evicted GPU
    caches with different floating-point results. New targets follow history
    in the manifest's order; resumed targets still participate in the replay.
    """
    targets = set(todo)
    last = {(i, j): index for index, (i, j) in enumerate(prefix)}
    for index, (i, j) in enumerate(prefix):
        yield i, j, (i, j) in targets and index == last[(i, j)]
    for i, j in todo:
        if (i, j) not in last:
            yield i, j, True


def _lock_exclusive(f: TextIO) -> None:
    """Advisory whole-file exclusive lock, portable across POSIX and Windows.

    POSIX uses ``fcntl.flock``; Windows has no fcntl, so ``msvcrt.locking``
    locks the first byte of the file instead (workers only append lines, so
    byte 0 is never a data byte anybody writes concurrently).  ``LK_LOCK``
    retries for ~10 s rather than failing at once, matching flock's
    block-until-available behaviour closely enough for chunk bookkeeping.
    """
    if sys.platform == "win32":
        import msvcrt

        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
        return
    import fcntl

    fcntl.flock(f.fileno(), fcntl.LOCK_EX)


def _unlock(f: TextIO) -> None:
    if sys.platform == "win32":
        import msvcrt

        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def append_checksum(sha_file: Path, digest: str, name: str) -> None:
    with open(sha_file, "a", encoding="utf-8") as f:
        _lock_exclusive(f)
        f.write(f"{digest}  {name}\n")
        f.flush()
        _unlock(f)


def validate_coarse_statistics(candidate: Any, reference: Any) -> None:
    """Check the accepted spread and four climate channels of a six-channel field."""
    import numpy as np

    if candidate.dtype != np.float32 or reference.dtype != np.float32:
        raise ValueError("coarse sources must use float32 encoding")
    if candidate.ndim != 3 or candidate.shape[0] != 6 or candidate.shape != reference.shape:
        raise ValueError("coarse sources need matching six-channel fields")
    if not np.isfinite(candidate).all() or not np.isfinite(reference).all():
        raise ValueError("coarse sources must be finite")
    if not np.array_equal(candidate[2:], reference[2:]):
        raise ValueError("coarse source changed a fixed climate channel")
    # Subtraction at the new mean retains float32 roundoff; signed spreads
    # are valid in the existing TD encoding.
    if not np.allclose(candidate[0] - candidate[1], reference[0] - reference[1], rtol=0, atol=8e-6):
        raise ValueError("coarse source changed the accepted mean-minus-p5 spread")


def translate_coarse_mean(reference: Any, new_mean: Any) -> Any:
    """Shift mean and p5 together, preserving zero-response cells bit for bit.

    All values use the TD float32 encoding. Computing p5 from a freshly
    subtracted spread would round even where the mean did not change; an
    additive translation leaves those reference values intact.
    """
    import numpy as np

    validate_coarse_statistics(reference, reference)
    mean = np.asarray(new_mean)
    if mean.dtype != np.float32 or mean.shape != reference.shape[1:]:
        raise ValueError("new mean must match the reference float32 footprint grid")
    if not np.isfinite(mean).all():
        raise ValueError("new mean must be finite")
    result = reference.copy()
    changed = mean != reference[0]
    shift = mean[changed] - reference[0][changed]
    result[0][changed] = mean[changed]
    result[1][changed] = reference[1][changed] + shift
    validate_coarse_statistics(result, reference)
    return result


def read_coarse_source(canvas: Path, meta: dict[str, Any]) -> Any:
    """Read and validate a self-contained, checksummed statistical source."""
    import numpy as np

    descriptor = meta["coarse_source"]
    if descriptor.get("format") != "fixed-coarse-statistics-v1":
        raise ValueError("unsupported coarse statistical source")
    fields = []
    for name in ("field", "reference"):
        item = descriptor[name]
        path = (canvas / item["path"]).resolve()
        if not path.is_relative_to(canvas.resolve()):
            raise ValueError("coarse source must be contained in the canvas batch")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != item["sha256"]:
            raise ValueError(f"coarse source checksum mismatch: {name}")
        fields.append(np.load(path))
    n = int(meta["geometry"]["ncell"]) + 2 * int(meta["generation"]["edge_padding_cells"])
    if fields[0].shape != (6, n, n) or list(fields[0].shape) != descriptor["shape"]:
        raise ValueError("coarse source shape does not match the padded canvas")
    validate_coarse_statistics(*fields)
    return fields[0]


def _read_conditioning(canvas: Path, meta: dict[str, Any]) -> dict[str, Any]:
    """Validate each complete input before installing it in the TD pipeline."""
    import numpy as np

    ncell = int(meta["geometry"]["ncell"])
    arrays = {}
    for name, _, _, _ in CHANNELS:
        path = canvas / "conditioning" / f"{name}.npy"
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != meta["conditioning_sha256"].get(name):
            raise ValueError(f"conditioning checksum mismatch: {name}")
        array = np.load(path)
        if array.dtype != np.float32 or array.shape != (ncell, ncell):
            raise ValueError(f"conditioning must match the float32 footprint grid: {name}")
        if not np.isfinite(array).all():
            raise ValueError(f"conditioning must be finite: {name}")
        arrays[name] = array
    return arrays


def prepare_coarse_statistics(
    world: Any, reference_canvas: Path, candidate_canvas: Path, *, refresh_climate: bool = False
) -> Any:
    """Generate a candidate mean against the same accepted reference statistics.

    The caller binds the pinned model, seed and condition SNR first. A frozen
    reference shared field is used directly when available. Otherwise it is
    generated from the verified reference conditioning. Each changed import
    rebuilds the tile store before queries; all four climate outputs and the
    mean-minus-p5 spread are retained from the reference field.
    """
    import numpy as np

    meta = [
        json.loads((canvas / "canvas.json").read_text(encoding="utf-8"))
        for canvas in (reference_canvas, candidate_canvas)
    ]
    for name in ("geometry", "generation", "structure"):
        if meta[0].get(name) != meta[1].get(name):
            raise ValueError(f"statistical preparation needs the same reference {name}")
    if "height_refinement" in meta[0] and "coarse_source" not in meta[0]:
        raise ValueError("a refined reference needs its accepted frozen statistical source")
    arrays = [
        _read_conditioning(canvas, m)
        for canvas, m in zip((reference_canvas, candidate_canvas), meta, strict=True)
    ]
    for name, _, _, _ in CHANNELS[1:]:
        if not refresh_climate and arrays[0][name].tobytes() != arrays[1][name].tobytes():
            raise ValueError(f"statistical preparation changed a reference climate input: {name}")
    pad = int(meta[0]["generation"]["edge_padding_cells"])
    n = int(meta[0]["geometry"]["ncell"]) + 2 * pad

    def query(inputs: dict[str, Any]) -> Any:
        for name, channel, scale, default in CHANNELS:
            world.set_custom_conditioning_import(
                channel,
                np.pad(inputs[name] * scale, pad, mode="edge"),
                0,
                0,
                default_value=default,
                rebuild=False,
            )
        world.rebuild()
        raw = world.coarse[:, 0:n, 0:n]
        raw_array = raw.numpy()
        if (
            raw_array.shape != (7, n, n)
            or not np.isfinite(raw_array).all()
            or np.any(raw_array[-1] <= 0)
        ):
            raise ValueError(
                "TD coarse query must supply finite channels and positive blend weights"
            )
        field = (raw[:-1] / raw[-1:]).numpy().copy()
        validate_coarse_statistics(field, field)
        return field

    if "coarse_source" in meta[0]:
        reference = read_coarse_source(reference_canvas, meta[0])
    else:
        reference = query(arrays[0])
    if not refresh_climate and arrays[0]["heightmap"].tobytes() == arrays[1]["heightmap"].tobytes():
        return reference.copy(), reference
    candidate = query(arrays[1])
    if refresh_climate:
        # The accepted spread remains fixed; climate channels come from the new model query.
        reference = reference.copy()
        reference[2:] = candidate[2:]
    return translate_coarse_mean(reference, candidate[0]), reference


def _load_pipeline(gen_cfg: dict[str, Any]) -> Any:
    """Load the pinned production TD model in the worker environment."""
    from terrain_diffusion.inference.world_pipeline import (  # type: ignore[import-not-found,unused-ignore]
        WorldPipeline,
    )

    hub = Path(os.environ.get("HF_HUB_CACHE", Path.home() / ".cache/huggingface/hub"))
    snaps = hub / f"models--{gen_cfg['model'].replace('/', '--')}" / "snapshots"
    if gen_cfg.get("model_revision") and not (snaps / gen_cfg["model_revision"]).exists():
        raise SystemExit(f"model snapshot {gen_cfg['model_revision']} not in {snaps}")
    model = (
        str(snaps / gen_cfg["model_revision"])
        if gen_cfg.get("model_revision")
        else gen_cfg["model"]
    )
    world = WorldPipeline.from_pretrained(
        model,
        seed=int(gen_cfg["seed"]),
        latents_batch_size=[1, 2, 4, 8, 16],
        torch_compile=bool(gen_cfg["torch_compile"]),
        dtype=None,
        caching_strategy="direct",
        cache_limit=4 << 30,
        **gen_cfg.get("pipeline_kwargs", {}),  # e.g. residual_std (output-time detail scale)
    )
    world.to("cuda")
    world.set_cond_snr(gen_cfg["cond_snr"])
    world.bind(hdf5_file=None)
    return world


def prepare_coarse_main(argv: list[str]) -> None:  # pragma: no cover - needs pinned TD and GPU
    """Write one reusable, checksummed shared field before normal HD generation."""
    import numpy as np
    import torch  # type: ignore[import-not-found,unused-ignore]

    reference, candidate, output = (Path(path) for path in argv[2:5])
    if output.exists():
        raise FileExistsError("coarse statistics output must be a new batch")
    meta = json.loads((candidate / "canvas.json").read_text(encoding="utf-8"))
    started = time.perf_counter()
    torch.set_num_threads(1)
    with _load_pipeline(meta["generation"]) as world:
        torch.cuda.synchronize()
        ready = time.perf_counter()
        field, baseline = prepare_coarse_statistics(
            world, reference, candidate, refresh_climate="--refresh-climate" in argv[5:]
        )
        torch.cuda.synchronize()
        prepared = time.perf_counter()
    output.mkdir(parents=True, exist_ok=False)
    receipt: dict[str, Any] = {
        "format": "prepared-coarse-statistics-v1",
        "reference_canvas_sha256": hashlib.sha256(
            (reference / "canvas.json").read_bytes()
        ).hexdigest(),
        "candidate_canvas_sha256": hashlib.sha256(
            (candidate / "canvas.json").read_bytes()
        ).hexdigest(),
        "shape": list(field.shape),
        "model_ready_s": ready - started,
        "prepare_s": prepared - ready,
        "spread_policy": "reference mean-minus-p5",
        "climate_policy": (
            "new conditioning query" if "--refresh-climate" in argv[5:] else "fixed reference"
        ),
    }
    for name, value in (("field", field), ("reference", baseline)):
        path = output / f"{name}.npy"
        np.save(path, value)
        with path.open("rb") as stream:
            receipt[name] = {
                "path": path.name,
                "sha256": hashlib.file_digest(stream, "sha256").hexdigest(),
            }
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt), flush=True)


def main(argv: list[str]) -> None:  # pragma: no cover - needs the terrain-diffusion venv and a GPU
    import numpy as np
    import torch  # type: ignore[import-not-found,unused-ignore]

    canvas, k, nw = Path(argv[1]), int(argv[2]), int(argv[3])
    meta = json.loads((canvas / "canvas.json").read_text(encoding="utf-8"))
    gen_cfg: dict[str, Any] = meta["generation"]
    cc = int(meta["geometry"]["chunk_cells"])
    pad = int(gen_cfg["edge_padding_cells"])
    chunks = meta["chunks"]
    if "--only" in argv:
        only_file = Path(argv[argv.index("--only") + 1])
        only = {tuple(c) for c in json.loads(only_file.read_text(encoding="utf-8"))}
        chunks = [c for c in chunks if tuple(c) in only]
    mine, nxt = worker_slice(chunks, k, nw)
    extra = nxt if "--check" in argv else None
    out = canvas / "chunks"
    out.mkdir(exist_ok=True)
    sha_file = canvas / "chunks.sha256"
    log = open(canvas / f"worker{k}.log", "a", encoding="utf-8")  # noqa: SIM115
    todo = pending(canvas, mine)
    print(
        f"worker {k}: {len(mine)} chunks, {len(mine) - len(todo)} already done",
        file=log,
        flush=True,
    )
    if not todo and extra is None:
        return

    t0 = time.time()
    world = _load_pipeline(gen_cfg)
    for name, ch, scale, default in CHANNELS:
        arr = np.load(canvas / "conditioning" / f"{name}.npy").astype(np.float32) * scale
        world.set_custom_conditioning_import(
            ch, np.pad(arr, pad, mode="edge"), 0, 0, default_value=default
        )
    if "coarse_source" in meta:
        from infinite_tensor import (  # type: ignore[import-not-found,unused-ignore]
            InfiniteTensor,
            TensorWindow,
        )

        field = read_coarse_source(canvas, meta)
        world._init_tile_store(None, None, None, None)

        def frozen(ctx: Any) -> Any:
            _, i, j = ctx
            r, c = i * 16, j * 16
            if min(r, c) < 0 or r + 16 > field.shape[1] or c + 16 > field.shape[2]:
                raise ValueError("coarse source coverage exceeded by the TD query")
            return torch.from_numpy(
                np.concatenate([field[:, r : r + 16, c : c + 16], np.ones((1, 16, 16), np.float32)])
            )

        world.coarse = InfiniteTensor(
            shape=(7, None, None),
            f=frozen,
            output_window=TensorWindow(size=(7, 16, 16), stride=(7, 16, 16)),
            tile_store=world.tile_store,
            tensor_id="fixed_statistics_" + meta["coarse_source"]["field"]["sha256"],
        )
        world.latents = world._build_latent_stage()
        world.residual = world._build_decoder_stage()
    t_ready = time.time()
    print(f"ready {t_ready - t0:.1f}s, {len(todo)} to generate", file=log, flush=True)

    def gen(i: int, j: int) -> Any:
        r1, c1 = (pad + i * cc) * PX, (pad + j * cc) * PX
        res = world.get(r1, c1, r1 + cc * PX, c1 + cc * PX, with_climate=False)
        return np.clip(res["elev"].numpy(), -32768, 32767).astype(np.int16)

    times = []
    with world:
        # An accepted batch can carry its original query prefix, so GPU
        # cache population follows the recorded evaluation order.
        prefix = meta.get("coarse_source", {}).get("query_prefix", [])
        for i, j in prefix:
            if min(i, j) < 0 or (max(i, j) + 1) * cc > int(meta["geometry"]["ncell"]):
                raise ValueError("query prefix lies outside the canvas footprint grid")
        for i, j, emit in generation_queries(prefix, todo):
            s = time.time()
            arr = gen(i, j)
            if not emit:
                continue
            final = out / chunk_name(i, j)
            tmp = final.with_suffix(f".tmp{k}.npy")
            np.save(tmp, arr)
            os.replace(tmp, final)
            append_checksum(sha_file, hashlib.sha256(final.read_bytes()).hexdigest(), final.name)
            torch.cuda.synchronize()
            times.append(time.time() - s)
            print(f"chunk {i} {j} {times[-1]:.2f}s", file=log, flush=True)
        if prefix:
            print(f"replayed {len(prefix)} reference prefix chunks", file=log, flush=True)
        if extra is not None:
            (out / "check").mkdir(exist_ok=True)
            np.save(out / "check" / f"{chunk_name(*extra)[:-4]}_w{k}.npy", gen(*extra))
    summary = {
        "worker": k,
        "generated": len(times),
        "ready_s": round(t_ready - t0, 1),
        "gen_s": round(time.time() - t_ready, 1),
        "per_chunk_median_s": float(np.median(times)) if times else None,
    }
    print(json.dumps(summary), file=log, flush=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--prepare-coarse":
        prepare_coarse_main(sys.argv)
    else:
        main(sys.argv)
