---
title: "附录：气候 GCM 运行配置与复现命令"
type: design-note-appendix
tags: [climate, gcm, exoplasim, reproducibility]
date: 2026-10-14
status: accepted
---

# 0012 附录 — GCM 运行配置与复现命令

本附录列出 [0012](0012-climate-gcm-calibration.md) 引用的全部 ExoPlaSim 运行：每个运行的
配置、PlaSim 实际使用的轨道、结果摘要与复现命令。表格由脚本从各运行目录的 `manifest.json`
与 `MOST_DIAG` 生成，不手工编辑；新增运行后重新生成即可：

```bash
private/gcm/venv/bin/python scripts/climate/gcm/gcm_runs_appendix.py \
    private/gcm/runs/t42o/* private/gcm/runs/t42a/* \
    --preamble private/gcm/tools/appendix_preamble.md --out data/worlds/nacrea/design-notes/0012-appendix-gcm-runs.md
```

运行目录的分组：`t42o/cold_*` 是 CO₂ 扫描的冷臂；`t42o/warm_*` 是暖臂，种子为
`t42o/melt_2000`（2000 ppm 积分 10 年，只作种子，不作平衡结果）；`t42o/earth_pi` 是地球参照臂；
`t42a/` 是 712 ppm 下的消融（`abl_obliq_only` 只改倾角，`abl_sh_year` 为南半球大年相位，
`abl_equinox_year` 为均衡年相位）。表中「代码版本」为「未记录」的运行早于 manifest 记录代码
版本的功能，复现命令由记录的参数重建，轨道显式写出。运行需要 `private/gcm/venv` 环境与
`docs/usage/exoplasim-gcm.md` 所述的集群环境变量。

## 共用配置

- 额外 `configure` 参数：`{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}`
- 额外 namelist：`{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}`
- 轨道一律固定（`fixedorbit`），实际使用值见下表，读自各运行的 `MOST_DIAG`。
- 结果取最后 5 个模式年（60 条月记录）的面积加权平均；趋势为最后两个五年窗口之差。

## 运行一览

| 运行目录 | pCO₂ | 模式年 | 起步 | 偏心率 | 倾角 | MVELP（季节相位） | 全球 2 m 气温 | 趋势 | 海冰 | 代码版本 |
|---|---:|---:|---|---:|---:|---|---:|---:|---:|---|
| `private/gcm/runs/t42a/abl_equinox_year` | 711.5 ppm | 30 | 冷启动 | 0.067863 | 19.900° | 172.678°（φ = 352.7°） | 12.13 °C | +0.08 K | 11.1 % | v0.39.0-38-g123210fdcec8 |
| `private/gcm/runs/t42a/abl_obliq_only` | 711.5 ppm | 30 | 冷启动 | 0.017465 | 19.900° | 68.837°（φ = 248.8°） | 11.77 °C | +0.11 K | 11.6 % | v0.39.0-38-g123210fdcec8 |
| `private/gcm/runs/t42a/abl_sh_year` | 711.5 ppm | 30 | 冷启动 | 0.067863 | 19.900° | 82.678°（φ = 262.7°） | 12.50 °C | +0.06 K | 10.5 % | v0.39.0-38-g123210fdcec8 |
| `private/gcm/runs/t42o/cold_1000` | 999.0 ppm | 30 | 冷启动 | 0.067863 | 19.900° | 262.678°（φ = 82.7°） | 13.67 °C | +0.04 K | 10.1 % | v0.39.0-38-g123210fdcec8 |
| `private/gcm/runs/t42o/cold_140` | 140.0 ppm | 30 | 冷启动 | 0.067863 | 19.900° | 262.678°（φ = 82.7°） | 3.38 °C | -0.02 K | 20.3 % | 未记录 |
| `private/gcm/runs/t42o/cold_1400` | 1398.0 ppm | 30 | 冷启动 | 0.067863 | 19.900° | 262.678°（φ = 82.7°） | 15.42 °C | -0.00 K | 8.3 % | v0.39.0-38-g123210fdcec8 |
| `private/gcm/runs/t42o/cold_2000` | 1996.0 ppm | 30 | 冷启动 | 0.067863 | 19.900° | 262.678°（φ = 82.7°） | 17.17 °C | +0.06 K | 7.1 % | v0.39.0-38-g123210fdcec8 |
| `private/gcm/runs/t42o/cold_280` | 279.9 ppm | 30 | 冷启动 | 0.067863 | 19.900° | 262.678°（φ = 82.7°） | 6.77 °C | +0.10 K | 16.8 % | v0.39.0-38-g123210fdcec8 |
| `private/gcm/runs/t42o/cold_3000` | 2991.0 ppm | 30 | 冷启动 | 0.067863 | 19.900° | 262.678°（φ = 82.7°） | 19.12 °C | +0.05 K | 5.6 % | v0.39.0-38-g123210fdcec8 |
| `private/gcm/runs/t42o/cold_356` | 355.9 ppm | 30 | 冷启动 | 0.067863 | 19.900° | 262.678°（φ = 82.7°） | 8.25 °C | +0.12 K | 15.4 % | v0.39.0-38-g123210fdcec8 |
| `private/gcm/runs/t42o/cold_560` | 559.7 ppm | 30 | 冷启动 | 0.067863 | 19.900° | 262.678°（φ = 82.7°） | 10.66 °C | +0.12 K | 13.0 % | v0.39.0-38-g123210fdcec8 |
| `private/gcm/runs/t42o/cold_6000` | 5964.2 ppm | 30 | 冷启动 | 0.067863 | 19.900° | 262.678°（φ = 82.7°） | 22.11 °C | +0.05 K | 3.5 % | v0.39.0-38-g123210fdcec8 |
| `private/gcm/runs/t42o/cold_712` | 711.5 ppm | 30 | 冷启动 | 0.067863 | 19.900° | 262.678°（φ = 82.7°） | 11.91 °C | +0.06 K | 11.8 % | 未记录 |
| `private/gcm/runs/t42o/earth_pi` | 279.9 ppm | 40 | 冷启动 | 0.016700 | 23.440° | 102.700°（φ = 282.7°） | 12.89 °C | +0.06 K | 7.6 % | v0.39.0-38-g123210fdcec8 |
| `private/gcm/runs/t42o/melt_2000` | 1996.0 ppm | 10 | 冷启动 | 0.067863 | 19.900° | 262.678°（φ = 82.7°） | 13.05 °C | +11.65 K | 11.5 % | 未记录 |
| `private/gcm/runs/t42o/warm_140` | 140.0 ppm | 30 | 暖启动，种子 `private/gcm/runs/t42o/melt_2000/MOST_REST.00000` | 0.067863 | 19.900° | 262.678°（φ = 82.7°） | 3.44 °C | -0.03 K | 20.4 % | v0.39.0-38-g123210fdcec8 |
| `private/gcm/runs/t42o/warm_356` | 355.9 ppm | 30 | 暖启动，种子 `private/gcm/runs/t42o/melt_2000/MOST_REST.00000` | 0.067863 | 19.900° | 262.678°（φ = 82.7°） | 8.25 °C | +0.05 K | 15.4 % | v0.39.0-38-g123210fdcec8 |
| `private/gcm/runs/t42o/warm_712` | 711.5 ppm | 30 | 暖启动，种子 `private/gcm/runs/t42o/melt_2000/MOST_REST.00000` | 0.067863 | 19.900° | 262.678°（φ = 82.7°） | 12.02 °C | +0.02 K | 11.6 % | v0.39.0-38-g123210fdcec8 |

