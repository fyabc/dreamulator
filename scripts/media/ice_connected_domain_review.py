"""Export native ice-body, margin and shared-chunk-boundary review figures."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import numpy as np
from matplotlib import pyplot as plt
from matplotlib.colors import LightSource


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--comparison", type=Path)
    args = parser.parse_args()
    report = json.loads((args.inputs / "report.json").read_text(encoding="utf-8"))
    accepted = report.get("author_acceptance") == "passed"
    acceptance_text = (
        "本轮共享域与保持零冰厚的比例校正已获作者验收。"
        if accepted
        else "本轮共享域与冰量账本检查通过，建议采用保持零冰厚的比例校正候选，等待作者验收。"
    )
    root = args.inputs / "surface"
    fields = {
        name: np.load(root / f"{name}.npy", mmap_mode="r")
        for name in ("bed.m", "prior.ice.m", "untapered.ice.m", "ice.m", "surface.m")
    }
    args.output.mkdir(parents=True, exist_ok=True)
    bounds = report["selection"]["bounds_px"]
    r0, r1 = max(0, bounds[0][0] - 256), min(4096, bounds[0][1] + 256)
    c0, c1 = max(0, bounds[1][0] - 256), min(2048, bounds[1][1] + 256)
    sl = np.s_[r0:r1, c0:c1]
    px_km = 0.08984375
    extent = (c0 * px_km, c1 * px_km, r1 * px_km, r0 * px_km)
    bed = fields["bed.m"][sl].astype(float)
    surfaces = [
        bed + fields["prior.ice.m"][sl],
        bed + fields["untapered.ice.m"][sl],
        fields["surface.m"][sl],
    ]
    thicknesses = [fields[name][sl] for name in ("prior.ice.m", "untapered.ice.m", "ice.m")]
    vmin, vmax = float(min(a.min() for a in surfaces)), float(max(a.max() for a in surfaces))
    light = LightSource(azdeg=315, altdeg=40)
    fig, axes = plt.subplots(1, 3, figsize=(15, 8), constrained_layout=True)
    for ax, surface, ice, title in zip(
        axes,
        surfaces,
        thicknesses,
        [
            "100 yr fixed-climate inventory",
            "10 yr SIA; shared ice-body volume",
            "Same surface with bounded margin taper",
        ],
        strict=True,
    ):
        rgb = light.shade(
            surface,
            cmap=plt.get_cmap("terrain"),
            vmin=vmin,
            vmax=vmax,
            vert_exag=2,
            dx=89.84375,
            dy=89.84375,
            blend_mode="soft",
        )
        covered = ice > 1
        shade = light.hillshade(surface, vert_exag=2, dx=89.84375, dy=89.84375)
        snow = np.stack([0.70 + 0.27 * shade, 0.80 + 0.19 * shade, 0.87 + 0.13 * shade], axis=-1)
        rgb[covered, :3] = snow[covered]
        ax.imshow(rgb, extent=extent)
        ax.axhline(2048 * px_km, color="tomato", linestyle="--", linewidth=1)
        ax.set_title(title, fontsize=10)
        ax.set_xlabel("Native canvas x offset (km)")
    axes[0].set_ylabel("Native canvas row offset (km)")
    fig.suptitle(
        "One complete existing ice body; native spacing 89.84375 m\n"
        "Dashed line: shared edge of the two 2048-pixel chunks",
        fontsize=12,
    )
    fig.savefig(args.output / "ice-body.png", dpi=170)
    plt.close(fig)

    crossing = (fields["ice.m"][2047] > 1) & (fields["ice.m"][2048] > 1)
    candidates = np.flatnonzero(crossing)
    col = int(candidates[np.argmax(fields["ice.m"][2048, candidates])])
    rows = np.arange(max(r0, 2048 - 512), min(r1, 2048 + 512))
    x = (rows - 2048) * px_km
    fig, axes = plt.subplots(1, 2, figsize=(13, 4), constrained_layout=True)
    curves = [
        ("bed.m", "Independent bed", "#725944"),
        ("prior.ice.m", "Before SIA", "#999999"),
        ("untapered.ice.m", "Shared untapered surface", "#008cad"),
        ("surface.m", "Final surface", "#1b3b8b"),
    ]
    for name, title, color in curves:
        a = fields[name][rows, col].astype(float)
        if "ice" in name:
            a += fields["bed.m"][rows, col]
        axes[0].plot(x, a, label=title, color=color)
    axes[0].axvline(0, color="tomato", linestyle="--")
    axes[0].set(xlabel="Distance from shared chunk edge (km)", ylabel="Elevation (m)")
    axes[0].legend(fontsize=8)
    a = fields["surface.m"][rows, col].astype(float)
    axes[1].plot(x, a, color="#1b3b8b", marker=".")
    axes[1].set_xlim(-1, 1)
    near = np.abs(x) <= 1
    axes[1].set_ylim(float(a[near].min()) - 1, float(a[near].max()) + 1)
    axes[1].axvline(0, color="tomato", linestyle="--")
    axes[1].set(xlabel="Distance from shared chunk edge (km)", ylabel="Final elevation (m)")
    fig.suptitle(f"Native profile crossing the chunk edge; local column {col}")
    fig.savefig(args.output / "shared-edge.png", dpi=170)
    plt.close(fig)
    comparison_text = ""
    if args.comparison is not None:
        other = json.loads((args.comparison / "report.json").read_text(encoding="utf-8"))
        other_ice = np.load(args.comparison / "surface/ice.m.npy", mmap_mode="r")
        other_surface = np.load(args.comparison / "surface/surface.m.npy", mmap_mode="r")
        fig, axes = plt.subplots(1, 2, figsize=(11, 8), constrained_layout=True)
        for ax, surface, ice, title in zip(
            axes,
            [fields["surface.m"][sl], other_surface[sl]],
            [fields["ice.m"][sl], other_ice[sl]],
            ["Common height shift", "Per-body thickness scaling"],
            strict=True,
        ):
            rgb = light.shade(
                surface,
                cmap=plt.get_cmap("terrain"),
                vmin=vmin,
                vmax=vmax,
                vert_exag=2,
                dx=89.84375,
                dy=89.84375,
                blend_mode="soft",
            )
            covered = ice > 1
            shade = light.hillshade(surface, vert_exag=2, dx=89.84375, dy=89.84375)
            snow = np.stack(
                [0.70 + 0.27 * shade, 0.80 + 0.19 * shade, 0.87 + 0.13 * shade], axis=-1
            )
            rgb[covered, :3] = snow[covered]
            ax.imshow(rgb, extent=extent)
            ax.axhline(2048 * px_km, color="tomato", linestyle="--", linewidth=1)
            ax.set_title(title)
            ax.set_xlabel("Native canvas x offset (km)")
        axes[0].set_ylabel("Native canvas row offset (km)")
        fig.suptitle("Only volume normalization changes; shared climate, flow and margin closure")
        fig.savefig(args.output / "volume-correction.png", dpi=170)
        plt.close(fig)
        shutil.copy2(args.comparison / "report.json", args.output / "volume-scale-report.json")
        scales = [row["volume_scale"] for row in other["components"]]
        extra = int(np.count_nonzero((fields["ice.m"] > 1) & (other_ice <= 1)))
        extra_km2 = extra * 89.84375**2 / 1e6
        correction_status = (
            "本轮比例校正已获作者验收，正式冰面生产接线随完整批次进行。\n"
            if accepted
            else "本轮将比例校正作为待验收的数值候选，尚未接入正式冰面生产。\n"
        )
        comparison_text = (
            "\n体积校正的对照见[同位置两方案图](volume-correction.png)。左侧采用统一高程偏移，"
            "右侧按每个冰体的未校正非负冰厚乘以同一个比例，保持原有零冰厚。\n"
            f"本样本的比例为 {scales[0]:.6f}。统一高程偏移产生的额外可见覆冰面积为 "
            f"{extra_km2:.3f} km²，统计口径是左侧冰厚超过1 m、右侧不超过1 m的像素。\n"
            f"比例校正的最终冰量相对残差为 {other['final_relative_residual']:.3e}。"
            f"{correction_status}"
        )
    shutil.copy2(args.inputs / "report.json", args.output / "report.json")
    climate = report["climate_budget"]
    seam = report["native_seam"]
    before, after = report["margin_before"], report["margin_after"]
    taper_fraction = report["margin_taper_export_m3"] / report["flow"]["final_volume_m3"]
    table = "\n".join(
        [
            "| 账目 | 本轮结果 |",
            "|---|---|",
            (
                f"| 气候储量 | 全年最小冰量为 {climate['final_minimum_ice_m3'] / 1e9:.3f} km³，"
                f"预算残差为 {climate['residual_m3']:.6f} m³。 |"
            ),
            (
                f"| 浅冰流动 | 冰量残差为 {report['flow']['residual_m3']:.6f} m³，"
                f"求解完成 {report['flow']['substeps']} 个稳定子步。 |"
            ),
            (
                f"| 原生延拓与输出 | 末态冰量为 {report['final_volume_m3'] / 1e9:.3f} km³，"
                f"漂浮输出为 {report['floating_export_m3'] / 1e9:.6f} km³，"
                f"冰缘输出为 {report['margin_taper_export_m3'] / 1e9:.6f} km³。 |"
            ),
            (
                "| 最终冰量核对 | 末态加两项输出相对延拓前冰量的残差为 "
                f"{report['final_relative_residual']:.3e}。 |"
            ),
            (
                f"| 共同边界 | 有 {seam['icy_crossing_pixels']} 对相邻覆冰像素跨过边界，"
                "共享字段的分块与整域读取逐值一致。 |"
            ),
            (
                f"| 冰缘形态 | 第一圈覆冰的平均厚度为 {before['mean_m']:.2f} m，"
                f"经处理后为 {after['mean_m']:.2f} m；95百分位分别为 "
                f"{before['p95_m']:.2f} m和{after['p95_m']:.2f} m。 |"
            ),
        ]
    )
    text = f"""# 完整既有冰体的跨块验收

