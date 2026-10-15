#!/usr/bin/env python
"""Render a set of ExoPlaSim runs as a Markdown appendix with reproduction commands.

For each run directory the appendix lists the configuration (from ``manifest.json``), the
orbit PlaSim actually used (from the ``MOST_DIAG`` "Computed Orbital Parameters" block),
summary results (global 2 m temperature and sea ice over the last 5 model years, and the
change between the last two 5-year windows) and a command that reproduces the run.  The
command is the one recorded in the manifest when present; for older manifests an
equivalent explicit command is rebuilt from the recorded parameters, with the orbit
spelled out and the surface files located by their recorded hashes.  Needs the ``[gcm]``
environment (netCDF4).

Example:
    python scripts/climate/gcm/gcm_runs_appendix.py private/gcm/runs/t42o/* \\
        private/gcm/runs/t42a/* --out /tmp/appendix.md --preamble /tmp/preamble.md
"""

from __future__ import annotations

import argparse
import hashlib
import os
import json
import shlex
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from dreamulator.gcm.runner import parse_orbit_block  # noqa: E402

PARAM_FIELDS = {"radius", "gravity", "rotationperiod", "obliquity", "eccentricity", "flux",
                "year", "pressure", "startemp", "pN2", "pO2", "pAr", "pCO2", "lonvernaleq",
                "fixedorbit"}  # fmt: skip
# Surface files (.sra) live in the author-local GCM archive, which is not part of
# the repository; set GCM_ARCHIVE to its root so recorded hashes can be resolved.
_archive = os.environ.get("GCM_ARCHIVE")
SURFACE_DIRS = (Path(_archive) / "surf",) if _archive else ()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rel(path: str | Path) -> str:
    p = Path(path)
    try:
        return str(p.resolve().relative_to(REPO))
    except ValueError:
        return str(p)


def _find_by_hash(digest: str) -> str | None:
    for d in SURFACE_DIRS:
        for f in sorted(d.glob("*.sra")):
            if _sha256(f) == digest:
                return _rel(f)
    return None


def _world(manifest: dict) -> tuple[str, str]:
    year = manifest["configure_kwargs"].get("year", 0.0)
    return ("earth", "planet_earth") if abs(year - 365.25) < 1.0 else ("nacrea", "satellite_nacrea")


def rebuild_command(run: Path, manifest: dict) -> str:
    """Equivalent explicit run_exoplasim.py command for a manifest without a recorded one."""
    kw = manifest["configure_kwargs"]
    opts = manifest["model_options"]
    world, planet = _world(manifest)
    hashes = manifest.get("input_hashes", {})
    paths = manifest.get("input_paths", {})
    args = ["python", "scripts/climate/gcm/run_exoplasim.py", "--world", f"data/worlds/{world}",
            "--planet", planet, "--resolution", opts["resolution"], "--ncpus", str(opts["ncpus"]),
            "--years", str(opts["years"])]  # fmt: skip
    if kw.get("pCO2") is not None:
        args += ["--greenhouse-mode", "pco2", "--pco2-bar", repr(kw["pCO2"])]
    for name, flag in (("landmap", "--landmap"), ("topomap", "--topomap")):
        path = paths.get(name) or (_find_by_hash(hashes[name]) if name in hashes else None)
        if path:
            args += [flag, _rel(path)]
        elif name in hashes:
            args += [flag, f"<file with sha256 {hashes[name][:12]}…>"]
    extras = {k: v for k, v in kw.items() if k not in PARAM_FIELDS and k != "restartfile"}
    if extras:
        args += ["--configure", json.dumps(extras, ensure_ascii=False)]
    if opts.get("namelist_overrides"):
        args += ["--namelist", json.dumps(opts["namelist_overrides"], ensure_ascii=False)]
    orbit = {k: round(kw[k], 6) for k in ("eccentricity", "obliquity", "lonvernaleq") if k in kw}
    args += ["--override", json.dumps(orbit)]
    if kw.get("restartfile"):
        args += ["--restart", _rel(kw["restartfile"])]
    args += ["--workdir", _rel(run)]
    return shlex.join(args)


def results(nc: Path) -> dict[str, float]:
    import netCDF4

    ds = netCDF4.Dataset(str(nc))
    lat = np.asarray(ds["lat"][:], dtype=float)
    w = np.cos(np.radians(lat))[:, None] * np.ones(len(ds["lon"]))
    ocean = np.asarray(ds["lsm"][0]) < 0.5
    tas = np.asarray(ds["tas"][:], dtype=float) - 273.15
    sic = np.asarray(ds["sic"][:], dtype=float)
    gm = (tas * w).sum(axis=(1, 2)) / w.sum()
    ice = (sic * w * ocean).sum(axis=(1, 2)) / (w * ocean).sum() * 100.0
    return {
        "t_last5": float(gm[-60:].mean()),
        "trend": float(gm[-60:].mean() - gm[-120:-60].mean()) if len(gm) >= 120 else float("nan"),
        "ice_last5": float(ice[-60:].mean()),
        "records": int(len(gm)),
    }


