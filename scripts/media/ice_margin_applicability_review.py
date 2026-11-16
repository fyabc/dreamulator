"""Compare bounded ice-margin footprints using a frozen native ice body."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import numpy as np
from matplotlib import pyplot as plt
from matplotlib.colors import LightSource

from dreamulator.map.canvas_ice_surface import margin_taper


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.inputs, args.output
    out.mkdir(parents=True, exist_ok=True)
    report = json.loads((root / "diagnosis.json").read_text(encoding="utf-8"))
    plan = json.loads((root / "plan.json").read_text(encoding="utf-8"))
    px = plan["pixel_m"]
    sl = np.s_[1632:3140, 279:1577]
    extent = (279 * px / 1000, 1577 * px / 1000, 3140 * px / 1000, 1632 * px / 1000)
    names = ["untapered", "existing_12km", "solver_spacing_5750m"]
    titles = ["Before margin adjustment", "Existing 12 km footprint", "5.75 km footprint candidate"]
    surfaces = [np.load(root / f"{name}.surface.m.npy", mmap_mode="r")[sl] for name in names]
    vmin, vmax = min(float(a.min()) for a in surfaces), max(float(a.max()) for a in surfaces)
    light = LightSource(azdeg=315, altdeg=40)
    fig, axes = plt.subplots(1, 3, figsize=(15, 8), constrained_layout=True)
    for ax, name, title, surface in zip(axes, names, titles, surfaces, strict=True):
        ice = np.load(root / f"{name}.ice.m.npy", mmap_mode="r")[sl]
        rgb = light.shade(
            surface,
            cmap=plt.get_cmap("terrain"),
            vmin=vmin,
            vmax=vmax,
            vert_exag=2,
            dx=px,
            dy=px,
            blend_mode="soft",
        )
        shade = light.hillshade(surface, vert_exag=2, dx=px, dy=px)
        snow = np.stack([0.70 + 0.27 * shade, 0.80 + 0.19 * shade, 0.87 + 0.13 * shade], axis=-1)
        covered = ice > 1
        rgb[covered, :3] = snow[covered]
        ax.imshow(rgb, extent=extent)
        ax.set_title(title, fontsize=11)
        ax.set_xlabel("Native x offset (km)")
    axes[0].set_ylabel("Native row offset (km)")
    fig.suptitle("Same complete ice body; fixed climate, ice flow and volume correction")
    fig.savefig(out / "ice-body.png", dpi=160)
    plt.close(fig)

    # These slabs are prescribed numerical stress tests, not observed glaciers.
    distance = np.arange(1, 1401) * px
    benchmarks = []
    fig, axes = plt.subplots(1, 2, figsize=(12, 4), constrained_layout=True)
    for thickness, ax in zip((450.0, 2000.0), axes, strict=True):
        h = np.full(distance.shape, thickness)
        row = dict(prescribed_ice_thickness_m=thickness, native_pixel_m=px)
        for width, color in [(12000.0, "#3155aa"), (5750.0, "#d8681e")]:
            result = margin_taper(h, distance, gravity_m_s2=10.28, band_limit_m=width)
            ax.plot(distance / 1000, result, color=color, label=f"{width / 1000:g} km footprint")
            row[f"first_pixel_{int(width)}m"] = float(result[0])
        ax.set(
            xlim=(0, 15),
            xlabel="Distance from prescribed ice-free edge (km)",
            ylabel="Ice thickness (m)",
        )
        ax.set_title(f"Prescribed {thickness:g} m flat-bed slab")
        ax.legend(fontsize=9)
        benchmarks.append(row)
    fig.suptitle(
        "Synthetic sensitivity check; each plot keeps ice thickness and yield stress fixed"
    )
    fig.savefig(out / "thick-margin-control.png", dpi=160)
    plt.close(fig)
    report["synthetic_margin_controls"] = benchmarks
    report["recommendation"] = (
        "Keep the accepted 12 km default. The one-cell footprint helps this small body, "
        "but increases the residual cliff of prescribed thick margins. Improve near-margin "
        "surface reconstruction before adopting a universal footprint change."
    )
    report["author_acceptance"] = "pending"
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    rows = []
    for name, label in zip(names, ["处理前", "现行12 km", "候选5.75 km"], strict=True):
        r = report["arms"][name]
        rows.append(
            f"| {label} | {r['export_fraction']:.1%} | {r['first_ring_mean_m']:.1f} m | "
            f"{r['first_ring_p95_m']:.1f} m | {r['first_ring_max_m']:.1f} m |"
        )
    table = "\n".join(rows)
    native = report["native_enclosed_comparison"]["loss_fraction"]
    thick = benchmarks[1]
    text = f"""# 小冰体的冰缘处理诊断

