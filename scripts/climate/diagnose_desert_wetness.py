#!/usr/bin/env python3
"""§5 沙漠过湿归因 + SST 对流门标定（2026-09-13 诊断轮，Stage C 方法论）。

两种模式：

**默认（存档模式，秒级）** — 读 earth/climate-dev 归档产物 + `climate_obs.json`：

1. **f(ΔSST) 经验抑制曲线**（§5-α 对流门标定）：海洋格
   e_rel = P_obs/纬向带均值(GPCP) vs ΔSST = SST − 纬向带均 SST（5° 带、面积加权）。
   物理：WTG（Sobel et al. 2001，热带自由对流层温度水平均匀）→ 海洋对流不
   稳定度由局地 SST 相对纬向均值的距平决定；SST 对流阈值族（Johnson & Xie
   2010，~27.5 °C 且随区域变化）；冷洋流海岸雾沙漠（Garreaud et al. 2002
   海岸低族；Xie & Philander 1994 冷舌-ITCZ 耦合）。
   实测结点：热带 e_rel 0.94@ΔSST=0 → 0.84@−1 → 0.60@−2；外热带
   1.00@0 → 0.82@−3 → 0.65@−5 → 0.24@−7（热带敏感得多 = WTG 预期）。
2. **模型 ΔSST 结构核查**：`sst_anomaly_c` std 0.17 °C、极值 ±1.4（南极冰缘），
   索马里上升流/加拉帕戈斯/秘鲁/加那利/本格拉各洋流盒 |ΔSST| < 0.3，热带 SST
   顶在 28.0 暖池上限——真实寒流距平 −4~−8 °C。**结论：ΔSST 门在现状下无输入
   可触发（空转），§5-α 实施被 §4 洋流/SST 结构阻塞。**

**--ablation（消融模式，~15 min，引擎重跑 ×3）** — A 基线 / B 季风异常关 /
C κ 扩散关，逐盒归因。2026-09-13 结论：

- 内陆沙漠过湿**过决定**（多通道供给）：撒哈拉腹地 B/A 0.54（季风热低压平流
  ~46%）、C/A 0.41（κ ~59%）、Budyko 再循环 ET 248 mm（ET/E_pot 0.21）；澳洲
  沙漠 B/A 0.36（季风 64%）；无季风时撒哈拉仍 308（obs 27）。
- **纬向对称杠杆决定性证伪**：恒河 κ 依赖 78%（C/A 0.22）、华南 65%，均高于
  撒哈拉（59%）；季风占恒河 49%。任何纬向 κ 削减 / k_rain 帽 / W 帽打验收
  （恒河 −650、华南 −1236 已偏干）比打沙漠更狠——与 Stage C 的 `_dt_subsidence`
  纬向对称证伪同墙。RH 判据同轮证伪（模型 T 被 P 偏差反向污染：7 月撒哈拉
  30.5 °C < 恒河 34.9 °C，与实况倒置 → RH 门方向打反）。
- **F 线（水分路由）新锚点**：西高止季风贡献 ≈0（B/A 1.02）+ 阿拉伯海海上
  降水 795 vs obs 356（水汽在到岸前海上雨出）+ 几内亚湾去季风反而更湿
  （1410→2468，B/A 1.75）= 西非水分被撒哈拉热低压（B2 揭蔽、ΔP 5× 过深）
  错误北抽。
- **B 族（赤道干带：加拉帕戈斯 +2611/索马里 +957/东太平冷舌）对季风与 κ 均
  不敏感**（B/A ≥ 1.06、冷舌 C/A 1.07）= 纯背景辐合 + 均匀暖 SST → 归 §4
  （SST 距平结构死亡）+ §5-α（门曲线已标定待实施）。
- 内陆/暖岸族（A3+A1：撒哈拉腹地、澳洲、卡拉哈里、波斯湾、红海）根治 =
  ④ 副热带反气旋的经度结构：Rodwell & Hoskins 2001（季风加热 → 西侧 Rossby
  下沉 = 沙漠与季风是同一枚硬币两面）、Gill 1980 线性斜压响应 = 轻量候选
  实现路径（从模型自身加热场算定常波响应，负反馈自正则）。

Usage::

    uv run python scripts/climate/diagnose_desert_wetness.py
    uv run python scripts/climate/diagnose_desert_wetness.py --ablation
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

import numpy as np


def _find_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


# (name, lat0, lat1, lon0, lon1) — hot-desert wet-bias family + controls.
_BOXES = [
    ("撒哈拉腹地", 20, 28, 5, 25),
    ("萨赫勒", 12, 16, 0, 20),
    ("撒哈拉西洋岸", 20, 27, -17, -12),
    ("澳洲大沙漠", -26, -20, 125, 135),
    ("卡拉哈里", -24, -19, 20, 26),
    ("纳米布", -24, -17, 12, 16),
    ("阿塔卡马", -27, -20, -71, -68),
    ("波斯湾沿岸", 22, 30, 45, 57),
    ("红海西岸", 18, 26, 35, 43),
    ("索马里", 5, 11, 43, 51),
    ("恒河平原", 25, 29, 80, 87),
    ("西高止", 12, 18, 73, 77),
    ("华南", 22, 28, 108, 118),
    ("刚果盆地", -4, 2, 16, 26),
    ("加拉帕戈斯洋", -1, 1, -92, -88),
    ("东太平冷舌", -2, 0, -140, -135),
    ("西太暖池", 0, 5, 140, 150),
    ("阿拉伯海", 10, 15, 55, 65),
    ("索马里洋上升流", -2, 4, 42, 48),
    ("几内亚湾", 0, 5, -5, 5),
]

# Ocean-current boxes for the ΔSST structure check.
_CURRENT_BOXES = [
    ("索马里上升流", -2, 4, 42, 50),
    ("加拉帕戈斯", -2, 1, -92, -87),
    ("秘鲁寒流", -20, -8, -80, -72),
    ("加那利寒流", 20, 28, -20, -14),
    ("本格拉寒流", -25, -15, 10, 16),
    ("几内亚湾暖水", 0, 6, -4, 4),
    ("西太暖池", 0, 6, 140, 152),
    ("阿拉伯海", 10, 16, 56, 66),
    ("孟加拉湾", 8, 15, 85, 93),
    ("南海", 8, 16, 110, 118),
    ("黑潮", 28, 34, 125, 135),
    ("湾流", 32, 38, -70, -60),
]


def _load_archive(map_dir: Path) -> dict[str, np.ndarray]:
    """Fast raw-JSON mesh load (no pydantic) + per-cell GPCP/NCEP obs."""
    from dreamulator.map.export import find_mesh_file, load_cvt_mesh

    mesh_path = find_mesh_file(map_dir)
    if mesh_path is None:
        raise FileNotFoundError(f"no mesh file under {map_dir}")
    mesh = load_cvt_mesh(mesh_path)
    cells = mesh["cells"]

    def _f(key: str) -> np.ndarray:
        return np.array([np.nan if c.get(key) is None else c[key] for c in cells], dtype=np.float64)

    out = {
        "lat": np.array([c["lat"] for c in cells]),
        "lon": np.array([c["lon"] for c in cells]),
        "elev": np.array([c["elevation"] for c in cells]),
        "area": np.array([c["area_km2"] for c in cells]),
        "sst": _f("temperature_C"),  # ocean cells: SST (Stage 2.5 override)
        "sst_anom": _f("sst_anomaly_c"),
    }
    with open(map_dir / "climate_obs.json", encoding="utf-8") as f:
        obs = json.load(f)
    p_obs = np.full(len(cells), np.nan)
    for cid, v in obs["cells"].items():
        if "p_obs_mm" in v:
            p_obs[int(cid)] = v["p_obs_mm"]
    out["p_obs"] = p_obs
    return out


def _zonal_mean(
    vals: np.ndarray, weight: np.ndarray, mask: np.ndarray, band: np.ndarray, nb: int
) -> np.ndarray:
    num = np.bincount(band[mask], weights=(vals * weight)[mask], minlength=nb)
    den = np.bincount(band[mask], weights=weight[mask], minlength=nb)
    return (num / np.maximum(den, 1e-12))[band]


def run_archive_mode(map_dir: Path) -> None:
    a = _load_archive(map_dir)
    lat, area, sst, p_obs = a["lat"], a["area"], a["sst"], a["p_obs"]
    is_ocean = a["elev"] < 0.0

    band = np.floor((lat + 2.5) / 5.0).astype(int)
    band -= band.min()
    nb = int(band.max()) + 1

    m = is_ocean & np.isfinite(sst) & np.isfinite(p_obs)
    sst_zm = _zonal_mean(sst, area, is_ocean & np.isfinite(sst), band, nb)
    p_zm = _zonal_mean(p_obs, area, m, band, nb)
    d_sst = sst - sst_zm
    e_rel = p_obs / np.maximum(p_zm, 1e-9)

    print(f"ocean cells with obs: {m.sum()} / {int(is_ocean.sum())}")
    print(f"model SST range: {np.nanmin(sst[m]):.1f} .. {np.nanmax(sst[m]):.1f} C")
    print(f"model dSST range: {np.nanmin(d_sst[m]):.2f} .. {np.nanmax(d_sst[m]):.2f} C")

    anom = a["sst_anom"]
    oc_anom = anom[is_ocean & np.isfinite(anom)]
    print(
        f"\nsst_anomaly_c (archived, ocean): std {oc_anom.std():.2f} C, "
        f"min {oc_anom.min():.2f}, max {oc_anom.max():.2f}"
    )
    print("  (real current-driven anomalies are +-3..8 C — the Stommel->SST chain")
    print("   is ~20-40x too weak at 200k; the gate below has no input to fire on.)")

    print("\n== e_rel (obs P / zonal-mean obs P) by dSST bin [ocean, GPCP] ==")
    print(f"{'dSST bin':>10}{'n':>8}{'med':>7}{'p25':>7}{'p75':>7}")
    for lo in np.arange(-8, 5.01, 1.0):
        sel = m & (d_sst >= lo) & (d_sst < lo + 1)
        if sel.sum() < 30:
            continue
        e = e_rel[sel]
        print(
            f"{lo:>4.0f}..{lo + 1:<4.0f}{sel.sum():>8}{np.median(e):>7.2f}"
            f"{np.percentile(e, 25):>7.2f}{np.percentile(e, 75):>7.2f}"
        )

    print("\n== same, split |lat| <= 25 (WTG tropics) / > 25 ==")
    for lab, extra in (("tropics", np.abs(lat) <= 25), ("extratrop", np.abs(lat) > 25)):
        row = []
        for lo in range(-8, 4):
            sel = m & extra & (d_sst >= lo) & (d_sst < lo + 1)
            row.append(f"{lo:+d}:{np.median(e_rel[sel]):.2f}" if sel.sum() >= 30 else f"{lo:+d}:--")
        print(f"  {lab:>9}: " + "  ".join(row))

    print("\n== ocean-current boxes: model SST / zonal mean / dSST / obs P ==")
    print(f"{'box':<14}{'n':>6}{'SST':>7}{'SST_zm':>8}{'dSST':>7}{'obsP':>7}{'e_rel':>7}")
    for name, la0, la1, lo0, lo1 in _CURRENT_BOXES:
        sel = m & (lat >= la0) & (lat <= la1) & (a["lon"] >= lo0) & (a["lon"] <= lo1)
        if sel.sum() == 0:
            print(f"{name:<14} EMPTY")
            continue
        print(
            f"{name:<14}{sel.sum():>6}{np.nanmean(sst[sel]):>7.1f}"
            f"{np.nanmean(sst_zm[sel]):>8.1f}{np.nanmean(d_sst[sel]):>+7.2f}"
            f"{np.nanmean(p_obs[sel]):>7.0f}{np.nanmedian(e_rel[sel]):>7.2f}"
        )


def run_wave_gate_calibration(map_dir: Path) -> None:
    """④ v2 下沉干燥门标定：e_rel（GPCP 陆格 P / 陆地带均值）vs 模型 w_mid 分 bin。

    波动求解是 pass-1 场的纯函数，而 pass-1 产物 = flag-off 构建存档
    （t/p/wind 月场，climate_monthly.msgpack，int16×scale/offset）——无需重跑
    引擎。结点自变量 = 年均（+7 月对照）下沉速度 w<0（m/s）；e_rel 在 w≈0 bin
    归一（同 §5-α 纪律：零距平基线不动）。月份约定 month_0 = 春分 → 7 月 =
    索引 4。
    """
    import msgpack

    from dreamulator.map.stationary_wave_two_level import compute_omega_wave_anomaly

    a = _load_archive(map_dir)
    with open(map_dir / "climate_monthly.msgpack", "rb") as f:
        d = msgpack.unpack(f)

    def _monthly(prefix: str) -> np.ndarray:
        raw = np.frombuffer(d[f"{prefix}_monthly"], dtype=np.int16).reshape(
            d["num_cells"], d["months"]
        )
        return raw.astype(np.float64) * d[f"{prefix}_scale"] + d[f"{prefix}_offset"]

    sol = compute_omega_wave_anomaly(
        p_monthly_mm=_monthly("p"),
        t_monthly_c=_monthly("t"),
        elevation_m=a["elev"],
        cell_lat_deg=a["lat"],
        cell_lon_deg=a["lon"],
        cell_area_km2=a["area"],
        wind_east_monthly=_monthly("wind_east"),
        wind_north_monthly=_monthly("wind_north"),
        surface_pressure_hpa=1013.25,
        rotation_period_days=1.0,
        radius_km=6371.0,
        orbital_period_days=365.25,
    )
    w = sol.w_mid_m_s  # (n, 12)，>0 上升
    lat, area, p_obs = a["lat"], a["area"], a["p_obs"]
    is_land = a["elev"] >= 0.0

    band = np.floor((lat + 2.5) / 5.0).astype(int)
    band -= band.min()
    nb = int(band.max()) + 1
    m = is_land & np.isfinite(p_obs) & np.isfinite(w.mean(axis=1))
    p_zm = _zonal_mean(p_obs, area, m, band, nb)
    e_rel = p_obs / np.maximum(p_zm, 1e-9)

    w_ann = w.mean(axis=1)
    w_jul = w[:, 4]  # month_0 = vernal equinox → July = index 4
    print(f"land cells with obs: {m.sum()} / {int(is_land.sum())}")
    print(
        f"w_mid annual: min {w_ann[m].min():.2e} max {w_ann[m].max():.2e} m/s; "
        f"subsidence share {float((w_ann[m] < 0).mean()) * 100:.0f}%"
    )
    print(f"w_mid July:   min {w_jul[m].min():.2e} max {w_jul[m].max():.2e} m/s")

    for label, wf in (("annual", w_ann), ("July", w_jul)):
        print(f"\n== e_rel (obs P / zonal-mean obs P) by w_mid bin [land, GPCP, {label}] ==")
        print(f"{'w bin (m/s)':>18}{'n':>8}{'med':>7}{'p25':>7}{'p75':>7}")
        edges = [-4e-3, -2e-3, -1e-3, -5e-4, -2e-4, -1e-4, -5e-5, -1e-5, 0.0, 1e-5, 1e-4]
        for lo, hi in zip(edges[:-1], edges[1:], strict=False):
            sel = m & (wf >= lo) & (wf < hi)
            if sel.sum() < 30:
                print(f"{lo:>9.1e}..{hi:<7.1e}{sel.sum():>8}   --")
                continue
            e = e_rel[sel]
            print(
                f"{lo:>9.1e}..{hi:<7.1e}{sel.sum():>8}{np.median(e):>7.2f}"
                f"{np.percentile(e, 25):>7.2f}{np.percentile(e, 75):>7.2f}"
            )
        up = m & (wf >= 1e-4)
        if up.sum() >= 30:
            print(f"{'ascent>1e-4':>18}{up.sum():>8}{np.median(e_rel[up]):>7.2f}")

    print("\n== desert/monsoon boxes: model w_mid (annual / July) + obs e_rel ==")
    print(f"{'box':<14}{'n':>6}{'w_ann':>10}{'w_jul':>10}{'e_rel':>7}")
    for name, la0, la1, lo0, lo1 in _BOXES:
        sel = m & (lat >= la0) & (lat <= la1) & (a["lon"] >= lo0) & (a["lon"] <= lo1)
        if sel.sum() == 0:
            print(f"{name:<14} EMPTY")
            continue
        print(
            f"{name:<14}{sel.sum():>6}{np.nanmean(w_ann[sel]):>+10.2e}"
            f"{np.nanmean(w_jul[sel]):>+10.2e}{np.nanmedian(e_rel[sel]):>7.2f}"
        )


def run_ablation(world_dir: Path) -> None:
    """3 engine re-runs: baseline / monsoon-anomaly off / kappa off."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from diagnose_precip_budget import _load_mesh

    from dreamulator.map.climate_config import load_climate_config

    cases = (("A基线", ""), ("B无季风", "no_monsoon"), ("C无κ扩散", "no_kappa"))
    results: dict[str, dict] = {}
    for label, patch in cases:
        mesh = _load_mesh(world_dir, "planet_earth", "climate-dev")
        cfg = load_climate_config(world_dir, "earth", "planet_earth", "climate-dev", mesh.num_cells)
        import dreamulator.map.climate_simulator as cs

        orig = None
        if patch == "no_monsoon":
            orig = cs.monsoon_boundary_layer_wind
            cs.monsoon_boundary_layer_wind = lambda *args, _n=mesh.num_cells, **kw: np.zeros(
                (12, _n, 3)
            )
        elif patch == "no_kappa":
            cfg.moisture_diffusivity_m2s = 0.0

        debug: dict[str, np.ndarray] = {}
        cs.simulate_climate(mesh, cfg, debug=debug)
        if orig is not None:
            cs.monsoon_boundary_layer_wind = orig

        lat = np.array([c.lat for c in mesh.cells])
        lon = np.array([c.lon for c in mesh.cells])
        elev = np.array([c.elevation for c in mesh.cells])
        final, et, epot = debug["final"], debug.get("land_et"), debug.get("land_epot")
        rec: dict[str, dict] = {}
        for name, la0, la1, lo0, lo1 in _BOXES:
            sel = (lat >= la0) & (lat <= la1) & (lon >= lo0) & (lon <= lo1)
            land = sel & (elev >= 0.0)
            use = land if land.sum() > 0 else sel
            entry = {"P": float(final[use].mean())}
            if land.sum() > 0 and et is not None and epot is not None:
                entry["ET"] = float(et[land].mean())
                entry["ETpot"] = float(epot[land].mean())
            rec[name] = entry
        results[label] = rec
        print(f"[{label}] done", flush=True)

    print("\n== box annual P (mm) by ablation ==")
    print(f"{'box':<14}{'A':>8}{'B无季风':>9}{'C无κ':>8}{'B/A':>7}{'C/A':>7}{'ET':>7}{'ET/pot':>8}")
    for name, *_ in _BOXES:
        ra = results["A基线"][name]
        rb = results["B无季风"][name]
        rc = results["C无κ扩散"][name]
        pa = max(ra["P"], 1e-9)
        et_s = f"{ra.get('ET', float('nan')):>7.0f}" if "ET" in ra else "      -"
        r_s = f"{ra['ET'] / max(ra['ETpot'], 1e-9):>8.2f}" if "ET" in ra else "       -"
        print(
            f"{name:<14}{ra['P']:>8.0f}{rb['P']:>9.0f}{rc['P']:>8.0f}"
            f"{rb['P'] / pa:>7.2f}{rc['P'] / pa:>7.2f}{et_s}{r_s}"
        )


