#!/usr/bin/env python3
"""Köppen confusion-matrix diagnostic — per-class precision/recall/F1.

Runs the climate engine on the Earth (baseline) mesh, compares the simulated
Köppen class against the Beck et al. (2018) per-cell reference, and reports:

  - a full confusion matrix (observed rows → simulated columns),
  - per-class precision / recall / F1,
  - top confusion pairs (off-diagonal),
  - the two v0.27 tuning targets (BWk cold desert → C/D, ET tundra → C/D).

Usage::

    uv run python scripts/diagnose_koppen_confusion.py
    uv run python scripts/diagnose_koppen_confusion.py --top 15
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np


def _find_project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_mesh(world_dir: Path, planet_id: str, branch: str | None = None) -> object | None:
    from pydantic import TypeAdapter

    from dreamulator.map.models import CVTMesh

    search_dirs = [world_dir]
    if branch:
        search_dirs.insert(0, world_dir / "branches" / branch)
    for base in search_dirs:
        p = base / "maps" / planet_id / "cvt_mesh.json"
        if p.exists():
            # Rust pydantic-core parser — no intermediate dict, ~5× faster and
            # far less memory than json.load + CVTMesh(**data) on a 244 MB mesh.
            from dreamulator.map.export import decompress_mesh_bytes

            return TypeAdapter(CVTMesh).validate_json(decompress_mesh_bytes(p.read_bytes()))
    return None


def _cohens_kappa(matrix: np.ndarray) -> float:
    """Cohen's kappa from a confusion matrix (rows = observed, cols = simulated).

    κ = (p_o − p_e) / (1 − p_e), where p_o is the observed agreement and p_e the
    agreement expected by chance under the observed marginal distributions.
    """
    total = int(matrix.sum())
    if total == 0:
        return 0.0
    p_o = float(np.trace(matrix)) / total
    p_e = float((matrix.sum(axis=1) * matrix.sum(axis=0)).sum()) / (total * total)
    if p_e == 1.0:
        return 1.0
    return (p_o - p_e) / (1.0 - p_e)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", default="earth")
    parser.add_argument("--planet", default="planet_earth")
    parser.add_argument("--branch", default="climate-dev")
    parser.add_argument("--top", type=int, default=12, help="number of top confusions to show")
    parser.add_argument(
        "--no-auto-lat-gradient",
        action="store_false",
        dest="auto_lat_gradient",
        default=True,
        help="disable auto_lat_gradient (fall back to manual --lat-gradient-c)",
    )
    parser.add_argument(
        "--no-diffusive-heat-transport",
        action="store_false",
        dest="diffusive_heat_transport",
        default=True,
        help="disable graph-Laplacian diffusive heat transport",
    )
    parser.add_argument(
        "--lat-gradient-c",
        type=float,
        default=45.0,
        help="manual equator-pole ΔT when auto_lat_gradient is off",
    )
    args = parser.parse_args()

    root = _find_project_root()
    world_dir = root / "data" / "worlds" / args.world

    print(f"Loading Earth mesh ({args.world}, branch={args.branch}) ...")
    mesh = _load_mesh(world_dir, args.planet, args.branch)
    if mesh is None:
        print("  ERROR: no mesh found")
        return

    print(f"Running climate engine on {mesh.num_cells} cells ...")
    from dreamulator.map.climate_simulator import simulate_climate
    from dreamulator.validate_climate import build_earth_validation_config

    simulate_climate(
        mesh,
        build_earth_validation_config(
            mesh.num_cells,
            lat_gradient_c=args.lat_gradient_c,
            auto_lat_gradient=args.auto_lat_gradient,
            diffusive_heat_transport=args.diffusive_heat_transport,
        ),
    )

    # Load Beck 2018 reference
    obs_path = world_dir / "branches" / args.branch / "maps" / args.planet / "koppen_obs.json"
    if not obs_path.exists():
        print(f"  ERROR: koppen_obs.json not found at {obs_path}")
        return
    with obs_path.open("r", encoding="utf-8") as f:
        obs_cells = json.load(f).get("cells", {})

    # Collect (obs, sim) pairs for comparable land cells
    confusion: Counter[tuple[str, str]] = Counter()
    for c in mesh.cells:
        obs = obs_cells.get(str(c.id), "N/A")
        sim = c.koppen_class or "Ocean"
        if obs == "N/A" or sim == "Ocean":
            continue
        confusion[(obs, sim)] += 1

    if not confusion:
        print("  ERROR: no comparable cells")
        return

    # Class universe (union of obs and sim)
    classes = sorted({k[0] for k in confusion} | {k[1] for k in confusion})
    n = len(classes)
    idx = {k: i for i, k in enumerate(classes)}

    # Confusion matrix (obs rows → sim cols)
    matrix = np.zeros((n, n), dtype=int)
    for (obs, sim), cnt in confusion.items():
        matrix[idx[obs], idx[sim]] += cnt

    # Per-class precision / recall / F1 (over the full class universe)
    print("\n=== Per-class precision / recall / F1 ===\n")
    print(f"{'class':>6} {'n_obs':>7} {'n_sim':>7} {'prec':>6} {'recall':>7} {'f1':>6}")
    precisions = {}
    recalls = {}
    for k in classes:
        tp = matrix[idx[k], idx[k]]
        obs_total = matrix[idx[k], :].sum()
        sim_total = matrix[:, idx[k]].sum()
        prec = tp / sim_total if sim_total else 0.0
        rec = tp / obs_total if obs_total else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        precisions[k] = prec
        recalls[k] = rec
        print(f"{k:>6} {obs_total:>7} {sim_total:>7} {prec:>6.2f} {rec:>7.2f} {f1:>6.2f}")

    # Macro-average
    macro_p = float(np.mean(list(precisions.values())))
    macro_r = float(np.mean(list(recalls.values())))
    print(f"\n  macro precision={macro_p:.2f}  macro recall={macro_r:.2f}")

    # Overall accuracy
    total = matrix.sum()
    correct = int(np.trace(matrix))
    print(f"  overall accuracy={correct / total:.1%} ({correct}/{total} cells)")

    # Cohen's Kappa — 30-class cell-by-cell + 5-group (A/B/C/D/E)
    kappa_full = _cohens_kappa(matrix)
    groups = sorted({k[0] for k in classes})
    g_idx = {g: i for i, g in enumerate(groups)}
    g_matrix = np.zeros((len(groups), len(groups)), dtype=int)
    for (obs, sim), cnt in confusion.items():
        g_matrix[g_idx[obs[0]], g_idx[sim[0]]] += cnt
    kappa_group = _cohens_kappa(g_matrix)
    group_correct = int(np.trace(g_matrix))
    print("\n=== Cohen's Kappa ===")
    print(
        f"  5-group (A/B/C/D/E): kappa={kappa_group:.3f}  "
        f"accuracy={group_correct / g_matrix.sum():.1%}"
    )
    print(f"  30-class cell-by-cell: kappa={kappa_full:.3f}")

    # Top confusion pairs (off-diagonal)
    off_diag = [(cnt, obs, sim) for (obs, sim), cnt in confusion.items() if obs != sim]
    off_diag.sort(reverse=True)
    print(f"\n=== Top {args.top} confusion pairs (obs → sim) ===\n")
    for cnt, obs, sim in off_diag[: args.top]:
        print(f"  {obs:>5} → {sim:<5} {cnt:>7} cells")

    # v0.27 tuning targets: BWk (cold desert) and ET (tundra) confusion with C/D
    print("\n=== v0.27 tuning targets (BWk / ET confusions) ===")
    for target in ("BWk", "ET"):
        cw = [
            (cnt, o, s)
            for (o, s), cnt in confusion.items()
            if (o == target or s == target) and o != s
        ]
        total_conf = sum(cnt for cnt, _, _ in cw)
        print(f"  {target}: {total_conf} confused cells")
        for cnt, o, s in sorted(cw, reverse=True)[:5]:
            print(f"    {o} → {s}: {cnt}")


if __name__ == "__main__":
    main()
