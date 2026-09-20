#!/usr/bin/env python3
"""Generate the Nacrea UCC migration-fixture document (UCC-01 第四步 4b/4c).

Applies the current UCC profile (already exported per-cell in the world's
``climate_yearly.msgpack`` by ``export_climate_layers``) to Nacrea and records:

- the global class distribution + modifier/status tallies + descriptor quantiles;
- 预期 vs 实际 (the plan-time migration expectations, judged honestly — reality
  differences are the point of a fixture, not something to hide);
- representative sites at named geography anchors (geography.yaml) with monthly
  series → descriptors → classification;
- extreme cells (driest/wettest/coldest/warmest/most seasonal).

The document is the migration-semantics fixture: thresholds are globally shared
(never per-world quantiles), so a slow-rotating short-year world must produce
semantically correct — not earth-like — labels.  Future profile/engine/config
changes that move these tables are conscious deltas to accept or investigate.

Output: ``data/worlds/nacrea/design-notes/0010-ucc-migration-fixture.md``
(regenerate, don't hand-edit).

Usage:
    uv run python scripts/climate/ucc_examples_nacrea.py
    uv run python scripts/climate/ucc_examples_nacrea.py --map-dir <maps dir> --out <path>
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from collections import Counter
from pathlib import Path

import msgpack
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from dreamulator.map.export import decompress_mesh_bytes  # noqa: E402
from dreamulator.map.ucc import status_short  # noqa: E402

_DEFAULT_MAP = Path("data/worlds/nacrea/maps/satellite_nacrea")
_DEFAULT_OUT = Path("data/worlds/nacrea/design-notes/0010-ucc-migration-fixture.md")

# Representative sites: (name, lat, lon, want) — anchors from geography.yaml
# (named continents/oceans/features).  ``want`` forces the nearest cell of that
# water class so an ocean anchor doesn't snap to a coastline cell.
SITES: list[tuple[str, float, float, str]] = [
    ("Aegis深渊洋·向星点", 0.0, 0.0, "ocean"),
    ("永耀岛（热点火山岛）", -0.8, 0.5, "land"),
    ("虚空洋·背星点", 0.0, 180.0, "ocean"),
    ("世界岛·中西部", -10.0, -100.0, "land"),
    ("世界岛·东部内陆", -12.0, -60.0, "land"),
    ("世界岛·北部", 28.0, -88.0, "land"),
    ("大裂谷海·中段", -3.0, -91.5, "ocean"),
    ("北极大陆", 86.0, 150.0, "land"),
    ("前导点褶皱山系", -2.5, 94.0, "land"),
    ("南方大陆1", -35.0, 120.0, "land"),
    ("南方大陆2", -40.0, -35.0, "land"),
    ("南大洋·90E", -39.0, 90.0, "ocean"),
    ("南极浅海", -85.0, 0.0, "ocean"),
]


def _unit(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    la, lo = np.radians(lat), np.radians(lon)
    return np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], axis=1)


def _nearest(lat: float, lon: float, pts: np.ndarray, mask: np.ndarray | None = None) -> int:
    v = _unit(np.array([lat]), np.array([lon]))[0]
    dots = pts @ v
    if mask is not None:
        dots = np.where(mask, dots, -2.0)
    return int(np.argmax(dots))


def _load_monthly(path: Path) -> tuple[np.ndarray, np.ndarray]:
    with path.open("rb") as f:
        d = msgpack.unpackb(f.read())
    n, m = d["num_cells"], d["months"]

    def deq(name: str) -> np.ndarray:
        q = np.frombuffer(d[name], dtype=np.int16).astype(np.float64)
        return (
            q.reshape(n, m) * d[name.removesuffix("_monthly") + "_scale"]
            + d[name.removesuffix("_monthly") + "_offset"]
        )

    return deq("t_monthly"), deq("p_monthly")


def _f32(d: dict, key: str) -> np.ndarray:
    return np.frombuffer(d[key], dtype=np.float32).astype(np.float64)


def _u8(d: dict, key: str) -> np.ndarray:
    return np.frombuffer(d[key], dtype=np.uint8)


def _fmt(v: float | None, prec: int = 2) -> str:
    return "—" if v is None or (isinstance(v, float) and not np.isfinite(v)) else f"{v:.{prec}f}"


_THERMAL_LETTERS = {"polar": "P", "cold": "C", "temperate": "T", "tropical": "R"}
_SUPPLY_LETTERS = {"arid": "a", "semi_arid": "s", "transitional": "t", "humid": "h"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map-dir", type=Path, default=_DEFAULT_MAP)
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    args = parser.parse_args()
    map_dir = args.map_dir

    print(f"Reading climate_yearly.msgpack from {map_dir} …")
    with (map_dir / "climate_yearly.msgpack").open("rb") as f:
        y = msgpack.unpackb(f.read())
    n = int(y["num_cells"])
    profile = str(y["profile"])
    thermal_bands = list(y["thermal_bands"])
    supply_bands = list(y["supply_bands"])
    status_codes = list(y["status_codes"])

    print("Reading climate_monthly.msgpack …")
    t_monthly, p_monthly = _load_monthly(map_dir / "climate_monthly.msgpack")

    print("Reading mesh (lat/lon/water_class/elevation) — full JSON parse, ~1 min …")
    mesh = json.loads(decompress_mesh_bytes((map_dir / "cvt_mesh.json").read_bytes()))
    cells = mesh["cells"]
    lat = np.array([c["lat"] for c in cells], dtype=np.float64)
    lon = np.array([c["lon"] for c in cells], dtype=np.float64)
    elev = np.array([c.get("elevation", 0.0) for c in cells], dtype=np.float64)
    water = np.array([c.get("water_class") or "" for c in cells], dtype=str)
    land = water == "land"
    assert len(lat) == n, "mesh/yearly cell-count mismatch"
    pts = _unit(lat, lon)

    # Decode yearly arrays.
    ai = _f32(y, "ai")
    ai_status = _u8(y, "ai_status")
    deficit = _f32(y, "deficit")
    deficit_status = _u8(y, "deficit_status")
    t_mean = _f32(y, "t_mean_c")
    t_min = _f32(y, "t_min_c")
    t_max = _f32(y, "t_max_c")
    t_range = _f32(y, "t_range_c")
    t_below = _f32(y, "t_below_frac")
    p_total = _f32(y, "p_total_mm")
    conc = _f32(y, "concentration")
    th = _u8(y, "ucc_thermal")
    sp = _u8(y, "ucc_supply")
    sp_status = _u8(y, "ucc_supply_status")
    mods = _u8(y, "ucc_modifiers")

    # Vectorized code assembly: thermal letter + supply letter (o/n for the
    # not-applicable slot) + optional "-xw" modifier suffix.
    tl = np.array([_THERMAL_LETTERS[b] for b in thermal_bands])
    sl = np.array([_SUPPLY_LETTERS[b] for b in supply_bands])
    supply_letter = np.where(
        sp != 255,
        sl[np.clip(sp, 0, len(sl) - 1)],
        np.where(land, "n", "o"),
    )
    base = tl[th] + supply_letter
    suffix = np.where(
        (mods & 1).astype(bool) | (mods & 2).astype(bool),
        "-"
        + np.where((mods & 1).astype(bool), "x", "")
        + np.where((mods & 2).astype(bool), "w", ""),
        "",
    )
    all_codes: np.ndarray = (base + suffix).astype(object)

    # --- Global stats -------------------------------------------------------
    n_land, n_ocean = int(land.sum()), int((~land).sum())
    # Main classes aggregate over modifier suffixes (Tt and Tt-w are one class).
    land_base = Counter(base[land].tolist())
    land_combos = Counter(all_codes[land].tolist())
    ocean_bands = Counter(np.array(thermal_bands)[th[~land]].tolist())
    cont_share = float((mods[land] & 1).mean())
    ws_share = float(((mods[land] & 2) > 0).mean())
    ai_land_valid = ai[land & (ai_status == 0)]
    status_tally = Counter(status_codes[s] for s in ai_status[land])
    ood_land = int(((ai_status == 4) & land).sum())
    supply_na_land = int((land & (sp == 255)).sum())

    # --- Expectation checks (plan 4b, restated for profile v1) --------------
    top5 = land_base.most_common(5)
    top5_share = sum(c for _, c in top5) / n_land
    e1_verdict = top5_share >= 0.8
    e2 = cont_share == 0.0 and t_range.max() < 25.0
    e4 = bool(np.all(sp[~land] == 255))
    checks = [
        (
            "E1 主类集中 tropical/temperate × transitional/humid（计划按 v0 预期；"
            "v1 干旱带 0.2 细分后 semi_arid/arid 单列）",
            f"top5 组合占陆地 {top5_share:.0%}：" + "、".join(f"{k} {v}" for k, v in top5),
            "✓" if e1_verdict else "△（实际见分布表，计划预期按 v1 修正）",
        ),
        (
            "E2 continental ≈ 0（t_range 全域 0–5.4 °C，构造性低于 25 °C 阈值）",
            f"continental 份额 {cont_share:.2%}，max t_range {t_range.max():.2f} °C",
            "✓" if e2 else "✗",
        ),
        (
            "E3 water_stress 标记季节干旱区（deficit ≥ 0.5）",
            f"陆地份额 {ws_share:.1%}；极值点见 §5",
            "✓" if ws_share > 0 else "✗",
        ),
        (
            "E4 海洋 cell 供需轴全部 n/a（o 槽位）",
            f"海洋 255 份额 {'100%' if e4 else '<100%'}",
            "✓" if e4 else "✗",
        ),
        (
            "E5 部分有效路径：冰冻区走 out_of_domain（冰冻陆地应得 Pn 而非伪湿润；"
            "陆地 n/a 应全部由 out_of_domain 解释）",
            f"out_of_domain：全网格 {int((ai_status == 4).sum())}，其中陆地 {ood_land}"
            f"（陆地供需 n/a 共 {supply_na_land}）",
            "✓" if supply_na_land == ood_land else "✗",
        ),
        (
            "E6 cold 带（t_min<−3 且 t_max≥10）出现与否取决于季节振幅：Nacrea 弱季节"
            "（9° 倾角 + 短年）预期 cold 极少或为零——「无 D 类」的 UCC 对应物",
            f"cold cell 全网格 {int((th == 1).sum())}",
            "✓（记录值）",
        ),
    ]

    # --- Sites ----------------------------------------------------------------
    site_rows: list[str] = []
    site_details: list[str] = []
    for k, (name, la, lo, want) in enumerate(SITES, start=1):
        m = land if want == "land" else ~land
        i = _nearest(la, lo, pts, mask=m)
        c = all_codes[i]
        ai_s = _fmt(ai[i]) if ai_status[i] == 0 else status_short(status_codes[ai_status[i]])
        def_s = (
            _fmt(deficit[i])
            if deficit_status[i] == 0
            else status_short(status_codes[deficit_status[i]])
        )
        site_rows.append(
            f"| {k} | {name} | {lat[i]:.1f} | {lon[i]:.1f} | {elev[i]:.0f}"
            f" | {t_mean[i]:.1f} | {t_range[i]:.1f} | {p_total[i]:.0f} | {ai_s} | {def_s}"
            f" | **{c}** |"
        )
        mods_l = []
        if mods[i] & 1:
            mods_l.append("continental")
        if mods[i] & 2:
            mods_l.append("water_stress")
        supply_s = (
            supply_bands[sp[i]]
            if sp[i] != 255
            else f"n/a（{status_short(status_codes[sp_status[i]])}）"
            if land[i]
            else "n/a（海洋）"
        )
        site_details += [
            f"### {k}. {name}",
            "",
            f"- cell #{i} · {'陆地' if land[i] else '海洋'} · 高程 {elev[i]:.0f} m",
            f"- 月箱均 T（°C）：{' '.join(f'{v:.1f}' for v in t_monthly[i])}",
            f"- 月箱降水（mm/箱）：{' '.join(f'{v:.0f}' for v in p_monthly[i])}",
            f"- 描述量：t_mean {t_mean[i]:.1f} · t_min {t_min[i]:.1f} · t_max {t_max[i]:.1f}"
            f" · t_range {t_range[i]:.1f} · 低于0°C份额 {t_below[i]:.2f}"
            f" · P {p_total[i]:.0f} mm/参考年 · AI {ai_s} · deficit {def_s}"
            f" · C_TV {_fmt(conc[i]) if np.isfinite(conc[i]) else '—'}",
            f"- **分类（{profile}）**：{thermal_bands[th[i]]} / {supply_s}"
            f" · 简码 **{c}** · 修饰语：{'+'.join(mods_l) if mods_l else '—'}",
            "",
        ]

    # --- Extremes ---------------------------------------------------------------
    def extreme_row(label: str, i: int) -> str:
        ai_s = _fmt(ai[i]) if ai_status[i] == 0 else status_short(status_codes[ai_status[i]])
        return (
            f"| {label} | #{i} | {lat[i]:.1f}, {lon[i]:.1f} | {elev[i]:.0f}"
            f" | T均 {t_mean[i]:.1f} · P {p_total[i]:.0f} · AI {ai_s} | **{all_codes[i]}** |"
        )

    lv = land & (ai_status == 0)
    extremes = [
        extreme_row("最干（AI 最低陆地）", int(np.argmin(np.where(lv, ai, np.inf)))),
        extreme_row("最湿（AI 最高陆地）", int(np.argmax(np.where(lv, ai, -np.inf)))),
        extreme_row("最冷（t_mean 最低）", int(np.argmin(t_mean))),
        extreme_row("最热（t_mean 最高）", int(np.argmax(t_mean))),
        extreme_row(
            "水压力最强（deficit 最高陆地）",
            int(np.argmax(np.where(lv & (deficit_status == 0), deficit, -np.inf))),
        ),
        extreme_row("季节最强（t_range 最大）", int(np.argmax(t_range))),
        extreme_row("降水最多（陆地）", int(np.argmax(np.where(land, p_total, -np.inf)))),
    ]

    # --- Document ------------------------------------------------------------------
    q = np.array([0.05, 0.25, 0.5, 0.75, 0.95])
    ai_q = np.quantile(ai_land_valid, q) if ai_land_valid.size else np.full(5, np.nan)
    tr_q = np.quantile(t_range[land], q)
    pt_q = np.quantile(p_total[land], q)

    band_rows = []
    for t_name in thermal_bands:
        for s_name in supply_bands:
            code = _THERMAL_LETTERS[t_name] + _SUPPLY_LETTERS[s_name]
            cnt = land_base.get(code, 0)
            band_rows.append(f"| {code}（{t_name}/{s_name}） | {cnt} | {cnt / n_land:.1%} |")
    for t_name in thermal_bands:
        code = _THERMAL_LETTERS[t_name] + "n"
        cnt = land_base.get(code, 0)
        band_rows.append(f"| {code}（{t_name}/供需不适用） | {cnt} | {cnt / n_land:.1%} |")

    tr_q_s = " | ".join(f"{v:.2f}" for v in tr_q)
    ai_q_s = " | ".join(_fmt(v) for v in ai_q)
    pt_q_s = " | ".join(f"{v:.0f}" for v in pt_q)

    today = datetime.date.today().isoformat()
    doc = (
        f"""---
