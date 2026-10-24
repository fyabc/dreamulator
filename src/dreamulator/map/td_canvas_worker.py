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
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

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


def append_checksum(sha_file: Path, digest: str, name: str) -> None:
    import fcntl

    with open(sha_file, "a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(f"{digest}  {name}\n")
        f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)


def main(argv: list[str]) -> None:  # pragma: no cover - needs the terrain-diffusion venv and a GPU
    import numpy as np
    import torch  # type: ignore[import-not-found,unused-ignore]
    from terrain_diffusion.inference.world_pipeline import (  # type: ignore[import-not-found,unused-ignore]
        WorldPipeline,
    )

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

    # the model snapshot the layout pins must be the one the Hub cache resolves to
    hub = Path(os.environ.get("HF_HUB_CACHE", Path.home() / ".cache/huggingface/hub"))
    snaps = hub / f"models--{gen_cfg['model'].replace('/', '--')}" / "snapshots"
    if gen_cfg.get("model_revision") and not (snaps / gen_cfg["model_revision"]).exists():
        raise SystemExit(f"model snapshot {gen_cfg['model_revision']} not in {snaps}")
    t0 = time.time()
    world = WorldPipeline.from_pretrained(
        gen_cfg["model"],
        seed=int(gen_cfg["seed"]),
        latents_batch_size=[1, 2, 4, 8, 16],
        torch_compile=bool(gen_cfg["torch_compile"]),
        dtype=None,
        caching_strategy="direct",
        cache_limit=4 << 30,
    )
    world.to("cuda")
    world.set_cond_snr(gen_cfg["cond_snr"])
    world.bind(hdf5_file=None)
    for name, ch, scale, default in CHANNELS:
        arr = np.load(canvas / "conditioning" / f"{name}.npy").astype(np.float32) * scale
        world.set_custom_conditioning_import(
            ch, np.pad(arr, pad, mode="edge"), 0, 0, default_value=default
        )
    t_ready = time.time()
    print(f"ready {t_ready - t0:.1f}s, {len(todo)} to generate", file=log, flush=True)

    def gen(i: int, j: int) -> Any:
        r1, c1 = (pad + i * cc) * PX, (pad + j * cc) * PX
        res = world.get(r1, c1, r1 + cc * PX, c1 + cc * PX, with_climate=False)
        return np.clip(res["elev"].numpy(), -32768, 32767).astype(np.int16)

    times = []
    with world:
        for i, j in todo:
            s = time.time()
            arr = gen(i, j)
            final = out / chunk_name(i, j)
            tmp = final.with_suffix(f".tmp{k}.npy")
            np.save(tmp, arr)
            os.replace(tmp, final)
            append_checksum(sha_file, hashlib.sha256(final.read_bytes()).hexdigest(), final.name)
            torch.cuda.synchronize()
            times.append(time.time() - s)
            print(f"chunk {i} {j} {times[-1]:.2f}s", file=log, flush=True)
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
    main(sys.argv)
