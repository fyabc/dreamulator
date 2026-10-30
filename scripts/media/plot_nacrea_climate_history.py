"""Plot Nacrea's recorded historical reference without rerunning any model."""

from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/worlds/nacrea/design-notes/assets/0021-heat-co2-ice-history.csv"
OUTPUT = ROOT / "exports/mosaic/20261030-v2/history/nacrea-setting-history.png"


def main() -> None:
    rows = np.genfromtxt(SOURCE, delimiter=",", names=True)
    font = next(
        font
        for name in ["WenQuanYi Zen Hei", "Microsoft YaHei", "DejaVu Sans"]
        for font in font_manager.fontManager.ttflist
        if font.name == name
    )
    plt.rcParams.update(
        {
            "font.family": [font.name],
            "font.weight": font.weight,
            "axes.titleweight": font.weight,
            "axes.labelweight": font.weight,
            "axes.unicode_minus": False,
            "font.size": 11,
        }
    )
    fig, axes = plt.subplots(3, 1, figsize=(11.5, 10), sharex=True, layout="constrained")
    time = rows["lookback_yr"] / 10000
    axes[0].plot(time, rows["tidal_heat_w_m2"], color="#216a91")
    axes[0].set(title="Nacrea 最近200万年的历史参考", ylabel="全球潮汐热流（W/m²）")
    for ax, prefix, suffix, scale, color, title, unit in [
        (axes[1], "co2", "ppm", 1, "#a85c25", "脱气与风化的碳库存响应", "CO₂（ppm）"),
        (
            axes[2],
            "grounded_ice",
            "m3",
            1e15,
            "#286876",
            "全球陆地冰量的参考估算",
            "陆地冰体积（百万km³）",
        ),
    ]:
        reference = rows[f"{prefix}_reference_{suffix}"] / scale
        cases = np.stack([rows[f"{prefix}_tau{tau}_{suffix}"] / scale for tau in [170, 380]])
        ax.fill_between(
            time,
            np.minimum(cases.min(0), reference),
            np.maximum(cases.max(0), reference),
            color=color,
            alpha=0.16,
            label="风化响应时间17–38万年的模型范围",
        )
        ax.plot(time, reference, color=color, label="24万年参考情景")
        ax.set(title=title, ylabel=unit)
        ax.legend(loc="lower left")
    axes[2].set(xlabel="距今（万地球年；最右为当代）", ylim=(0, None))
    for ax in axes:
        ax.set_xlim(200, 0)
        ax.grid(alpha=0.2)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT, dpi=240)
    plt.close(fig)
    print(OUTPUT)


if __name__ == "__main__":
    main()
