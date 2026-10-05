"""Global overview figure for one ExoPlaSim run (``overview.png``).

Six-panel summary: near-surface temperature, total precipitation, sea-level
pressure, near-surface zonal wind (lowest model level when 10 m wind is
absent from the variable set), the zonal-mean zonal-wind cross-section, and
the temporal standard deviation of zonal wind (transient eddies live here —
the mean fields of an aquaplanet are zonally banded *by construction*).
Plus a statistics panel answering "is the wind field dead?".

Captions are Chinese when a CJK font is reachable (Windows-mounted 微软雅黑
under WSL, then Noto/WQY on Linux) and fall back to English otherwise, so the
same figure works on the local WSL box and on a bare server container.
"""

from __future__ import annotations

import os
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as fm  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import netCDF4  # noqa: E402
import numpy as np  # noqa: E402

from dreamulator.gcm.diagnostics import mass_streamfunction

_FONT_CANDIDATES = [
    "/mnt/c/Windows/Fonts/msyh.ttc",  # Windows 微软雅黑 (WSL mount)
    "/mnt/c/Windows/Fonts/simhei.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy-zenhei.ttc",
]

CJK_OK = False
for _path in _FONT_CANDIDATES:
    if os.path.exists(_path):
        try:
            fm.fontManager.addfont(_path)
            _name = fm.FontProperties(fname=_path).get_name()
            plt.rcParams["font.sans-serif"] = [_name, "DejaVu Sans"]
            plt.rcParams["font.monospace"] = [_name, "DejaVu Sans Mono"]
            CJK_OK = True
            break
        except Exception:  # noqa: BLE001 -- try the next candidate
            continue
plt.rcParams["axes.unicode_minus"] = False

_T: dict[str, Any] = {
    True: {  # Chinese captions
        "t2m": "近地面温度",
        "pr": "总降水",
        "psl": "海平面气压",
        "u_sfc": "纬向风（最低模式层）",
        "uzm": "纬向平均纬向风",
        "psi": "经向翻转流函数 ψ（环流圈）",
        "ustd": "纬向风时间标准差（涡动/季节）",
        "lat": "纬度",
        "lev": "模式层",
        "verdict_ok": "★ 风场正常",
        "verdict_dead": "⚠ 疑似风场死寂",
        "stats": {
            "max_ua": "最大|纬向风| ua：",
            "max_va": "最大|经向风| va：",
            "jet": "急流（纬向平均最大）：",
            "eddy": "风速时间变率 std(u)：",
            "t_eq": "赤道均温：",
            "t_pole": "极区均温：",
        },
    },
    False: {  # English fallback
        "t2m": "near-surface temperature",
        "pr": "total precipitation",
        "psl": "sea-level pressure",
        "u_sfc": "zonal wind (lowest level)",
        "uzm": "zonal-mean zonal wind",
        "psi": "meridional mass streamfunction ψ (cells)",
        "ustd": "temporal std of zonal wind (eddies/season)",
        "lat": "lat",
        "lev": "model level",
        "verdict_ok": "WINDS LOOK ALIVE",
        "verdict_dead": "*** WIND FIELD DEAD? ***",
        "stats": {
            "max_ua": "max|ua|: ",
            "max_va": "max|va|: ",
            "jet": "jet (zonal-mean max): ",
            "eddy": "std(u): ",
            "t_eq": "T_eq: ",
            "t_pole": "T_pole: ",
        },
    },
}[CJK_OK]


def _read_var(ds: netCDF4.Dataset, name: str) -> np.ndarray | None:
    """Read a variable as ndarray, or ``None`` when absent.

    Uses try/except rather than ``in`` membership so mypy keeps the
    ``Any``-typed ``ds.variables`` un-narrowed.
    """
    try:
        return np.asarray(ds.variables[name][:])
    except KeyError:
        return None


def _tail_mean(arr: np.ndarray, n: int = 6) -> np.ndarray:
    return np.asarray(np.mean(arr[-min(n, arr.shape[0]) :], axis=0))


def _panel(
    ax: Any,
    lon: np.ndarray,
    lat: np.ndarray,
    field: np.ndarray,
    title: str,
    units: str,
    cmap: str = "viridis",
    sym: bool = False,
) -> None:
    vmax = float(np.abs(field).max()) if sym else float(field.max())
    vmin = -vmax if sym else float(field.min())
    if not np.isfinite(vmax) or vmax == vmin:
        vmax, vmin = (1.0, -1.0) if sym else (1.0, 0.0)
    pcm = ax.pcolormesh(lon, lat, field, cmap=cmap, vmin=vmin, vmax=vmax, shading="auto")
    ax.set_title(title, fontsize=10)
    ax.set_xticks([0, 90, 180, 270, 360])
    ax.set_yticks([-90, -45, 0, 45, 90])
    ax.set_ylabel(_T["lat"], fontsize=8)
    plt.colorbar(pcm, ax=ax, label=units, shrink=0.85)