title: "UCC 迁移语义夹具：{profile} 应用于 Nacrea"
type: fixture
tags: [ucc, climate, classification, fixture, migration]
date: {today}
status: accepted
---

# 0010 · UCC 迁移语义夹具（{profile} × Nacrea）

> UCC-01 第四步 4b/4c 产物。本文档由脚本生成，勿手改——重生成：
> `uv run python scripts/climate/ucc_examples_nacrea.py`
> 数据 = 正典构建导出 `maps/satellite_nacrea/climate_yearly.msgpack`
> （引擎输出，`data_source: model`，profile {profile}）+ `climate_monthly.msgpack`
> + `cvt_mesh.json`。描述量与分类语义见
> `docs/knowledge/climatology/ucc_climate_descriptors.md`；Earth 侧对照例见
> `data/worlds/earth/design-notes/ucc-worked-examples.md`。
> 生成日期：{today}。
> **状态简写**（表格中替代完整状态名）：`OOD` = out_of_domain（需求模型超出有效域
> ——全年无液态水，AI/deficit 不报数）；`MI` = missing_input、`NA` = not_applicable、
> `NPD` = no_positive_demand（语义见知识文档 §3）。

## 1. 夹具目的

分类阈值全局共享（绝不按世界取分位数），所以把同一 profile 应用到慢自转
（Ω=0.31 Ω⊕、90° 单圈）、短年（99.98 地球日）、62 K 温室的 Nacrea 上，必须产出
**语义正确而非地球样**的标签。本文档记录 {profile} 在当前正典气候态上的结果，
作为将来 profile / 引擎 / 设定变更的对照基线：下述任何表格的移动都是需要有意
接受或排查的语义变化，不是可以静默发生的漂移。