本轮诊断通过。建议保持现行12 km默认值；缩窄处理带在这个小冰体上有收益，但会增高厚冰缘留下的冰崖。
下一步处理冰缘附近的冰面重建，使冰面在到达裸地前下降。本轮等待作者验收，正式产品保持当前状态。

查看[同位置三方案图](ice-body.png)与[合成厚冰缘对照](thick-margin-control.png)。
三方案共用上一批已验收的独立基岩、冰量、冰流、海洋判定和比例体积校正；这轮只重算冰缘处理。
原生格距为89.84375 m，样本是两个连续原生块上的同一个完整既有冰体。
下表的第一圈指冰厚超过1 m、距下降冰缘不超过1.5个原生格距的像素，包含对角相邻格。

| 方案 | 移除冰量比例 | 第一圈平均冰厚 | 第一圈冰厚95百分位 | 第一圈最大冰厚 |
|---|---|---|---|---|
{table}

主要原因是处理范围覆盖了小冰体的大部分面积。约76%的移除量发生在距下降冰缘超过1 km处，
约31%发生在5 km到12 km之间。改用原生像素精度识别被包围的无冰区，移除比例为{native:.1%}，
说明边界识别精度对本样本的影响很小。分块边界与冰量账本已由上一轮验收，不是本轮的待解问题。

5.75 km取自现有浅冰求解格距，用于检验把整形范围缩到一个求解格的影响，不据此标定新的物理长度。
在小冰体上，它把移除量从约25.1%降至14.0%，同时保留较低的边缘冰厚。
合成厚冰缘把未处理冰厚固定为2000 m，并把裸地边界和89.84375 m格距固定。
第一格的残余冰崖由{thick["first_pixel_12000m"]:.1f} m增到{thick["first_pixel_5750m"]:.1f} m。
当厚冰由带限支控制时，这一高度按带宽的平方根反比变化；因此缩带的代价会在厚冰缘放大。
合成对照用于验证公式的敏感性，不提供真实冰盖的形态观测。

现行塑性剖面来自平床、恒定屈服应力的近似。完整条件是冰厚乘以冰面坡度决定驱动应力；
在有坡度的基岩上，冰面坡度包含基岩与冰厚两部分。PISM使用实际冰面坡度并专门处理冰缘和粗糙基岩，
Reeh的塑性冰盖研究也明确区分平床剖面与任意床面的重建。
本轮的带宽和边界识别对照定位了数值处理的影响，并未证明这个架空冰体的真实平衡冰量应增减多少。

资料为[PISM浅冰近似](https://www.pism.io/docs/manual/modeling-choices/dynamics/sia.html)和
[Reeh（1982）的三维塑性冰盖重建](https://www.cambridge.org/core/journals/journal-of-glaciology/article/plasticity-theory-approach-to-the-steadystate-shape-of-a-threedimensional-ice-sheet/94C3B58F89AC51972613D72D0B42E93D)。
[完整统计](report.json)提供距离分组、应力描述、原生边界对照和各方案冰量。
"""
    (out / "README.md").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
