#!/usr/bin/env python3
"""Generate the Earth UCC worked-examples document (UCC-01 第四步 4c).

Reads the L2 external-climate-state dataset (``private/reviews/ucc-l2-earth-obs-
*.msgpack``, built by ``ucc_obs_descriptors.py`` from the earth root's observed
monthly series: NCEP R1 temperature + GPCP v2.3 precipitation + Beck 2018
Köppen reference column) and produces a human-review document:

- a summary table of ~30 curated real-world locations (this doubles as the 4b
  创作验收 review list: v1 labels vs geographic intuition);
- per-site detail blocks (monthly series → descriptors → classification +
  Köppen parallel);
- a class-coverage check — land classes not hit by any named site are topped up
  with the class medoid cell (marked as such), so every class has at least one
  worked example.

Output: ``docs/ucc/examples/earth.md`` (regenerate,
don't hand-edit).

Usage:
    uv run python scripts/climate/ucc_examples_earth.py
    uv run python scripts/climate/ucc_examples_earth.py --dataset <path> --out <path>
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

import msgpack
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from dreamulator.map.ucc import (  # noqa: E402
    PROFILE_CURRENT,
    STATUS_CODES,
    SUPPLY_BANDS_CURRENT,
    THERMAL_BANDS_CURRENT,
    ClimateDescriptors,
    UCCClassV0,
    classify_v1,
    status_short,
)

_DEFAULT_DATASET = Path("private/reviews/ucc-l2-earth-obs-2026-09-20.msgpack")
_DEFAULT_OUT = Path("docs/ucc/examples/earth.md")

# Curated review sites (4b): name, lat, lon, land/ocean, short geographic
# context.  Chosen to span every thermal × supply regime a reviewer can check
# against geographic intuition; gaps are auto-topped-up with class medoids.
SITES: list[tuple[str, float, float, str, str]] = [
    ("马瑙斯", -3.1, -60.0, "land", "亚马逊盆地中部"),
    ("基桑加尼", 0.5, 25.2, "land", "刚果盆地"),
    ("加里曼丹内陆", -0.5, 112.0, "land", "婆罗洲，海岛型热带雨林"),
    ("孟买", 19.0, 72.9, "land", "印度西海岸，季风"),
    ("达尔文", -12.5, 130.8, "land", "澳洲北部，冬干季风"),
    ("彼得罗利纳", -9.4, -40.5, "land", "巴西东北内陆地（caatinga）"),
    ("阿萨布", 13.0, 42.7, "land", "达纳基尔洼地南端，红海海岸荒漠（地球最热低地之一）"),
    ("利雅得", 24.7, 46.7, "land", "阿拉伯半岛荒漠"),
    ("塔曼拉塞特", 22.8, 5.5, "land", "撒哈拉中心"),
    ("尼亚美", 13.5, 2.1, "land", "萨赫勒过渡带"),
    ("甘济", -21.7, 21.7, "land", "卡拉哈里"),
    ("吕德里茨", -26.6, 15.2, "land", "纳米布海岸荒漠"),
    ("安托法加斯塔", -23.6, -70.4, "land", "阿塔卡马海岸"),
    ("爱丽丝泉", -23.7, 133.9, "land", "澳洲内陆"),
    ("雅典", 38.0, 23.7, "land", "地中海夏干"),
    ("洛杉矶", 34.05, -118.25, "land", "加州海岸地中海型"),
    ("伦敦", 51.5, -0.1, "land", "西欧温带海洋性"),
    ("北京", 39.9, 116.4, "land", "华北季风，冬冷夏热"),
    ("丹佛", 39.7, -105.0, "land", "北美高平原东缘"),
    ("萨斯卡通", 52.1, -106.7, "land", "加拿大草原"),
    ("雅库茨克", 62.0, 129.7, "land", "东西伯利亚，极端大陆性"),
    ("达兰扎达嘎德", 43.6, 104.4, "land", "戈壁"),
    ("沱沱河", 34.2, 92.4, "land", "青藏高原腹地（~4500 m）"),
    ("乌特恰维克", 71.3, -156.8, "land", "北极苔原（原巴罗角）"),
    ("雷克雅未克", 64.1, -21.9, "land", "冰岛，高纬海洋性"),
    ("里瓦达维亚海军准将城", -45.9, -67.5, "land", "巴塔哥尼亚东岸雨影"),
    ("布宜诺斯艾利斯", -34.6, -58.4, "land", "潘帕斯"),
    ("基督城", -43.5, 172.6, "land", "新西兰东岸"),
    ("冰穹A", -75.1, 123.4, "land", "南极冰盖最高点（需求模型域外反例）"),
    ("Summit 站", -72.6, -38.4, "land", "格陵兰冰盖顶峰"),
    ("赤道太平洋", 0.0, -140.0, "ocean", "海洋：热带暖池东缘"),
    ("北大西洋", 50.0, -30.0, "ocean", "海洋：副极地环流"),
    ("南大洋", -60.0, 30.0, "ocean", "海洋：南极绕极流"),
]

_FLOAT_KEYS = (
    "t_mean_c",
    "t_min_c",
    "t_max_c",
    "t_range_c",
    "t_below_frac",
    "p_mean_mm_per_month",
    "p_total_mm",
    "ai",
    "deficit",
    "concentration",
)
_UINT8_KEYS = ("ai_status", "deficit_status")


def _unit(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    la, lo = np.radians(lat), np.radians(lon)
    return np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], axis=1)


def _nearest_cell(lat: float, lon: float, pts: np.ndarray, mask: np.ndarray | None = None) -> int:
    v = _unit(np.array([lat]), np.array([lon]))[0]
    dots = pts @ v
    if mask is not None:
        dots = np.where(mask, dots, -2.0)
    return int(np.argmax(dots))


def _decode_fields(d: dict) -> dict[str, np.ndarray]:
    """Decode the dataset's raw-bytes columns into numpy arrays (do NOT index
    the msgpack bytes directly — that yields single-byte ints)."""
    f: dict[str, np.ndarray] = {
        k: np.frombuffer(d[k], dtype=np.float32).astype(np.float64) for k in _FLOAT_KEYS
    }
    f.update({k: np.frombuffer(d[k], dtype=np.uint8) for k in _UINT8_KEYS})
    return f


def _descriptors_at(f: dict[str, np.ndarray], i: int) -> ClimateDescriptors:
    def opt(key: str) -> float | None:
        # The exporter stores NaN exactly when the paired status is non-valid.
        v = float(f[key][i])
        return None if np.isnan(v) else v

    return ClimateDescriptors(
        t_mean=float(f["t_mean_c"][i]),
        t_min=float(f["t_min_c"][i]),
        t_max=float(f["t_max_c"][i]),
        t_range=float(f["t_range_c"][i]),
        t_below_frac=float(f["t_below_frac"][i]),
        p_mean_rate=float(f["p_mean_mm_per_month"][i]),
        p_total=float(f["p_total_mm"][i]),
        ai=opt("ai"),
        ai_status=STATUS_CODES[int(f["ai_status"][i])],
        deficit=opt("deficit"),
        deficit_status=STATUS_CODES[int(f["deficit_status"][i])],
        concentration=opt("concentration"),
    )


def _fmt(v: float | None, prec: int = 2, suffix: str = "") -> str:
    return "—" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.{prec}f}{suffix}"


def _site_block(
    idx: int,
    title: str,
    context: str,
    cell: int,
    lat: float,
    lon: float,
    t12: np.ndarray,
    p12: np.ndarray,
    desc: ClimateDescriptors,
    cls: UCCClassV0,
    koppen: str,
) -> list[str]:
    la = f"{abs(lat):.1f}°{'N' if lat >= 0 else 'S'}"
    lo = f"{abs(lon):.1f}°{'E' if lon >= 0 else 'W'}"
    ai_s = _fmt(desc.ai) if desc.ai_status == "valid" else f"—（{status_short(desc.ai_status)}）"
    def_s = (
        _fmt(desc.deficit)
        if desc.deficit_status == "valid"
        else f"—（{status_short(desc.deficit_status)}）"
    )
    mods = []
    if cls.continental:
        mods.append("continental")
    if cls.water_stress:
        mods.append("water_stress")
    supply_s = cls.supply if cls.supply is not None else f"n/a（{status_short(cls.supply_status)}）"
    return [
        f"### {idx}. {title}（{context}）",
        "",
        f"- 位置：{la}, {lo} · cell #{cell} · {'陆地' if cls.is_land else '海洋'}"
        f" · Beck Köppen：{koppen or '—'}",
        f"- 月均 T（°C）：{' '.join(f'{v:.1f}' for v in t12)}",
        f"- 月降水（mm/月）：{' '.join(f'{v:.0f}' for v in p12)}",
        f"- 描述量：t_mean {desc.t_mean:.1f} · t_min {desc.t_min:.1f} · t_max {desc.t_max:.1f}"
        f" · t_range {desc.t_range:.1f} · 低于0°C份额 {desc.t_below_frac:.2f}"
        f" · P {desc.p_total:.0f} mm/参考年 · AI {ai_s} · deficit {def_s}"
        f" · C_TV {_fmt(desc.concentration)}",
        f"- **分类（{PROFILE_CURRENT}）**：{cls.thermal} / {supply_s} · 简码 **{cls.code}**"
        f" · 修饰语：{'+'.join(mods) if mods else '—'}",
        "",
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=_DEFAULT_DATASET)
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    args = parser.parse_args()

    with args.dataset.open("rb") as fh:
        d = msgpack.unpackb(fh.read())
    n = int(d["num_cells"])
    f = _decode_fields(d)
    lat = np.frombuffer(d["lat"], dtype=np.float32).astype(np.float64)
    lon = np.frombuffer(d["lon"], dtype=np.float32).astype(np.float64)
    t_monthly = np.frombuffer(d["t_monthly"], dtype=np.float32).reshape(n, 12).astype(np.float64)
    p_monthly = np.frombuffer(d["p_monthly"], dtype=np.float32).reshape(n, 12).astype(np.float64)
    water = np.array(d["water_class"], dtype=str)
    koppen = np.array(d["koppen_obs"], dtype=str)
    land = water == "land"
    pts = _unit(lat, lon)

    print(f"Dataset: {args.dataset} ({n} cells, {int(land.sum())} land)")

    # Classify every cell once (also feeds the coverage check).  Base codes
    # strip the modifier suffix — coverage/medoids are about main classes
    # (Tt and Tt-w are the same class).
    codes = np.empty(n, dtype=object)
    for i in range(n):
        codes[i] = classify_v1(_descriptors_at(f, i), is_land=bool(land[i])).code
    base_codes = np.array([str(c).split("-")[0] for c in codes], dtype=object)

    # --- Named sites -------------------------------------------------------
    entries: list[dict] = []
    for name, la, lo, want, ctx in SITES:
        cell = _nearest_cell(la, lo, pts, mask=land if want == "land" else ~land)
        desc = _descriptors_at(f, cell)
        cls = classify_v1(desc, is_land=bool(land[cell]))
        entries.append(
            {
                "name": name,
                "ctx": ctx,
                "cell": cell,
                "lat": float(lat[cell]),
                "lon": float(lon[cell]),
                "desc": desc,
                "cls": cls,
                "koppen": str(koppen[cell]),
                "t12": t_monthly[cell],
                "p12": p_monthly[cell],
                "medoid": False,
            }
        )

    # --- Coverage top-up: class medoids for classes no named site hits ------
    named_codes = {e["cls"].code.split("-")[0] for e in entries}
    ai, deficit = f["ai"], f["deficit"]
    t_mean, t_range = f["t_mean_c"], f["t_range_c"]
    for code in sorted(set(base_codes.tolist())):
        if code in named_codes:
            continue
        m = (base_codes == code) & land & np.isfinite(ai) & np.isfinite(deficit)
        if not m.any():
            # Ocean / n-a classes: pick a medoid on the finite features only.
            m = base_codes == code
            if not m.any():
                continue
        idx = np.where(m)[0]
        # Medoid on standardized (t_mean, log10 AI, deficit, t_range); NaN
        # features (e.g. AI on ocean) simply don't vote.
        with np.errstate(divide="ignore", invalid="ignore"):
            feat = np.stack(
                [
                    t_mean[idx],
                    np.log10(np.where(np.isfinite(ai[idx]), np.clip(ai[idx], 1e-3, None), np.nan)),
                    deficit[idx],
                    t_range[idx],
                ],
                axis=1,
            )
        finite = np.isfinite(feat)
        med = np.array(
            [np.median(feat[finite[:, j], j]) if finite[:, j].any() else 0.0 for j in range(4)]
        )
        spread = np.array(
            [np.std(feat[finite[:, j], j]) if finite[:, j].any() else 1.0 for j in range(4)]
        )
        spread = np.where(spread > 0, spread, 1.0)
        dist = np.abs(np.where(finite, (feat - med) / spread, 0.0)).sum(axis=1)
        cell = int(idx[int(np.argmin(dist))])
        desc = _descriptors_at(f, cell)
        cls = classify_v1(desc, is_land=bool(land[cell]))
        entries.append(
            {
                "name": f"类中心代表点（{code}）",
                "ctx": "自动补充：命名地点未覆盖该类",
                "cell": cell,
                "lat": float(lat[cell]),
                "lon": float(lon[cell]),
                "desc": desc,
                "cls": cls,
                "koppen": str(koppen[cell]),
                "t12": t_monthly[cell],
                "p12": p_monthly[cell],
                "medoid": True,
            }
        )
        print(f"Top-up medoid for class {code}: cell #{cell} ({lat[cell]:.1f}, {lon[cell]:.1f})")

    # --- Document ----------------------------------------------------------
    prov = d.get("provenance", {})
    out_lines = [
        "# Earth · UCC Worked Examples（profile v1）",
        "",
        "> UCC-01 第四步 4c 产物，同时是 4b 创作验收的审阅清单（v1 标签对照地理直觉，",
        "> 逐站点人工判读）。本文档由脚本生成，勿手改——重生成：",
        "> `uv run python scripts/climate/ucc_examples_earth.py`。",
        f"> 生成日期：{datetime.date.today().isoformat()} · profile：{PROFILE_CURRENT}",
        f"> （`classify_v1`）· 数据集：`{args.dataset.name}`",
        ">",
        f"> 数据源（观测，非引擎输出）：温度 {prov.get('temperature', '—')}；",
        f"> 降水 {prov.get('precipitation', '—')}；Köppen 参照列 {prov.get('koppen_obs', '—')}；",
        f"> 参考需求 {prov.get('demand_model', '—')}。",
        "> 月度序列 month 0 = 三月（春分）——与引擎约定一致（观测导入器已重排）。",
        "> 读法与描述量语义见 `docs/ucc/specification.md`；",
        "> 分类阈值与简码字母表见该文 §5。",
        "> **状态简写**（表格中替代完整状态名）：`OOD` = out_of_domain（需求模型超出",
        "> 有效域——如冰盖全年无液态水，AI/deficit 不报数）；`MI` = missing_input、",
        "> `NA` = not_applicable、`NPD` = no_positive_demand（本表未出现；语义见该文 §3）。",
        "",
        "## 摘要表（审阅入口）",
        "",
        "| # | 站点 | 纬度 | 经度 | T均 °C | T范围 °C | P mm/年 | AI | deficit"
        " | UCC v1 | 修饰语 | Beck Köppen |",
        "|---|------|------|------|--------|----------|---------|----|---------|"
        "--------|--------|-------------|",
    ]
    for i, e in enumerate(entries, start=1):
        desc, cls = e["desc"], e["cls"]
        mods = ("x" if cls.continental else "") + ("w" if cls.water_stress else "")
        ai_s = _fmt(desc.ai) if desc.ai_status == "valid" else status_short(desc.ai_status)
        def_s = (
            _fmt(desc.deficit)
            if desc.deficit_status == "valid"
            else status_short(desc.deficit_status)
        )
        out_lines.append(
            f"| {i} | {e['name']} | {e['lat']:.1f} | {e['lon']:.1f} | {desc.t_mean:.1f}"
            f" | {desc.t_range:.1f} | {desc.p_total:.0f} | {ai_s} | {def_s}"
            f" | **{cls.code}** | {mods or '—'} | {e['koppen'] or '—'} |"
        )
    out_lines += ["", "## 逐站点详情", ""]
    for i, e in enumerate(entries, start=1):
        out_lines += _site_block(
            i,
            e["name"],
            e["ctx"],
            e["cell"],
            e["lat"],
            e["lon"],
            e["t12"],
            e["p12"],
            e["desc"],
            e["cls"],
            e["koppen"],
        )

    # --- Coverage check -----------------------------------------------------
    out_lines += ["## 类覆盖检查", ""]
    thermal_letters = {"polar": "P", "cold": "C", "temperate": "T", "tropical": "R"}
    supply_letters = {"arid": "a", "semi_arid": "s", "transitional": "t", "humid": "h"}
    land_codes = [
        thermal_letters[t] + supply_letters[s]
        for t in THERMAL_BANDS_CURRENT
        for s in SUPPLY_BANDS_CURRENT
    ] + ["Pn", "Cn", "Tn", "Rn"]
    ocean_codes = [thermal_letters[t] + "o" for t in THERMAL_BANDS_CURRENT]
    out_lines += [
        "| 类 | cell 数 | 占陆地/海洋 % | 命名站点覆盖 |",
        "|----|---------|----------------|--------------|",
    ]
    named_only = {e["cls"].code.split("-")[0] for e in entries if not e["medoid"]}
    for code in land_codes:
        cnt = int((base_codes == code).sum())
        pct = cnt / land.sum() * 100
        hit = "✓" if code in named_only else ("中心点" if cnt else "—")
        out_lines.append(f"| {code} | {cnt} | {pct:.1f}% | {hit} |")
    for code in ocean_codes:
        cnt = int((base_codes == code).sum())
        pct = cnt / (~land).sum() * 100
        hit = "✓" if code in named_only else ("中心点" if cnt else "—")
        out_lines.append(f"| {code}（海洋） | {cnt} | {pct:.1f}% | {hit} |")
    out_lines += [
        "",
        "注：类计数为 200k CVT cell 的等权计数，非面积加权；海洋类「占海洋 %」。",
        "主类计数已聚合修饰语后缀（Tt 与 Tt-w 同类）；摘要表/详情里的简码带后缀。",
        "`n` 槽位 = 陆地但供需轴不适用（如冰盖 out_of_domain）；`o` = 海洋（热量带照给，",
        "干湿轴 not_applicable）。",
        "",
    ]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"Wrote {args.out} ({len(entries)} sites)")


if __name__ == "__main__":
    main()
