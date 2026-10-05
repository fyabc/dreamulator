#!/usr/bin/env python3
"""Generate UCC worked-examples documents for the Solar-System reference bodies
(UCC-01 第四步 4d).

The bodies live inside the real-world reference-anchor world (``earth``) as
additional planet_ids.  Reads a body's ``climate_yearly.msgpack`` +
``climate_monthly.msgpack`` + the mesh file and writes the generated-tables
file ``docs/ucc/examples/<body>-data.md`` (the handwritten companion
``<body>.md`` carries the interpretation prose — script never touches it):

- the declared time basis + provenance (epistemic status travels with the file:
  GCM climatology = ucc-review §6.2 L4, NOT error-free truth; Diviner =
  observation-grade *surface* temperature);
- global class distribution + modifier/status tallies;
- named-feature site blocks (bin series → descriptors → classification);
- extreme cells.

Usage:
    uv run python scripts/solar/ucc_examples_solar.py --planet mars
    uv run python scripts/solar/ucc_examples_solar.py --planet titan --out <path>
"""

from __future__ import annotations

import argparse
import datetime
import sys
from collections import Counter
from pathlib import Path

import msgpack
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from dreamulator.map.export import find_mesh_file, load_cvt_mesh  # noqa: E402
from dreamulator.map.ucc import status_short  # noqa: E402

_ROOT = Path(__file__).resolve().parents[2]

# Body key → planet_id inside the real-world anchor world (stellar.yaml
# conventions: satellite_* for moons).
PLANET_IDS = {
    "mars": "planet_mars",
    "moon": "satellite_moon",
    "venus": "planet_venus",
    "titan": "satellite_titan",
}
_ANCHOR_WORLD = "earth"  # real-world reference anchor (name is historical)


# v2 alphabet: Köppen-direction A/C/D/E with B permanently blank; modifiers
# l/g; suffix letters m/d (wet-season shape) + h/o (rain–demand phase).
_THERMAL_LETTERS = {"tropical": "A", "temperate": "C", "cold": "D", "polar": "E"}
_SUPPLY_LETTERS = {"arid": "a", "semi_arid": "p", "transitional": "t", "humid": "u"}
_SHAPE_LETTERS = {"unimodal": "m", "bimodal": "d"}
_PHASE_LETTERS = {"in_phase": "h", "anti_phase": "o"}

# Named features per world: (name, lat, lon, want) — literature-typical
# coordinates of well-known landmarks, for geographic-intuition review.
WORLD_SITES: dict[str, list[tuple[str, float, float, str]]] = {
    "mars": [
        ("奥林帕斯山", 18.65, -133.8, "land"),
        ("Ascraeus Mons（塔尔西斯）", 11.9, -104.5, "land"),
        ("水手谷中部", -14.0, -56.0, "land"),
        ("希腊盆地底部", -42.7, 70.0, "land"),
        ("阿吉尔盆地", -49.4, -42.1, "land"),
        ("阿拉伯高地", 20.0, -30.0, "land"),
        ("大瑟提斯高原", 8.4, 69.5, "land"),
        ("埃律西昂平原", 3.0, 154.7, "land"),
        ("子午线平原（机遇号）", -2.0, -5.6, "land"),
        ("乌托邦平原", 46.7, 117.5, "land"),
        ("北极冠", 85.0, 0.0, "land"),
        ("南极高原（Planum Australe）", -84.0, 60.0, "land"),
    ],
    "moon": [
        ("中央湾（近面赤道）", 0.0, 0.0, "land"),
        ("雨海", 35.0, -17.0, "land"),
        ("静海（阿波罗11）", 0.7, 23.5, "land"),
        ("风暴洋", 20.0, -55.0, "land"),
        ("哥白尼坑", 9.6, -20.1, "land"),
        ("阿里斯塔克斯高原", 23.7, -47.4, "land"),
        ("齐奥尔科夫斯基坑（背面）", -20.4, 129.1, "land"),
        ("南极-艾特肯盆地", -53.0, 191.0, "land"),
        ("沙克尔顿坑（南极）", -89.9, 130.0, "land"),
        ("北极区", 89.0, 0.0, "land"),
    ],
    "venus": [
        ("麦克斯韦山脉", 65.0, 5.0, "land"),
        ("伊师塔地", 70.0, 40.0, "land"),
        ("阿佛洛狄忒地", -10.0, 200.0, "land"),
        ("贝塔区（Theia Mons）", 25.0, 282.0, "land"),
        ("Maat Mons", 0.5, 194.6, "land"),
        ("几内亚平原", -21.9, 319.4, "land"),
        ("拉维尼亚平原", -21.2, 344.5, "land"),
        ("赤道低地", 0.0, 150.0, "land"),
        ("北极区", 85.0, 0.0, "land"),
        ("南极区", -85.0, 0.0, "land"),
    ],
    "titan": [
        # Observed-name anchors use want="any": the model run's lake clusters do
        # not necessarily coincide with observed sea positions (Faulk hydrology
        # migrates lakes over Saturn-year timescales) — the snapped cell's class
        # tells the observation-vs-model story honestly.
        ("克拉肯海（观测名锚点）", 65.0, -40.0, "any"),
        ("丽姬亚海（观测名锚点）", 78.0, -40.0, "any"),
        ("安大略湖（观测名锚点）", -5.4, -150.0, "any"),
        ("北极甲烷湖区（模型 qsurf 集群）", 80.0, 40.0, "ocean"),
        ("南极甲烷湖区（模型 qsurf 集群）", -75.0, 0.0, "ocean"),
        ("香格里拉（赤道沙丘带）", -10.0, -160.0, "land"),
        ("阿鲁（Xanadu 亮区）", 9.0, -100.0, "land"),
        ("赤道区（0° 本初）", 0.0, 0.0, "land"),
        ("Menrva 盆地", 37.3, -53.4, "land"),
        ("南极区", -85.0, 120.0, "land"),
    ],
}