时间契约迁移点（知识文档 §2）：12 个分箱是**参考年**（365.25 地球日）的等长
切片，每箱 ≈ 0.37 个 Nacrea 本地年——月箱序列不是「本地月份」；`p_total` 按
参考年报告，不等于一个本地年累计。AI 为窗口不变量，可直接跨世界比较。

## 2. 全局分布（{n} cells；陆地 {n_land}，海洋 {n_ocean}）

**热量带**：陆地+海洋合计 — """
        + "、".join(f"{name} {int((th == i).sum())}" for i, name in enumerate(thermal_bands))
        + """。

**陆地供需档（valid）**："""
        + "、".join(
            f"{name} {int((land & (sp == i)).sum())}" for i, name in enumerate(supply_bands)
        )
        + f"""；陆地供需 n/a {supply_na_land}（其中 out_of_domain {ood_land}）。

**陆地主类组合**：

| 类 | cells | 占陆地 |
|----|-------|--------|
"""
        + "\n".join(band_rows)
        + """

**海洋热量带**："""
        + "、".join(f"{k} {v}" for k, v in ocean_bands.most_common())
        + f"""。

**修饰语**：continental {cont_share:.2%}（构造性为零，见 E2）；water_stress
{ws_share:.1%} 陆地。

**AI 状态（陆地）**："""
        + "、".join(f"{k} {v}" for k, v in status_tally.most_common())
        + f"""。