def _fmt(value: float | None, spec: str) -> str:
    """Format a number, or an em dash when it is missing or not finite."""
    if value is None or not np.isfinite(value):
        return "—"
    return spec.format(value)


def render(runs: list[Path]) -> str:
    rows, cmds, hashes = [], [], {}
    common_conf: dict | None = None
    common_nl: dict | None = None
    for run in runs:
        mf = run / "manifest.json"
        if not mf.exists():
            continue
        m = json.loads(mf.read_text(encoding="utf-8"))
        kw = m["configure_kwargs"]
        diag = next(iter(sorted(run.glob("MOST_DIAG.?????"))), None)
        orbit = (
            parse_orbit_block(diag.read_text(encoding="utf-8", errors="replace")) if diag else {}
        )
        nc = next(iter(sorted(run.glob("MOST.?????.nc"))), None)
        res = results(nc) if nc else {}
        ppm = kw["pCO2"] / kw["pressure"] * 1e6 if kw.get("pCO2") else float("nan")
        mvelp = orbit.get("Long of perh(deg)", kw.get("lonvernaleq", float("nan")))
        seed = kw.get("restartfile")
        cells = [
            f"`{_rel(run)}`",
            f"{ppm:.1f} ppm",
            str(m["model_options"]["years"]),
            f"暖启动，种子 `{_rel(seed)}`" if seed else "冷启动",
            _fmt(orbit.get("Eccentricity"), "{:.6f}"),
            _fmt(orbit.get("Obliquity (deg)"), "{:.3f}°"),
            f"{mvelp:.3f}°（φ = {(mvelp - 180.0) % 360.0:.1f}°）",
            _fmt(res.get("t_last5"), "{:.2f} °C"),
            _fmt(res.get("trend"), "{:+.2f} K"),
            _fmt(res.get("ice_last5"), "{:.1f} %"),
            m.get("code_version") or "未记录",
        ]
        rows.append("| " + " | ".join(cells) + " |")
        cmd = m.get("command") or rebuild_command(run, m)
        source = "manifest 记录的原始命令" if m.get("command") else "由参数重建的等价显式命令"
        cmds.append(f"**`{_rel(run)}`**（{source}）：\n\n```bash\n{cmd}\n```\n")
        for name in ("landmap", "topomap"):
            if name in m.get("input_hashes", {}):
                hashes[m["input_hashes"][name]] = name
        extras = {k: v for k, v in kw.items() if k not in PARAM_FIELDS and k != "restartfile"}
        common_conf = extras if common_conf is None or common_conf == extras else {}
        nl = m["model_options"].get("namelist_overrides") or {}
        common_nl = nl if common_nl is None or common_nl == nl else {}
    out = ["## 共用配置", ""]
    conf = json.dumps(common_conf or {}, ensure_ascii=False)
    out.append(f"- 额外 `configure` 参数：`{conf}`")
    out.append(f"- 额外 namelist：`{json.dumps(common_nl or {}, ensure_ascii=False)}`")
    out.append("- 轨道一律固定（`fixedorbit`），实际使用值见下表，读自各运行的 `MOST_DIAG`。")
    out.append("- 结果取最后 5 个模式年（60 条月记录）的面积加权平均；趋势为最后两个五年窗口之差。")
    out += ["", "## 运行一览", ""]
    header = ["运行目录", "pCO₂", "模式年", "起步", "偏心率", "倾角", "MVELP（季节相位）",
              "全球 2 m 气温", "趋势", "海冰", "代码版本"]  # fmt: skip
    out.append("| " + " | ".join(header) + " |")
    out.append("|---|---:|---:|---|---:|---:|---|---:|---:|---:|---|")
    out += rows
    out += ["", "## 地表文件哈希", ""]
    for digest, name in sorted(hashes.items(), key=lambda kv: kv[1]):
        path = _find_by_hash(digest)
        out.append(f"- {name}：`{digest}`" + (f"（当前文件 `{path}`）" if path else ""))
    out += ["", "## 复现命令", ""] + cmds
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "runs", nargs="+", help="run directories (those without manifest.json are skipped)"
    )
    ap.add_argument("--out", required=True, help="output Markdown path")
    ap.add_argument(
        "--preamble", help="Markdown file placed before the generated sections (title, scope)"
    )
    args = ap.parse_args(argv)
    runs = [Path(r) for r in args.runs if Path(r).is_dir()]
    head = (
        Path(args.preamble).read_text(encoding="utf-8").rstrip() + "\n\n" if args.preamble else ""
    )
    Path(args.out).write_text(head + render(runs), encoding="utf-8")
    print(f"wrote {args.out} ({len(runs)} run directories)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