## 地表文件哈希

- landmap：`8e832135467e227ef8aafe8d03869cf63119d15011d32e09b27b90659582ff2b`（当前文件 `private/gcm/surf/nacrea_N064_surf_0172.sra`）
- landmap：`dca5a292225c4cb3a2df6b2913e264e7f486318ffbde452d33be152fb0941b78`（当前文件 `private/gcm/surf/earth_N064_surf_0172.sra`）
- topomap：`ffdfe8be5fa7f0c315b4ba0b4fc36762b77a3ff0de490892f1c39bba9cdf8ce2`（当前文件 `private/gcm/surf/nacrea_N064_surf_0129.sra`）
- topomap：`85aa8af30a5587181b9d7c6ee3b7d201b49bfb874e82ac890ac95597c1c791ee`（当前文件 `private/gcm/surf/earth_N064_surf_0129.sra`）

## 复现命令

**`private/gcm/runs/t42a/abl_equinox_year`**（manifest 记录的原始命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.000721434 --landmap private/gcm/surf/nacrea_N064_surf_0172.sra --topomap private/gcm/surf/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --override '{"lonvernaleq": 172.677744}' --workdir private/gcm/runs/t42a/abl_equinox_year
```

**`private/gcm/runs/t42a/abl_obliq_only`**（manifest 记录的原始命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.000721434 --landmap private/gcm/surf/nacrea_N064_surf_0172.sra --topomap private/gcm/surf/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --override '{"eccentricity": 0.017465, "lonvernaleq": 68.836615}' --workdir private/gcm/runs/t42a/abl_obliq_only
```

**`private/gcm/runs/t42a/abl_sh_year`**（manifest 记录的原始命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.000721434 --landmap private/gcm/surf/nacrea_N064_surf_0172.sra --topomap private/gcm/surf/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --override '{"lonvernaleq": 82.677744}' --workdir private/gcm/runs/t42a/abl_sh_year
```

**`private/gcm/runs/t42o/cold_1000`**（manifest 记录的原始命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.00101325 --landmap private/gcm/surf/nacrea_N064_surf_0172.sra --topomap private/gcm/surf/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --workdir private/gcm/runs/t42o/cold_1000
```