def _unit(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    la, lo = np.radians(lat), np.radians(lon)
    return np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], axis=1)


def _nearest(lat: float, lon: float, pts: np.ndarray, mask: np.ndarray | None = None) -> int:
    v = _unit(np.array([lat]), np.array([lon]))[0]
    dots = pts @ v
    if mask is not None:
        dots = np.where(mask, dots, -2.0)
    return int(np.argmax(dots))


def _load_monthly(path: Path) -> tuple[np.ndarray, np.ndarray, dict]:
    with path.open("rb") as f:
        d = msgpack.unpackb(f.read())
    n, m = int(d["num_cells"]), int(d["months"])

    def deq(name: str) -> np.ndarray:
        q = np.frombuffer(d[name], dtype=np.int16).astype(np.float64)
        scale = float(d[name.removesuffix("_monthly") + "_scale"])
        offset = float(d[name.removesuffix("_monthly") + "_offset"])
        return q.reshape(n, m) * scale + offset

    return deq("t_monthly"), deq("p_monthly"), d


def _f32(d: dict, key: str) -> np.ndarray:
    return np.frombuffer(d[key], dtype=np.float32).astype(np.float64)


def _u8(d: dict, key: str) -> np.ndarray:
    return np.frombuffer(d[key], dtype=np.uint8)


