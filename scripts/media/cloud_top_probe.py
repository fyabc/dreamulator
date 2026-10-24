"""QA probe: diagnose the pack's cloud-top height field for the two-shell split.

The pack's ``cloud_top_height`` is the random-overlap expected height of the
topmost cloud a space view would see (NaN = clear).  This probe maps its
latitude-season structure, its full distribution, and scans split thresholds
to ground the deck/cirrus classification (S4) in the data: where the visible
top sits low the pixel belongs to the deck shell, where it sits high to the
cirrus shell.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from dreamulator.gcm.weather_pack import load_pack

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

PACK = Path("exports/weather/nacrea-gcm-t42-712")
OUT = Path("exports/globe")


def main() -> None:
    pack = load_pack(PACK)
    cth = np.asarray(pack.field("cloud_top_height"), dtype=np.float64)
    ch = np.asarray(pack.field("cloud_high"), dtype=np.float64)
    ct = np.asarray(pack.field("cloud_total"), dtype=np.float64)
    lat = np.asarray(pack.lat, dtype=float)
    n_frames = cth.shape[0]
    cloudy = ~np.isnan(cth)

    # ---- 1) Hovmöller: cloud-top height (cloud-frequency weighted) ----
    step = 3  # 18-h sampling; the annual structure is far coarser than this
    z = np.where(cloudy, cth, 0.0)[::step]
    w = cloudy[::step].astype(np.float64)
    zonal_z = z.sum(axis=2) / np.maximum(w.sum(axis=2), 1.0)  # (T, lat)
    zonal_f = w.mean(axis=2)
    frames = np.arange(n_frames)[::step]
    hours = np.asarray(pack.meta["time"]["hours_since_start"], dtype=float)[::step]

    fig, axes = plt.subplots(
        2, 1, figsize=(10, 8), sharex=True, constrained_layout=True
    )
    for ax, field, title, cmap, vmax in (
        (axes[0], zonal_z, "可见云顶高度（云频加权纬向平均, km）", "viridis", 16.0),
        (axes[1], zonal_f, "云频率（非晴空比例）", "magma", 1.0),
    ):
        im = ax.pcolormesh(
            hours / 24.0, lat, field.T, cmap=cmap, vmin=0.0, vmax=vmax, shading="auto"
        )
        ax.set_ylabel("纬度 (°)")
        ax.set_title(title)
        fig.colorbar(im, ax=ax, pad=0.01)
    axes[1].set_xlabel("模式时间 (d)")
    axes[0].text(
        0.01,
        0.03,
        f"frames 0–{n_frames - 1} · {len(frames)} 列（18 h 采样）",
        transform=axes[0].transAxes,
        color="white",
        fontsize=8,
    )
    fig.savefig(OUT / "_cloud-top-probe-hovmoller.png", dpi=150)
    plt.close(fig)

    # ---- 2) Distribution of all valid tops + annual zonal profile ----
    v = cth[cloudy]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
    axes[0].hist(v, bins=np.arange(0.0, 24.5, 0.5), color="#4c72b0")
    axes[0].set_yscale("log")
    axes[0].set_xlabel("可见云顶高度 (km)")
    axes[0].set_ylabel("格子数（对数）")
    axes[0].set_title(f"全年分布 · 晴空 {1.0 - cloudy.mean():.1%}")
    for q in (10, 50, 90):
        axes[0].axvline(
            np.percentile(v, q), color="k", ls=":", lw=1,
            label=f"p{q} = {np.percentile(v, q):.1f} km",
        )
    axes[0].legend(fontsize=8)

    mean_top = np.where(cloudy, cth, np.nan).mean(axis=(0, 2))
    freq = cloudy.mean(axis=(0, 2))
    ax2 = axes[1]
    ax2.plot(lat, mean_top, color="#4c72b0", label="平均云顶高度 (km)")
    ax2.plot(lat, freq * 16.0, color="#dd8452", ls="--", label="云频率 ×16")
    ax2.set_xlabel("纬度 (°)")
    ax2.set_ylabel("km / ×16")
    ax2.set_title("年均纬向剖面")
    ax2.legend(fontsize=8)
    fig.savefig(OUT / "_cloud-top-probe-dist.png", dpi=150)
    plt.close(fig)

    # ---- 3) Split-threshold scan: fraction of cloud assigned to cirrus ----
    # Weight each cloudy cell by its total cloud amount: the split moves
    # opacity, not pixels, so the cirrus share of opacity is what the renderer
    # cares about.
    opacity = np.where(cloudy, ct, 0.0)
    op_total = opacity[cloudy].sum()
    print("分界阈值扫描（云顶 ≥ z* 的不透明度份额 = 高壳占比）:")
    print("  z*(km)  cirrus_share  对照: high/(low+mid+high) 云量比例的全球份额")
    ratio_share = float(ch[cloudy].sum() / np.maximum(ct[cloudy].sum(), 1e-9))
    scan = np.arange(4.0, 12.5, 0.5)
    shares = []
    for z_star in scan:
        share = float(opacity[cloudy & (cth >= z_star)].sum() / op_total)
        shares.append(share)
        print(f"  {z_star:5.1f}   {share:6.3f}")
    print(f"  云量比例口径的高壳份额 = {ratio_share:.3f}")

    fig, ax = plt.subplots(figsize=(7, 4), constrained_layout=True)
    ax.plot(scan, shares, "o-", color="#4c72b0", label="云顶 ≥ z* 的高壳不透明度份额")
    ax.axhline(ratio_share, color="#dd8452", ls="--", label=f"云量比例口径 {ratio_share:.2f}")
    ax.set_xlabel("分界阈值 z* (km)")
    ax.set_ylabel("高壳份额")
    ax.set_title("两层分配的分界阈值扫描")
    ax.legend(fontsize=8)
    fig.savefig(OUT / "_cloud-top-probe-threshold.png", dpi=150)
    plt.close(fig)
    print(f"\nwrote 3 probes to {OUT}/_cloud-top-probe-*.png")


if __name__ == "__main__":
    main()