def run_pickup_gate_calibration(world_dir: Path) -> None:
    """§5-β 对流临界雨出门标定：x = W₀/W_sat 分箱 vs 观测（一次 flag-off 引擎重跑）。

    门的输入是水分收支 pass-1 的柱水汽 W₀（flag-off 构建即可取得——debug 键
    ``w_column_annual`` 无条件落盘）。对每个 x 分箱（陆/洋分列）输出：格数、
    W₀ 与模型 P 的中位数、观测 P 的中位数、两者的比值，以及 f_τ = 9d/τ_obs
    （τ_obs = W₀/(P_obs/365.25)）。f_τ 是「所需门因子」的保守上界：门压制后
    水汽会再平衡（干区 W 升高），所以实际所需压制比 f_τ 浅。

    已知局限（诚实登记）：单条 monotone 曲线分不开同 x 不同命运的格子——
    萨赫勒（x≈0.26，观测比模型湿）与撒哈拉（x≈0.19，观测比模型干 10 倍）几乎
    同档；孟加拉湾（x≈0.54）需要增强而非压制。这些格子的补偿来自自释放回路
    （过境洋面少漏、下游基过临界），不来自结点本身。结点骨架按物理形态定
    （Neelin-Peters-Hales 2009 抬升 + 陆地临界偏低），数据只微调中部斜率。
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from diagnose_precip_budget import _load_mesh

    import dreamulator.map.climate_simulator as cs
    from dreamulator.engine.climate_physics import (
        column_water_saturation,
        convective_pickup_gate,
    )
    from dreamulator.map.climate_config import load_climate_config

    mesh = _load_mesh(world_dir, "planet_earth", "climate-dev")
    cfg = load_climate_config(world_dir, "earth", "planet_earth", "climate-dev", mesh.num_cells)
    debug: dict[str, np.ndarray] = {}
    cs.simulate_climate(mesh, cfg, debug=debug)

    lat = np.array([c.lat for c in mesh.cells])
    lon = np.array([c.lon for c in mesh.cells])
    elev = np.array([c.elevation for c in mesh.cells])
    t_mean = np.array([c.temperature_C for c in mesh.cells])
    is_land = elev >= 0.0
    w0 = debug["w_column_annual"]
    p_mod = debug["final"]
    with open(
        world_dir / "branches" / "climate-dev" / "maps" / "planet_earth" / "climate_obs.json",
        encoding="utf-8",
    ) as f:
        obs = json.load(f)
    p_obs = np.full(len(lat), np.nan)
    for cid, v in obs["cells"].items():
        if "p_obs_mm" in v:
            p_obs[int(cid)] = v["p_obs_mm"]

    w_sat = column_water_saturation(t_mean)
    x = np.clip(w0 / np.maximum(w_sat, 0.5), 0.0, 1.0)
    f_cur = convective_pickup_gate(w0, t_mean)
    tau_obs = w0 / np.maximum(p_obs, 1e-9) * 365.25  # days
    f_tau = 9.0 / np.maximum(tau_obs, 1e-9)

    print(f"cells: {len(lat)} (land {int(is_land.sum())}); x range {x.min():.2f}..{x.max():.2f}")
    for label, mask in (("LAND", is_land), ("OCEAN", ~is_land)):
        print(f"\n== {label}: x-bin table (n≥30) ==")
        print(
            f"{'x bin':>12}{'n':>7}{'medW0':>7}{'medPmod':>8}{'medPobs':>8}"
            f"{'obs:mod':>8}{'f_tau':>7}"
        )
        for lo in np.arange(0.0, 1.0, 0.05):
            m = mask & (x >= lo) & (x < lo + 0.05) & np.isfinite(p_obs)
            if m.sum() < 30:
                continue
            print(
                f"{lo:>5.2f}-{lo + 0.05:<5.2f}{m.sum():>7}{np.median(w0[m]):>7.1f}"
                f"{np.median(p_mod[m]):>8.0f}{np.median(p_obs[m]):>8.0f}"
                f"{np.median(p_obs[m]) / max(np.median(p_mod[m]), 1e-9):>8.2f}"
                f"{np.median(f_tau[m]):>7.2f}"
            )

    print("\n== knot draft: median f_tau in ±0.05 windows at the knot x positions ==")
    for kx in (0.20, 0.35, 0.50, 0.65, 0.80):
        m = (np.abs(x - kx) <= 0.05) & np.isfinite(p_obs)
        tag = "all"
        if m.sum() >= 30:
            print(f"  x={kx:.2f} [{tag}]: f_tau med {np.median(f_tau[m]):.2f} (n={int(m.sum())})")
        else:
            print(f"  x={kx:.2f} [{tag}]: n={int(m.sum())} too few")

    print("\n== boxes: x / current-knot f / f_tau ==")
    print(f"{'box':<14}{'n':>6}{'x':>6}{'f_cur':>7}{'f_tau':>7}")
    for name, la0, la1, lo0, lo1 in _BOXES:
        m = (lat >= la0) & (lat <= la1) & (lon >= lo0) & (lon <= lo1) & np.isfinite(p_obs)
        if m.sum() == 0:
            print(f"{name:<14} EMPTY")
            continue
        print(
            f"{name:<14}{m.sum():>6}{np.nanmean(x[m]):>6.2f}"
            f"{np.nanmean(f_cur[m]):>7.2f}{np.nanmedian(f_tau[m]):>7.2f}"
        )


def main() -> None:
    root = _find_project_root()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--ablation",
        action="store_true",
        help="run the 3-case engine ablation (~15 min) instead of archive mode",
    )
    ap.add_argument(
        "--wave-gate",
        action="store_true",
        help="calibrate the ④ v2 subsidence-drying gate (archive-based, ~1 min)",
    )
    ap.add_argument(
        "--pickup-gate",
        action="store_true",
        help="calibrate the §5-β convective pickup gate (one engine re-run, ~4 min)",
    )
    ap.add_argument("--world", default="earth")
    ap.add_argument("--branch", default="climate-dev")
    ap.add_argument("--world-dir", default=str(root / "data" / "worlds"))
    args = ap.parse_args()
    world_dir = Path(args.world_dir) / args.world
    if args.ablation:
        run_ablation(world_dir)
    elif args.pickup_gate:
        run_pickup_gate_calibration(world_dir)
    elif args.wave_gate:
        map_dir = (
            world_dir / "branches" / args.branch / "maps" / f"planet_{args.world}"
            if args.branch
            else world_dir / "maps" / f"planet_{args.world}"
        )
        run_wave_gate_calibration(map_dir)
    else:
        map_dir = (
            world_dir / "branches" / args.branch / "maps" / f"planet_{args.world}"
            if args.branch
            else world_dir / "maps" / f"planet_{args.world}"
        )
        run_archive_mode(map_dir)


if __name__ == "__main__":
    main()