**`private/gcm/runs/t42o/cold_140`**（由参数重建的等价显式命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.000141855 --landmap private/gcm/surf/nacrea_N064_surf_0172.sra --topomap private/gcm/surf/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --override '{"eccentricity": 0.067863, "obliquity": 19.9, "lonvernaleq": 262.677744}' --workdir private/gcm/runs/t42o/cold_140
```

**`private/gcm/runs/t42o/cold_1400`**（manifest 记录的原始命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.00141855 --landmap private/gcm/surf/nacrea_N064_surf_0172.sra --topomap private/gcm/surf/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --workdir private/gcm/runs/t42o/cold_1400
```

**`private/gcm/runs/t42o/cold_2000`**（manifest 记录的原始命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.0020265 --landmap private/gcm/surf/nacrea_N064_surf_0172.sra --topomap private/gcm/surf/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --workdir private/gcm/runs/t42o/cold_2000
```

**`private/gcm/runs/t42o/cold_280`**（manifest 记录的原始命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.00028371 --landmap private/gcm/surf/nacrea_N064_surf_0172.sra --topomap private/gcm/surf/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --workdir private/gcm/runs/t42o/cold_280
```

**`private/gcm/runs/t42o/cold_3000`**（manifest 记录的原始命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.00303975 --landmap private/gcm/surf/nacrea_N064_surf_0172.sra --topomap private/gcm/surf/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --workdir private/gcm/runs/t42o/cold_3000
```

**`private/gcm/runs/t42o/cold_356`**（manifest 记录的原始命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.000360717 --landmap private/gcm/surf/nacrea_N064_surf_0172.sra --topomap private/gcm/surf/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --workdir private/gcm/runs/t42o/cold_356
```

**`private/gcm/runs/t42o/cold_560`**（manifest 记录的原始命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.00056742 --landmap private/gcm/surf/nacrea_N064_surf_0172.sra --topomap private/gcm/surf/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --workdir private/gcm/runs/t42o/cold_560
```

**`private/gcm/runs/t42o/cold_6000`**（manifest 记录的原始命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.0060795 --landmap private/gcm/surf/nacrea_N064_surf_0172.sra --topomap private/gcm/surf/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --workdir private/gcm/runs/t42o/cold_6000
```

**`private/gcm/runs/t42o/cold_712`**（由参数重建的等价显式命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.000721434 --landmap private/gcm/surf/nacrea_N064_surf_0172.sra --topomap private/gcm/surf/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --override '{"eccentricity": 0.067863, "obliquity": 19.9, "lonvernaleq": 262.677744}' --workdir private/gcm/runs/t42o/cold_712
```

**`private/gcm/runs/t42o/earth_pi`**（manifest 记录的原始命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/earth --planet planet_earth --resolution T42 --ncpus 16 --years 40 --greenhouse-mode pco2 --pco2-bar 0.00028371 --landmap private/gcm/surf/earth_N064_surf_0172.sra --topomap private/gcm/surf/earth_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --workdir private/gcm/runs/t42o/earth_pi
```

**`private/gcm/runs/t42o/melt_2000`**（由参数重建的等价显式命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 10 --greenhouse-mode pco2 --pco2-bar 0.0020265 --landmap private/gcm/surf/nacrea_N064_surf_0172.sra --topomap private/gcm/surf/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --override '{"eccentricity": 0.067863, "obliquity": 19.9, "lonvernaleq": 262.677744}' --workdir private/gcm/runs/t42o/melt_2000
```

**`private/gcm/runs/t42o/warm_140`**（由参数重建的等价显式命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.000141855 --landmap private/gcm/surf/nacrea_N064_surf_0172.sra --topomap private/gcm/surf/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --override '{"eccentricity": 0.067863, "obliquity": 19.9, "lonvernaleq": 262.677744}' --restart private/gcm/runs/t42o/melt_2000/MOST_REST.00000 --workdir private/gcm/runs/t42o/warm_140
```

**`private/gcm/runs/t42o/warm_356`**（由参数重建的等价显式命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.000360717 --landmap private/gcm/surf/nacrea_N064_surf_0172.sra --topomap private/gcm/surf/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --override '{"eccentricity": 0.067863, "obliquity": 19.9, "lonvernaleq": 262.677744}' --restart private/gcm/runs/t42o/melt_2000/MOST_REST.00000 --workdir private/gcm/runs/t42o/warm_356
```

**`private/gcm/runs/t42o/warm_712`**（由参数重建的等价显式命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.000721434 --landmap private/gcm/surf/nacrea_N064_surf_0172.sra --topomap private/gcm/surf/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --override '{"eccentricity": 0.067863, "obliquity": 19.9, "lonvernaleq": 262.677744}' --restart private/gcm/runs/t42o/melt_2000/MOST_REST.00000 --workdir private/gcm/runs/t42o/warm_712
```