def _fmt(v: float | None, prec: int = 2) -> str:
    return "—" if v is None or (isinstance(v, float) and not np.isfinite(v)) else f"{v:.{prec}f}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--planet", required=True, choices=sorted(WORLD_SITES))
    parser.add_argument("--map-dir", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    world = args.planet
    planet_id = PLANET_IDS[world]
    map_dir = args.map_dir or _ROOT / f"data/worlds/{_ANCHOR_WORLD}/maps" / planet_id
    out = args.out or _ROOT / f"docs/ucc/examples/{world}-data.md"

    print(f"Reading {map_dir}/climate_yearly.msgpack …")
    with (map_dir / "climate_yearly.msgpack").open("rb") as f:
        y = msgpack.unpackb(f.read())
    n = int(y["num_cells"])
    profile = str(y["profile"])
    thermal_bands = list(y["thermal_bands"])
    supply_bands = list(y["supply_bands"])
    status_codes = list(y["status_codes"])
    data_source = str(y.get("data_source", "?"))
    provenance = dict(y.get("provenance", {}))
    climate_state = str(y.get("climate_state", "—（未声明）"))
    _lapse = y.get("lapse_rate_c_per_km")
    lapse_line = f"{float(_lapse):g} K/km" if _lapse is not None else "未声明（无大气 → -H 不适用）"
    bin_days = float(y.get("bin_days", 365.25 / 12))
    window_days = float(y.get("window_days", bin_days * 12))

    t_monthly, p_monthly, monthly_meta = _load_monthly(map_dir / "climate_monthly.msgpack")
    month_0 = str(monthly_meta.get("month_0", "?"))

    print("Reading mesh — full JSON parse …")
    _mf = find_mesh_file(map_dir)
    assert _mf is not None, "no mesh file under {map_dir}"
    mesh = load_cvt_mesh(_mf)
    cells = mesh["cells"]
    lat = np.array([c["lat"] for c in cells], dtype=np.float64)
    lon = np.array([c["lon"] for c in cells], dtype=np.float64)
    elev = np.array([c.get("elevation", 0.0) for c in cells], dtype=np.float64)
    water = np.array([c.get("water_class") or "" for c in cells], dtype=str)
    land = water == "land"
    assert len(lat) == n, "mesh/yearly cell-count mismatch"
    pts = _unit(lat, lon)

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
    shape_codes = list(y.get("shape_codes", []))
    phase_codes = list(y.get("phase_codes", []))
    ucc_shape = _u8(y, "ucc_shape") if "ucc_shape" in y else None
    ucc_phase = _u8(y, "ucc_phase") if "ucc_phase" in y else None

    tl = np.array([_THERMAL_LETTERS[b] for b in thermal_bands])
    sl = np.array([_SUPPLY_LETTERS[b] for b in supply_bands])
    supply_letter = np.where(sp != 255, sl[np.clip(sp, 0, len(sl) - 1)], np.where(land, "n", "o"))
    base = tl[th] + supply_letter
    suffix = (
        np.where((mods & 1).astype(bool), "l", "")
        + np.where((mods & 2).astype(bool), "g", "")
        + np.where((mods & 4).astype(bool), "H", "")
    ).astype(object)
    if ucc_shape is not None and shape_codes:
        shape_letter = np.array(
            [_SHAPE_LETTERS.get(shape_codes[v], "") if v != 255 else "" for v in ucc_shape],
            dtype=object,
        )
        suffix = suffix + shape_letter
    if ucc_phase is not None and phase_codes:
        phase_letter = np.array(
            [_PHASE_LETTERS.get(phase_codes[v], "") if v != 255 else "" for v in ucc_phase],
            dtype=object,
        )
        suffix = suffix + phase_letter
    all_codes: np.ndarray = (base + np.where(suffix != "", "-" + suffix, "")).astype(object)

    n_land, n_ocean = int(land.sum()), int((~land).sum())
    land_base = Counter(base[land].tolist())
    ocean_base = Counter(base[~land].tolist())
    cont_share = float((mods[land] & 1).mean()) if n_land else 0.0
    ws_share = float(((mods[land] & 2) > 0).mean()) if n_land else 0.0
    status_tally = Counter(status_codes[s] for s in ai_status)

    band_rows = []
    for t_name in thermal_bands:
        for s_name in supply_bands:
            code = _THERMAL_LETTERS[t_name] + ("n" if s_name == "n-a" else _SUPPLY_LETTERS[s_name])
            cnt = land_base.get(code, 0)
            if cnt or code in {k[:2] for k in land_base}:
                pct = cnt / max(n_land, 1)
                band_rows.append(f"| {code}（{t_name}/{s_name}） | {cnt} | {pct:.1%} |")
    for t_name in thermal_bands:
        code = _THERMAL_LETTERS[t_name] + "n"
        cnt = land_base.get(code, 0)
        band_rows.append(f"| {code}（{t_name}/供需不适用） | {cnt} | {cnt / max(n_land, 1):.1%} |")

    site_rows: list[str] = []
    site_details: list[str] = []
    for k, (name, la, lo, want) in enumerate(WORLD_SITES[world], start=1):
        m = {"land": land, "ocean": ~land}.get(want)  # None = snap to any class
        if m is not None and not m.any():
            continue
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
        if mods[i] & 4:
            mods_l.append("highland")
        if sp[i] != 255:
            supply_s = supply_bands[sp[i]]
        elif land[i]:
            supply_s = f"n/a（{status_short(status_codes[sp_status[i]])}）"
        else:
            supply_s = "n/a（非陆地）"
        site_details += [
            f"### {k}. {name}",
            "",
            f"- cell #{i} · {'陆地' if land[i] else '海洋/海域'} · 高程 {elev[i]:.0f} m",
            f"- 分箱均 T（°C）：{' '.join(f'{v:.1f}' for v in t_monthly[i])}",
            f"- 分箱降水（mm/箱）：{' '.join(f'{v:.1f}' for v in p_monthly[i])}",
            f"- 描述量：t_mean {t_mean[i]:.1f} · t_min {t_min[i]:.1f} · t_max {t_max[i]:.1f}"
            f" · t_range {t_range[i]:.1f} · 低于0°C份额 {t_below[i]:.2f}"
            f" · P {p_total[i]:.0f} mm/窗口 · AI {ai_s} · deficit {def_s}"
            f" · C_TV {_fmt(conc[i]) if np.isfinite(conc[i]) else '—'}",
            f"- **分类（{profile}）**：{thermal_bands[th[i]]} / {supply_s}"
            f" · 简码 **{c}** · 修饰语：{'+'.join(mods_l) if mods_l else '—'}",
            "",
        ]

    def extreme_row(label: str, i: int) -> str:
        ai_s = _fmt(ai[i]) if ai_status[i] == 0 else status_short(status_codes[ai_status[i]])
        return (
            f"| {label} | #{i} | {lat[i]:.1f}, {lon[i]:.1f} | {elev[i]:.0f}"
            f" | T均 {t_mean[i]:.1f} · P {p_total[i]:.0f} · AI {ai_s} | **{all_codes[i]}** |"
        )

    lv = land & (ai_status == 0)
    extremes = [
        extreme_row("最冷（t_mean 最低）", int(np.argmin(t_mean))),
        extreme_row("最热（t_mean 最高）", int(np.argmax(t_mean))),
        extreme_row("季节最强（t_range 最大）", int(np.argmax(t_range))),
    ]
    if p_total.max() > 0:  # skip the degenerate row on declared-zero-P worlds
        extremes.append(extreme_row("降水最多", int(np.argmax(p_total))))
    if lv.any():
        extremes.append(
            extreme_row("最干（AI 最低陆地）", int(np.argmin(np.where(lv, ai, np.inf))))
        )
        extremes.append(
            extreme_row("最湿（AI 最高陆地）", int(np.argmax(np.where(lv, ai, -np.inf))))
        )

    prov_lines = "\n".join(f"> - {k}: {v}" for k, v in provenance.items())
    today = datetime.date.today().isoformat()
    doc = (
        f"""# {world.capitalize()} · UCC Worked Examples — 数据表（{profile}）

> UCC-01 第四步 4d 产物。本文档由脚本生成，勿手改——重生成：
> `uv run python scripts/solar/ucc_examples_solar.py --planet {world}`
> 生成日期：{today}。本天体的解读（世界要点、读法）见手写文档
> `docs/ucc/examples/{world}.md`；描述量与分类语义见
> `docs/ucc/specification.md`（§8 有本天体的示意演练行，
> 本文档是它的真实数据对照）。
> **状态简写**：`OOD` = out_of_domain（需求模型超出有效域）；`MI` = missing_input、
> `NA` = not_applicable、`NPD` = no_positive_demand（语义见知识文档 §3）。

**数据源**（`data_source: {data_source}`——认知地位见文件内 provenance，随数据走）：
{prov_lines}

**世界级声明**：`climate_state: {climate_state}`；递减率
{lapse_line}（-H 高地修饰语的判据输入）。

**时间基准**：12 分箱 × {bin_days:.2f} 地球日 = 窗口 {window_days:.1f} 日；
`month_0` = `{month_0}`。`p_total` 按此窗口报告；AI/deficit 为窗口不变量，可跨世界
直接比较（知识文档 §2）。

## 1. 全局分布（{n} cells；陆地 {n_land}，非陆地 {n_ocean}）

**热量带（全部 cell）**："""
        + "、".join(f"{name} {int((th == i).sum())}" for i, name in enumerate(thermal_bands))
        + f"""。

**修饰语**：continental {cont_share:.1%}；water_stress {ws_share:.1%}（陆地）。

**AI 状态（全部 cell）**："""
        + "、".join(f"{k} {v}" for k, v in status_tally.most_common())
        + """。

**陆地主类组合**：

| 类 | cells | 占陆地 |
|----|-------|--------|
"""
        + "\n".join(band_rows)
        + """

**非陆地基码**："""
        + ("、".join(f"{k} {v}" for k, v in ocean_base.most_common()) or "—")
        + """

## 2. 命名地点

| # | 地点 | 纬 | 经 | 高程 m | T均 | T范围 | P | AI | deficit | 类码 |
|---|------|----|----|--------|-----|-------|---|----|---------|------|
"""
        + "\n".join(site_rows)
        + """

"""
        + "\n".join(site_details)
        + """
## 3. 极值点

| 量 | cell | 纬, 经 | 高程 m | 描述量 | 类码 |
|----|------|--------|--------|--------|------|
"""
        + "\n".join(extremes)
        + """
"""
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    print(f"Wrote {out}")
    print(
        f"land={n_land} | thermal: "
        + ", ".join(f"{name}={int((th == i).sum())}" for i, name in enumerate(thermal_bands))
    )
    print("Top land classes:", land_base.most_common(8))


if __name__ == "__main__":
    main()
