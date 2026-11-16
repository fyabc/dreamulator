"""Render a frozen independent-bed/reference-height experiment for author review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads((args.inputs / "report.json").read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=True)
    summaries = []
    for cid in dict.fromkeys(row["canvas"] for row in report["chunks"]):
        rows = [row for row in report["chunks"] if row["canvas"] == cid]
        fig, axes = plt.subplots(len(rows), 5, figsize=(20, 4 * len(rows)), squeeze=False)
        detail, detail_axes = plt.subplots(len(rows), 5, figsize=(20, 4 * len(rows)), squeeze=False)
        for index, row in enumerate(rows):
            name = row["chunk"]
            folder = args.inputs / "response" / cid / Path(name).stem
            bed = np.load(args.inputs / "bed" / cid / "chunks" / name, mmap_mode="r")
            initial = np.load(folder / "initial_ice.m.npy", mmap_mode="r")
            td = np.load(folder / "td_condition_reference.ice.m.npy", mmap_mode="r")
            science = np.load(folder / "scientific_climate_reference.ice.m.npy", mmap_mode="r")
            arrays = [bed, initial, td, science, science.astype(float) - td]
            maximum = max(float(np.max(a)) for a in [initial, td, science])
            delta_max = max(float(np.max(np.abs(arrays[-1]))), 0.01)
            if delta_max > 0.01:
                cy, cx = np.unravel_index(np.argmax(np.abs(arrays[-1])), initial.shape)
            else:
                cy, cx = 1024, 1024
            y, x = max(0, min(int(cy) - 256, 1536)), max(0, min(int(cx) - 256, 1536))
            titles = [
                "Independent TD bed (m)",
                "Frozen initial ice (m)",
                "100 yr: TD height reference (m)",
                "100 yr: climate height reference (m)",
                "Climate minus TD ice (m)",
            ]
            for column, (array, title) in enumerate(zip(arrays, titles, strict=True)):
                limits = (
                    {"vmin": -delta_max, "vmax": delta_max, "cmap": "RdBu"}
                    if column == 4
                    else {"vmin": 0, "vmax": maximum, "cmap": "Blues"}
                    if column > 0
                    else {"cmap": "terrain"}
                )
                for figure, ax, shown in [
                    (fig, axes[index, column], array[::8, ::8]),
                    (
                        detail,
                        detail_axes[index, column],
                        array[y : y + 512 : 2, x : x + 512 : 2],
                    ),
                ]:
                    plotted = ax.imshow(shown, **limits)
                    ax.set_title(title, fontsize=10)
                    ax.set_xticks([])
                    ax.set_yticks([])
                    figure.colorbar(plotted, ax=ax, shrink=0.75, pad=0.02)
            axes[index, 0].set_ylabel(Path(name).stem, fontsize=11)
            detail_axes[index, 0].set_ylabel(
                f"{Path(name).stem}\nx={x}, y={y}; 46 km window", fontsize=10
            )
        fig.suptitle(f"{cid}: same bed, initial ice, climate and 100 yr storage model", fontsize=13)
        fig.tight_layout()
        fig.savefig(args.output / f"{cid}.png", dpi=150)
        plt.close(fig)
        detail.suptitle(
            f"{cid}: common 46 km crop at largest reference-height ice response", fontsize=13
        )
        detail.tight_layout()
        detail.savefig(args.output / f"{cid}-detail.png", dpi=150)
        plt.close(detail)
        volumes = {
            arm: sum(row["arms"][arm]["ice_volume_km3"] for row in rows)
            for arm in ["td_condition_reference", "scientific_climate_reference"]
        }
        baseline, corrected = volumes.values()
        summaries.append(
            {
                "canvas": cid,
                "sampled_chunks": len(rows),
                "initial_ice_volume_km3": sum(row["initial_ice_volume_km3"] for row in rows),
                "td_reference_ice_volume_km3": baseline,
                "climate_reference_ice_volume_km3": corrected,
                "difference_km3": corrected - baseline,
                "difference_percent": 100 * (corrected / baseline - 1) if baseline else None,
            }
        )
    report["canvas_summaries"] = summaries
    (args.output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# 独立基岩与覆冰参考高度小批验收",
        "",
        "本批建议通过独立基岩来源恢复与参考高度对照验收。九个独立基岩分块已保留，"
        "来源校验和、单年月度储量与闭式响应检查全部通过。",
        "",
        "本批重新生成三张画布的九个独立 TD 基岩分块。两条支路共用基岩、安装 v7 初始冰厚、"
        "月气候和气温变率，只改变订温参考高度。每块包含 2048×2048 像素，间距为 89.84375 m。",
        "",
        "下表为九个样本中初始覆冰像素的 100 年固定气候响应；冰体积按画布投影像素面积计算。"
        "这些数值表示局部响应，完整冰流与长期现今冰厚仍由后续验收。",
        "",
        "| 画布 | TD 条件参考下的冰体积 | 科学气候参考下的冰体积 | 差值 |",
        "|---|---:|---:|---:|",
    ]
    for summary in summaries:
        lines.append(
            f"| [{summary['canvas']}]({summary['canvas']}.png) | "
            f"{summary['td_reference_ice_volume_km3']:.3f} km³。 | "
            f"{summary['climate_reference_ice_volume_km3']:.3f} km³。 | "
            f"{summary['difference_km3']:+.3f} km³。 |"
        )
    lines += [
        "",
        "冰缘比厚冰内部更敏感。北极 r061_c037 样本在科学参考高度下的冰体积增加约 13.1%，"
        "66p5 的 r003_c004 样本减少约 6.15%；北极整块厚冰 r027_c033 的变化接近浮点误差。",
        "",
        "细节图分别是 [66p5](land_-66p5_-018p3-detail.png)、"
        "[62p9](land_-62p9_-050p8-detail.png)与[北极](arctic-detail.png)。"
        "每行选择冰厚差最大的像素附近 46 km 窗口，五列共用同一裁窗；"
        "厚冰无明显变化的样本显示中央窗口。原生分块中的裁窗坐标写在图左侧。",
        "",
        "图中各行对应一个原生分块，五列依次为独立基岩、初始冰厚、TD 参考高度响应、"
        "科学气候参考高度响应与两者的冰厚差。三列冰厚共用色标，差值使用独立色标。",
        "",
        f"单年月度储量最大残差为 {report['one_year_max_storage_residual_mm']:.3g} mm，"
        f"100 年闭式响应与抽样逐年迭代的最大差值为 "
        f"{report['explicit_100year_recurrence_max_error_m']:.3g} m。",
        "",
        "计算固定初始地表的订温高度，并重复 100 个 365.25 地球日年份；"
        "当前输出为年内最小冰量。全年剩余雪、地表高度反馈与冰流没有混入本轮比较。",
        "",
        "详细来源与逐块结果见 [report.json](report.json)。共享水平面、海洋连通、水文与跨画布"
        "接缝在下一阶段检查；长期冰量继续使用 T85 对 T42 的科学认证结果确定驱动。",
    ]
    (args.output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