**描述量分位数（陆地）**：

| 量 | 5% | 25% | 中位 | 75% | 95% |
|----|----|----|------|-----|-----|
| t_range °C | {tr_q_s} |
| AI（valid） | {ai_q_s} |
| P mm/参考年 | {pt_q_s} |

t_mean 全域 {t_mean.min():.1f} .. {t_mean.max():.1f} °C；t_range 全域 0 ..
{t_range.max():.2f} °C。

## 3. 预期 vs 实际（迁移验收）

计划时（ucc-01-plan 4b）按 v0 记录的预期，v1 语义下逐条核对：

| 预期 | 实际 | 判定 |
|------|------|------|
"""
        + "\n".join(f"| {a} | {b} | {c} |" for a, b, c in checks)
        + """

## 4. 代表地点（命名地理锚点，geography.yaml）

| # | 地点 | 纬 | 经 | 高程 m | T均 | T范围 | P | AI | deficit | 类码 |
|---|------|----|----|--------|-----|-------|---|----|---------|------|
"""
        + "\n".join(site_rows)
        + """

月箱序列 month 0 = 参考三月（春分点），与引擎约定一致。

"""
        + "\n".join(site_details)
        + """
## 5. 极值点

| 量 | cell | 纬, 经 | 高程 m | 描述量 | 类码 |
|----|------|--------|--------|--------|------|
"""
        + "\n".join(extremes)
        + """

## 6. 夹具维护

- 正典气候重建后（`uv run dreamulator build nacrea --only climate` 或全量）重跑
  本脚本刷新文档；数值移动应能与构建改动对应。
- profile 升级（v2 等）时：标题/元数据随 `climate_yearly.msgpack` 的 `profile`
  字段自动更新，§3 预期表需人工重述。
- 本文档是**语义夹具**（记录当前正典的正确行为），不是设定文档；设定变更走
  ADR 流程，本文档只在重建后刷新。
"""
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(doc, encoding="utf-8")
    print(f"Wrote {args.out}")

    # Console summary
    print(f"\nprofile={profile} | land={n_land} ocean={n_ocean}")
    print("Top land classes (base):", land_base.most_common(8))
    print("Top land codes (with modifiers):", land_combos.most_common(8))
    print(f"continental={cont_share:.2%} water_stress={ws_share:.1%} ood_land={ood_land}")
    print(f"AI(land valid) median={ai_q[2]:.2f} | t_range max={t_range.max():.2f}")


if __name__ == "__main__":
    main()