def plot_overview(
    nc_path: str | os.PathLike[str],
    out_png: str | None = None,
    *,
    radius_m: float = 6.37122e6,
    gravity: float = 9.80665,
) -> str:
    """Render ``overview.png`` for a postprocessed run; returns the PNG path."""
    ds = netCDF4.Dataset(str(nc_path))
    try:
        lon = np.asarray(ds.variables["lon"])  # already degrees (units: deg)
        lat = np.asarray(ds.variables["lat"])  # already degrees (units: deg)
        n_time = len(ds.dimensions["time"])

        tas = _read_var(ds, "tas")
        ta = _read_var(ds, "ta")
        pr = _read_var(ds, "pr")
        psl = _read_var(ds, "psl")
        if psl is None:
            psl = _read_var(ds, "ps")  # fall back to surface pressure
        uas = _read_var(ds, "uas")
        ua_all = _read_var(ds, "ua")
        va_all = _read_var(ds, "va")

        fig, axes = plt.subplots(2, 4, figsize=(19, 7))
        fig.suptitle(f"{nc_path}  (tail-mean, {n_time} records)", fontsize=11)

        if tas is not None:
            _panel(axes[0, 0], lon, lat, _tail_mean(tas) - 273.15, _T["t2m"], "°C", "RdYlBu_r")
        elif ta is not None:
            _panel(axes[0, 0], lon, lat, _tail_mean(ta)[-1] - 273.15, _T["t2m"], "°C", "RdYlBu_r")

        if pr is not None:
            _panel(
                axes[0, 1], lon, lat, _tail_mean(pr) * 86400.0 * 1000.0, _T["pr"], "mm/day", "Blues"
            )

        if psl is not None:
            _panel(axes[0, 2], lon, lat, _tail_mean(psl), _T["psl"], "hPa", "coolwarm")

        if uas is not None:
            _panel(axes[0, 3], lon, lat, _tail_mean(uas), _T["u_sfc"], "m/s", "RdBu_r", sym=True)
        elif ua_all is not None:
            _panel(
                axes[0, 3], lon, lat, _tail_mean(ua_all)[-1], _T["u_sfc"], "m/s", "RdBu_r", sym=True
            )

        if ua_all is not None:
            lev = np.asarray(ds.variables["lev"][:])
            n = min(6, ua_all.shape[0])
            u_zm = np.asarray(np.mean(ua_all[-n:], axis=(0, 3)))
            vmax = float(np.abs(u_zm).max()) or 1.0
            pcm = axes[1, 0].contourf(
                lat, lev, u_zm, levels=21, cmap="RdBu_r", vmin=-vmax, vmax=vmax
            )
            axes[1, 0].set_title(_T["uzm"], fontsize=10)
            axes[1, 0].set_xlabel(_T["lat"], fontsize=8)
            axes[1, 0].set_ylabel(_T["lev"], fontsize=8)
            plt.colorbar(pcm, ax=axes[1, 0], label="m/s", shrink=0.85)

            u_std = np.asarray(ua_all[-n:].std(axis=0).mean(axis=2))
            pcm = axes[1, 1].pcolormesh(lat, lev, u_std, cmap="magma", shading="auto")
            axes[1, 1].set_title(_T["ustd"], fontsize=10)
            axes[1, 1].set_xlabel(_T["lat"], fontsize=8)
            axes[1, 1].set_ylabel(_T["lev"], fontsize=8)
            plt.colorbar(pcm, ax=axes[1, 1], label="m/s", shrink=0.85)

            lines = [
                _T["stats"]["max_ua"] + f"{np.abs(ua_all).max():.3e} m/s",
            ]
            if va_all is not None:
                lines.append(_T["stats"]["max_va"] + f"{np.abs(va_all).max():.3e} m/s")
            lines += [
                _T["stats"]["jet"] + f"{u_zm.max():.1f} m/s",
                _T["stats"]["eddy"] + f"{ua_all[-n:].std(axis=0).max():.1f} m/s",
            ]
            if ta is not None:
                t_zm = np.asarray(np.mean(ta[-n:], axis=(0, 3)))
                i_eq = int(np.argmin(np.abs(lat)))
                lines.append(_T["stats"]["t_eq"] + f"{t_zm[:, i_eq].mean() - 273.15:.1f} °C")
                lines.append(
                    _T["stats"]["t_pole"]
                    + f"{0.5 * (t_zm[:, 0].mean() + t_zm[:, -1].mean()) - 273.15:.1f} °C"
                )
            verdict = _T["verdict_ok"] if np.abs(ua_all).max() > 1.0 else _T["verdict_dead"]
            axes[1, 2].axis("off")
            axes[1, 2].text(
                0.05,
                0.95,
                "\n".join(lines + ["", verdict]),
                va="top",
                fontsize=10,
                family="monospace",
            )

        # ---- ψ 质量流函数剖面（环流圈结构：符号翻转 = 圈边界）
        va_all = _read_var(ds, "va")
        levp = _read_var(ds, "levp")
        ps_all = _read_var(ds, "ps")
        if va_all is not None and levp is not None and ps_all is not None:
            npsi = min(6, va_all.shape[0])
            psi = mass_streamfunction(
                np.asarray(np.mean(va_all[-npsi:], axis=0)),
                np.asarray(np.mean(ps_all[-npsi:], axis=0)),
                lat,
                levp,
                radius_m,
                gravity,
            )
            psi10 = psi / 1e10
            vmax = float(np.abs(psi10).max()) or 1.0
            pcm = axes[1, 3].pcolormesh(
                lat,
                np.asarray(ds.variables["lev"][:]),
                psi10,
                cmap="RdBu_r",
                vmin=-vmax,
                vmax=vmax,
                shading="auto",
            )
            axes[1, 3].set_title(_T["psi"], fontsize=10)
            axes[1, 3].set_xlabel(_T["lat"], fontsize=8)
            axes[1, 3].set_ylabel(_T["lev"], fontsize=8)
            plt.colorbar(pcm, ax=axes[1, 3], label="1e10 kg/s", shrink=0.85)

        if out_png is None:
            from pathlib import Path

            out_png = str(Path(str(nc_path)).parent / "overview.png")
        fig.savefig(out_png, dpi=110, bbox_inches="tight")
        plt.close(fig)
        return out_png
    finally:
        ds.close()


__all__ = ["plot_overview"]
