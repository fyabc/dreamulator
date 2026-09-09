"""viz_nbody — REBOUND N 体运动可视化小工具（不接前端，独立脚本）。

三种模式：
  live    REBOUND 内置 WebGL 查看器实时看积分（浏览器打开 http://localhost:PORT）
  dump    定时把全粒子状态转储 npz（回放/诊断数据源）
  replay  读 npz → 静态轨迹图(png) / 动画(gif 或交互窗口) / 诊断时序图(png)

构型直接读 stellar.yaml（= 认证实现，层级根数原样重建），J2 + 潮汐算子与
认证跑同方法学（Lie 分裂，1 yr 块）。坐标系：sim 单位 (yr, AU, Msun)。

用法示例（repo 根目录）：
  uv run python scripts/astro/viz_nbody.py live --t-end 2000 --port 1234
  uv run python scripts/astro/viz_nbody.py dump --t-end 5000 --sample-every 2 \
      --out private/tmp/viz/states.npz
  uv run python scripts/astro/viz_nbody.py replay --npz private/tmp/viz/states.npz \
      --mode static --zoom sat --out private/tmp/viz/orbits_sat.png
  uv run python scripts/astro/viz_nbody.py replay --npz private/tmp/viz/states.npz \
      --mode anim --zoom sat --stride 4 --out private/tmp/viz/orbits.gif
  uv run python scripts/astro/viz_nbody.py replay --npz private/tmp/viz/states.npz \
      --mode diag --out private/tmp/viz/diag.png
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import rebound
from rebound_nbody import (
    _AU_KM,
    _CHAIN,
    _SATS,
    _add_body,
    _apply_j2_secular,
    _apply_tidal_edamp,
    load_system,
)

G_AU3_MSUN_YR2 = 4.0 * np.pi**2

# 视觉配色（与设定表面对应）
COLORS = {
    "star_ignis": "#FF8C00",
    "planet_aegis": "#DAA520",
    "satellite_nacrea": "#2E8B57",
    "satellite_cadence": "#8B4513",  # 托林红褐
    "satellite_vigil": "#708090",    # 处理冰中灰微蓝
}
DEFAULT_COLOR = "#777777"

ZOOMS = {
    # (中心天体, 半宽 km 或 AU, 单位)
    "sat": ("planet_aegis", 3.2e6, "km"),
    "close": ("planet_aegis", 1.0e6, "km"),
    "sys": ("star_ignis", 0.75, "AU"),
}


# ---------------------------------------------------------------- 构建

def build_sim() -> tuple[rebound.Simulation, dict[str, int], dict[str, float]]:
    """从 stellar.yaml 重建认证构型（行星链 + Aegis 三卫），返回 (sim, idx, radii)。"""
    sysdata = load_system()
    bodies = sysdata["bodies"]
    sim = rebound.Simulation()
    sim.units = ("yr", "AU", "Msun")
    sim.integrator = "ias15"
    sim.add(m=sysdata["star_m"])
    idx = {"star": 0}
    for bid in _CHAIN:
        _add_body(sim, bodies[bid])
        idx[bid] = len(sim.particles) - 1
    aegis = sim.particles[idx["planet_aegis"]]
    radii = {}
    for bid in _SATS:
        if bodies.get(bid, {}).get("parent") != "planet_aegis":
            continue  # 只重建 Aegis 卫星（与认证跑一致）
        _add_body(sim, bodies[bid], primary=aegis)
        idx[bid] = len(sim.particles) - 1
        radii[bid] = bodies[bid]["radius_km"] / _AU_KM
    sim.move_to_com()
    return sim, idx, radii


def _ops_ctx(idx: dict[str, int]) -> tuple[dict[str, int], float, tuple[float, float, float]]:
    """算子所需的 (idx 视图, R_A_AU, 赤道法向)。"""
    sysdata = load_system()
    bodies = sysdata["bodies"]
    r_a = bodies["planet_aegis"]["radius_km"] / _AU_KM
    tilt = np.radians(bodies["planet_aegis"]["axial_tilt_deg"])
    eq_n = (0.0, -float(np.sin(tilt)), float(np.cos(tilt)))
    return idx, r_a, eq_n


def _step_ops(sim, idx, r_a, eq_n, radii) -> None:
    _apply_j2_secular(sim, idx, 0.008, r_a, 1.0, eq_n)
    _apply_tidal_edamp(sim, idx, 1.0, 1.0, r_a, radii)


# ---------------------------------------------------------------- live / dump

def _ensure_viewer_html() -> None:
    """REBOUND 服务器要求 CWD 有 rebound.html（WASM 查看器，474 KB，REBOUND 5.1.1 配套）。

    自动安置顺序：CWD 已有 → 库内 vendor 副本（scripts/astro/vendor/，随 git）
    → 兜底 curl 下载（先直连、再本机代理）。服务器内置的自动下载走
    system("curl …")，无代理/离线环境会失败，故在此显式兜底。
    """
    target = Path("rebound.html")
    if target.exists() and target.stat().st_size > 100_000:
        return  # CWD 已有合格副本（小于此体积视为 404 残页等垃圾，覆盖之）
    vendored = Path(__file__).resolve().parent / "vendor" / "rebound.html"
    if vendored.exists():
        import shutil

        shutil.copy(vendored, target)
        print(f"已安置查看器: {vendored.name} → {target.resolve()}")
        return
    import os
    import subprocess

    url = "https://github.com/hannorein/rebound/releases/latest/download/rebound.html"
    for proxy in (None, "http://127.0.0.1:10808"):
        env = dict(os.environ)
        if proxy:
            env["https_proxy"] = proxy
            env["http_proxy"] = proxy
        subprocess.run(["curl", "-L", "-s", "--output", str(target), url],
                       env=env, check=False, timeout=120)
        if target.exists() and target.stat().st_size > 100_000:
            print(f"已下载查看器: {target.resolve()}（proxy={proxy}）")
            return
    target.unlink(missing_ok=True)
    print("警告: rebound.html 获取失败——浏览器将报错；请手动下载后放到当前目录：\n  " + url)


def run_live(args: argparse.Namespace) -> None:
    sim, idx, radii = build_sim()
    _, r_a, eq_n = _ops_ctx(idx)
    _ensure_viewer_html()
    sim.start_server(port=args.port)
    print(f"WebGL 查看器: http://localhost:{args.port}（滚轮缩放：恒星系 → 卫星区）")
    print(f"积分 {args.t_end:.0f} yr（1 yr/块，Ctrl+C 可中断）…", flush=True)
    t = 0.0
    t0 = time.time()
    try:
        while t < args.t_end:
            sim.integrate(t + 1.0)
            t += 1.0
            if not args.no_ops:
                _step_ops(sim, idx, r_a, eq_n, radii)
            if int(t) % 100 == 0:
                print(f"  t={t:.0f} yr ({time.time()-t0:.0f}s)", flush=True)
    except KeyboardInterrupt:
        print(f"\n中断于 t={t:.0f} yr")
    if args.no_hold:
        print("（--no-hold：不等待，查看器随进程退出）")
    else:
        input("积分结束。回车退出（查看器随之关闭）…")


def run_dump(args: argparse.Namespace) -> None:
    sim, idx, radii = build_sim()
    _, r_a, eq_n = _ops_ctx(idx)
    # 粒子索引顺序（star=0 也在转储里，便于 heliocentric 视图）
    order = ["star"] + [b for b in _CHAIN if b in idx] + \
            [b for b in _SATS if b in idx]
    pi = [idx[b] if b != "star" else 0 for b in order]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    n_samples = int(args.t_end // args.sample_every) + 1
    states = np.zeros((n_samples, len(order), 6), dtype=np.float64)
    times = np.zeros(n_samples, dtype=np.float64)
    t = 0.0
    k = 0
    t0 = time.time()

    def _snap() -> None:
        nonlocal k
        times[k] = t
        for j, p in enumerate(pi):
            pa = sim.particles[p]
            states[k, j] = (pa.x, pa.y, pa.z, pa.vx, pa.vy, pa.vz)
        k += 1

    _snap()
    next_sample = args.sample_every
    while t < args.t_end and k < n_samples:
        sim.integrate(t + 1.0)
        t += 1.0
        if not args.no_ops:
            _step_ops(sim, idx, r_a, eq_n, radii)
        if t >= next_sample - 1e-9:
            _snap()
            next_sample += args.sample_every
            if k % 50 == 0:
                print(f"  t={t:.0f} yr, 样本 {k}/{n_samples} ({time.time()-t0:.0f}s)",
                      flush=True)
    masses = np.array([sim.particles[p].m for p in pi])
    np.savez_compressed(out, t=times[:k], states=states[:k], masses=masses,
                        names=np.array(order))
    print(f"转储完成: {out}（{k} 样本 × {len(order)} 天体，"
          f"{out.stat().st_size/1e6:.1f} MB，{time.time()-t0:.0f}s）")


# ---------------------------------------------------------------- replay

def _load(npz_path: str):
    z = np.load(npz_path, allow_pickle=False)
    t = z["t"]
    states = z["states"]
    masses = z["masses"]
    names = [str(n) for n in z["names"]]
    return t, states, masses, names


def _elements(rel: np.ndarray, mu: float) -> tuple[np.ndarray, np.ndarray]:
    """相对状态 (N,6) → (a, e)，两体解析式（AU 单位制）。"""
    r = rel[:, :3]
    v = rel[:, 3:]
    rn = np.linalg.norm(r, axis=1)
    vn = np.linalg.norm(v, axis=1)
    energy = vn**2 / 2.0 - mu / rn
    a = -mu / (2.0 * energy)
    h = np.cross(r, v)
    e_vec = (np.cross(v, h) / mu) - (r.T / rn).T
    e = np.linalg.norm(e_vec, axis=1)
    return a, e


def run_replay(args: argparse.Namespace) -> None:
    import matplotlib

    if args.out:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import animation

    # 中文标题字体（Windows 优先雅黑/黑体；缺字则回退 DejaVu 并容忍警告）
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    t, states, masses, names = _load(args.npz)
    ix = {n: i for i, n in enumerate(names)}
    center_name, half, unit = ZOOMS[args.zoom]
    ci = ix[center_name]
    rel = states[:, :, :3] - states[:, ci, None, :3]  # 中心天体坐标 (N,S,3)
    if unit == "km":
        rel = rel * _AU_KM
        half_disp = half
    else:
        half_disp = half
    show = [n for n in names if n != center_name
            and (unit == "AU" or n.startswith(("satellite", "planet_aegis")))]
    if args.zoom != "sys":
        show = [n for n in names if n != center_name and n != "star"]
        show = [n for n in show if n.startswith(("satellite_nacrea",
                                                 "satellite_cadence",
                                                 "satellite_vigil"))]

    if args.mode == "diag":
        _diag(t, states, masses, names, ix, args, plt)
        return

    gif_out = args.mode == "anim" and args.out and args.out.lower().endswith(".gif")
    fig_kw = {"figsize": (6, 6), "dpi": 90} if gif_out else {"figsize": (8, 8), "dpi": 110}
    fig, ax = plt.subplots(**fig_kw)
    ax.set_aspect("equal")
    ax.set_xlim(-half_disp, half_disp)
    ax.set_ylim(-half_disp, half_disp)
    ax.set_xlabel(f"x [{unit}]")
    ax.set_ylabel(f"y [{unit}]")
    ttl = ax.set_title("")
    ax.plot([0], [0], "o", ms=8, color=COLORS.get(center_name, DEFAULT_COLOR))
    ax.text(0, 0, f" {center_name.split('_', 1)[-1]}", fontsize=8, va="bottom")
    trails, dots = {}, {}
    for n in show:
        c = COLORS.get(n, DEFAULT_COLOR)
        j = ix[n]
        (tr,) = ax.plot(rel[:, j, 0], rel[:, j, 1], "-", lw=0.4, color=c, alpha=0.35)
        (d,) = ax.plot([], [], "o", ms=4, color=c)
        trails[n], dots[n] = tr, d

    if args.mode == "static":
        ttl.set_text(f"{args.npz}  zoom={args.zoom}  Δt={t[-1]:.0f} yr（细线=全程轨迹）")
        _save_or_show(fig, args, plt)
        return

    # anim：全程轨迹常显（细线）+ 当前位置亮点
    frames = list(range(0, len(t), max(1, args.stride)))

    def update(fi: int):
        artists = []
        for n in show:
            j = ix[n]
            dots[n].set_data([rel[fi, j, 0]], [rel[fi, j, 1]])
            artists.append(dots[n])
        ttl.set_text(f"t = {t[fi]:,.0f} yr   zoom={args.zoom}")
        return artists + [ttl]

    ani = animation.FuncAnimation(fig, update, frames=frames, blit=False)
    if args.out:
        ani.save(args.out, writer=animation.PillowWriter(fps=args.fps))
        print(f"动画已保存: {args.out}（{len(frames)} 帧 @{args.fps} fps）")
    else:
        plt.show()


def _diag(t, states, masses, names, ix, args, plt) -> None:
    """诊断时序：三卫 e(t) + 守珠-韵珠径向净空（X8 死法复盘视图）。"""
    ai = ix["planet_aegis"]
    mu_of = {}
    for n in ("satellite_nacrea", "satellite_cadence", "satellite_vigil"):
        mu_of[n] = G_AU3_MSUN_YR2 * (masses[ai] + masses[ix[n]])
    fig, axes = plt.subplots(2, 2, figsize=(13, 8), dpi=110, sharex=True)
    series = {}
    for k, n in enumerate(mu_of):
        j = ix[n]
        rel = states[:, j, :] - states[:, ai, :]
        a, e = _elements(rel, mu_of[n])
        series[n] = (a, e)
        ax = axes[k // 2][k % 2]
        ax.plot(t / 1000.0, e, lw=0.7, color=COLORS.get(n))
        ax.set_ylabel("e")
        ax.set_title(n.replace("satellite_", ""), fontsize=10)
        ax.grid(alpha=0.3)
    # 净空面板
    a_c, e_c = series["satellite_cadence"]
    a_v, e_v = series["satellite_vigil"]
    clear = (a_v * (1 - e_v) - a_c * (1 + e_c)) * _AU_KM
    ax = axes[1][1]
    ax.plot(t / 1000.0, clear, lw=0.7, color="#444444")
    ax.axhline(0, color="red", lw=1.0, ls="--")
    ax.set_ylabel("V近点 − C远点 [km]")
    ax.set_title("径向净空（<0 = 轨道交叉）", fontsize=10)
    ax.grid(alpha=0.3)
    for ax in axes[1]:
        ax.set_xlabel("t [kyr]")
    fig.suptitle(f"诊断时序 — {args.npz}", fontsize=11)
    fig.tight_layout()
    _save_or_show(fig, args, plt)


def _save_or_show(fig, args, plt) -> None:
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(args.out, bbox_inches="tight")
        print(f"已保存: {args.out}")
    else:
        plt.show()


# ---------------------------------------------------------------- CLI

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("live", help="REBOUND 内置 WebGL 实时查看")
    pl.add_argument("--t-end", type=float, default=2000.0)
    pl.add_argument("--port", type=int, default=1234)
    pl.add_argument("--no-ops", action="store_true", help="关闭 J2/潮汐算子（纯引力）")
    pl.add_argument("--no-hold", action="store_true", help="积分结束不等待回车（无头测试用）")

    pd = sub.add_parser("dump", help="状态转储 npz")
    pd.add_argument("--t-end", type=float, default=5000.0)
    pd.add_argument("--sample-every", type=float, default=5.0, help="采样间隔 [yr]")
    pd.add_argument("--out", required=True)
    pd.add_argument("--no-ops", action="store_true")

    pr = sub.add_parser("replay", help="回放/诊断出图")
    pr.add_argument("--npz", required=True)
    pr.add_argument("--mode", choices=("static", "anim", "diag"), default="static")
    pr.add_argument("--zoom", choices=tuple(ZOOMS), default="sat")
    pr.add_argument("--stride", type=int, default=4, help="anim 抽帧步长")
    pr.add_argument("--fps", type=int, default=25)
    pr.add_argument("--out", default=None, help="缺省=交互窗口")

    args = p.parse_args()
    if args.cmd == "live":
        run_live(args)
    elif args.cmd == "dump":
        run_dump(args)
    else:
        run_replay(args)


if __name__ == "__main__":
    main()