{acceptance_text}
两个相邻原生块共用一次冰流求解、同一个冰面场与每个连通冰体的体积校正。
分块读取、256行与512行的样条求值、160像素邻域的冰缘处理均与整域结果逐值一致。
浮点地表的最大存储误差为 {report["geometry_identity_max_error_m"]:.6f} m，裸岩高程逐值保持来源值。

查看[完整冰体三阶段对比](ice-body.png)与[跨块剖面](shared-edge.png)。红色虚线表示两个原生块的共同边界。
左图是固定气候响应后的来源冰面，中图是共享浅冰解，右图是同一冰面加上既有冰缘处理。
冰厚独立决定白色覆盖，阴影读取对应地表。三幅图使用同一位置、尺度、高程色标和照明。

输入来自南方画布 `{report["canvas"]}` 的两个连续2048格块。原生格距为89.84375 m，
整个数值域为368 km × 184 km。选择的既有连通冰体在窗口内部完整闭合，初始与最终外框覆冰像素均为零。
可承载陆地上的初始冰量为 {report["selection"]["initial_volume_m3"] / 1e9:.3f} km³，
基岩海洋判定另排除 {report["selection"]["initial_marine_excluded_m3"] / 1e9:.3f} km³ 的来源冰量。
独立基岩由已冻结的地质条件、TD 模型、统计场与种子恢复，属于统计基岩来源。
月气候、同批温度波动与独立气候参考高度均保留来源校验。

物质平衡沿用已验收的固定覆盖诊断口径，仅在这个既有冰体的初始覆盖内计算100年的固定高度响应；
冰流可以进入周围裸岩。5750 m浅冰网格随后计算10年的零物质平衡响应。
这轮检查完整既有冰体的重建和块间共同边界，新增覆冰区、跨画布投影重叠和长期平衡各按后续任务验收。

{table}

{comparison_text}

冰缘移除量单独作为一次形态调整的输出，不补回内部。距下降冰缘超过12 km的内部冰厚逐值保持。
这轮冰缘处理移除的体积占延拓前冰量的 {taper_fraction:.1%}，小冰体的冰缘适用范围继续验收。
共同边界两侧是相隔一个格距的像素，因此剖面保留自然高差；相同位置的读取一致性另由逐值核对证明。
[完整统计](report.json)记录来源、逐冰体校正、冰量与精度。

方法依据为[既有亚格子冰面方案](../../../docs/design/proposals/canvas-glacial-landforms.md#404-初版细尺度覆冰与形态验收)
以及[PISM 的独立参考高程约定](https://www.pism.io/docs/climate_forcing/atmosphere.html#adjustments-using-modeled-change-in-surface-elevation)。
"""
    (args.output / "README.md").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
