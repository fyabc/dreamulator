---
title: "附录：气候 GCM 运行配置与复现命令"
type: design-note-appendix
tags: [climate, gcm, exoplasim, reproducibility]
date: 2026-10-23
status: accepted
---

# 0012 附录 — GCM 运行配置与复现命令

本附录列出 [0012](0012-climate-gcm-calibration.md) 与 [0016](0016-sea-level-gateways.md) 引用的全部
ExoPlaSim 运行：每个运行的配置、PlaSim 实际使用的轨道、结果摘要与复现命令。表格由脚本从各运行目录的
`manifest.json` 与 `MOST_DIAG` 生成，不手工编辑；新增运行后重新生成即可。运行目录、地表文件与工具脚本
都位于作者本机的 GCM 存档（不随仓库分发），本文路径均为该存档内的相对路径：

```bash
# 在 GCM 存档根目录下运行（venv、运行目录与 tools/ 都在存档中）：
GCM_ARCHIVE=$PWD <venv>/bin/python <repo>/scripts/climate/gcm/gcm_runs_appendix.py \
    runs/t42r/cold_* runs/t42r/warm_* runs/t42r/melt_2000 runs/t42r/abl_* runs/t42r/obl_* \
    runs/t42r/sl_* runs/t42o/earth_pi \
    --preamble tools/appendix_preamble.md --out <repo>/data/worlds/nacrea/design-notes/0012-appendix-gcm-runs.md
```

**运行分组。** `runs/t42r/` 是 2026-10-22 重新生成的地形上的全部 nacrea 运行，2026-10-23 一次跑完，口径一致：

- `cold_*` 是 10 档 CO₂ 的冷臂，从 ExoPlaSim 默认初态积分 30 个模式年。0012 §3 的扫描表、§7 的范围表
  与 0016 §2 的海平面表都取自这一组，固定气候分支 `gcm-t42-712` 取自其中的 712 ppm。
- `warm_*` 是 140、356、712 ppm 的暖臂，种子为 `melt_2000`（2000 ppm 积分 10 年，只作种子，不作平衡
  结果），用于判断是否存在多个平衡态。
- `abl_obliq_only` 换成地球公元 1 年的偏心率与近日点相位、保留 nacrea 的季节倾角；`abl_earth_orbit`
  在此基础上再把倾角换成地球的 23.695°，两者合起来把倾角效应与距离季节效应分开。`abl_sh_year` 为
  南半球大年相位，`abl_equinox_year` 为均衡年相位。
- `obl_14.5` 与 `obl_26.0` 是季节角固定为 14.5° 与 26° 的平衡态。
- `sl_m36_140` 与 `sl_p43_3000` 是海平面各降 36 m、升 43 m 后重标海陆掩膜的对照，供 0016 §3 使用。
- 季节角瞬变运行是重启链 `trans2/seg_000` 至 `seg_033`（每段 1 个模式年，季节角按
  20.6° + 5.8° sin(2π(k + 0.5)/8.49) 逐段取值，8.49 个模式年约等于 8.6 地球年），由存档中的
  `tools/t42_r22_queue.sh` 生成、`tools/transient_obliquity.py` 分析，各段配置相同，不逐段列入下表。

`runs/t42o/earth_pi` 是地球参照臂。它的输入没有随 nacrea 地形变化，因此没有重跑，仍是 2026-10 的运行。

注意 PlaSim 的一个模式年约 370 地球日，约等于 3.7 个轨道年。运行需要 GCM 存档中的 venv 环境与
`docs/usage/exoplasim-gcm.md` 所述的集群环境变量。

## 共用配置

- 额外 `configure` 参数：`{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}`
- 额外 namelist：`{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}`
- 轨道一律固定（`fixedorbit`），实际使用值见下表，读自各运行的 `MOST_DIAG`。
- 结果取最后 5 个模式年（60 条月记录）的面积加权平均；趋势为最后两个五年窗口之差。

## 运行一览

| 运行目录 | pCO₂ | 模式年 | 起步 | 偏心率 | 倾角 | MVELP（季节相位） | 全球 2 m 气温 | 趋势 | 海冰 | 代码版本 |
|---|---:|---:|---|---:|---:|---|---:|---:|---:|---|
| `runs/t42r/cold_1000` | 999.0 ppm | 30 | 冷启动 | 0.067863 | 19.900° | 262.678°（φ = 82.7°） | 13.93 °C | +0.02 K | 11.3 % | v1.1.0-46-g1fb27ca5f12d |
| `runs/t42r/cold_140` | 140.0 ppm | 30 | 冷启动 | 0.067863 | 19.900° | 262.678°（φ = 82.7°） | 3.78 °C | -0.04 K | 20.4 % | v1.1.0-30-g4ba8d808d2d5 |
| `runs/t42r/cold_1400` | 1398.0 ppm | 30 | 冷启动 | 0.067863 | 19.900° | 262.678°（φ = 82.7°） | 15.44 °C | +0.03 K | 10.1 % | v1.1.0-32-g1a424cf6789d |
| `runs/t42r/cold_2000` | 1996.0 ppm | 30 | 冷启动 | 0.067863 | 19.900° | 262.678°（φ = 82.7°） | 17.26 °C | +0.03 K | 8.4 % | v1.1.0-46-g1fb27ca5f12d |
| `runs/t42r/cold_280` | 279.9 ppm | 30 | 冷启动 | 0.067863 | 19.900° | 262.678°（φ = 82.7°） | 7.04 °C | -0.01 K | 17.7 % | v1.1.0-46-g1fb27ca5f12d |
| `runs/t42r/cold_3000` | 2991.0 ppm | 30 | 冷启动 | 0.067863 | 19.900° | 262.678°（φ = 82.7°） | 19.28 °C | +0.11 K | 6.8 % | v1.1.0-32-g1a424cf6789d |
| `runs/t42r/cold_356` | 355.9 ppm | 30 | 冷启动 | 0.067863 | 19.900° | 262.678°（φ = 82.7°） | 8.46 °C | +0.11 K | 16.6 % | v1.1.0-31-gd3a5929969ee |
| `runs/t42r/cold_560` | 559.7 ppm | 30 | 冷启动 | 0.067863 | 19.900° | 262.678°（φ = 82.7°） | 10.86 °C | +0.02 K | 14.3 % | v1.1.0-46-g1fb27ca5f12d |
| `runs/t42r/cold_6000` | 5964.2 ppm | 30 | 冷启动 | 0.067863 | 19.900° | 262.678°（φ = 82.7°） | 22.43 °C | +0.02 K | 4.1 % | v1.1.0-46-g1fb27ca5f12d |
| `runs/t42r/cold_712` | 711.5 ppm | 30 | 冷启动 | 0.067863 | 19.900° | 262.678°（φ = 82.7°） | 12.20 °C | -0.00 K | 12.9 % | v1.1.0-30-g4ba8d808d2d5 |
| `runs/t42r/warm_140` | 140.0 ppm | 30 | 暖启动，种子 `runs/t42r/melt_2000/MOST_REST.00000` | 0.067863 | 19.900° | 262.678°（φ = 82.7°） | 3.75 °C | -0.05 K | 20.4 % | v1.1.0-46-g1fb27ca5f12d |
| `runs/t42r/warm_356` | 355.9 ppm | 30 | 暖启动，种子 `runs/t42r/melt_2000/MOST_REST.00000` | 0.067863 | 19.900° | 262.678°（φ = 82.7°） | 8.46 °C | -0.01 K | 16.6 % | v1.1.0-46-g1fb27ca5f12d |
| `runs/t42r/warm_712` | 711.5 ppm | 30 | 暖启动，种子 `runs/t42r/melt_2000/MOST_REST.00000` | 0.067863 | 19.900° | 262.678°（φ = 82.7°） | 12.24 °C | -0.09 K | 12.9 % | v1.1.0-46-g1fb27ca5f12d |
| `runs/t42r/melt_2000` | 1996.0 ppm | 10 | 冷启动 | 0.067863 | 19.900° | 262.678°（φ = 82.7°） | 13.15 °C | +11.92 K | 12.7 % | v1.1.0-30-g4ba8d808d2d5 |
| `runs/t42r/abl_earth_orbit` | 711.5 ppm | 30 | 冷启动 | 0.017465 | 23.695° | 68.837°（φ = 248.8°） | 12.96 °C | +0.12 K | 10.7 % | v1.1.0-46-g1fb27ca5f12d-dirty |
| `runs/t42r/abl_equinox_year` | 711.5 ppm | 30 | 冷启动 | 0.067863 | 19.900° | 172.678°（φ = 352.7°） | 12.46 °C | +0.14 K | 12.5 % | v1.1.0-46-g1fb27ca5f12d |
| `runs/t42r/abl_obliq_only` | 711.5 ppm | 30 | 冷启动 | 0.017465 | 19.900° | 68.837°（φ = 248.8°） | 12.18 °C | +0.08 K | 12.8 % | v1.1.0-46-g1fb27ca5f12d |
| `runs/t42r/abl_sh_year` | 711.5 ppm | 30 | 冷启动 | 0.067863 | 19.900° | 82.678°（φ = 262.7°） | 12.72 °C | +0.09 K | 12.1 % | v1.1.0-46-g1fb27ca5f12d |
| `runs/t42r/obl_14.5` | 711.5 ppm | 30 | 冷启动 | 0.067863 | 14.500° | 262.678°（φ = 82.7°） | 11.58 °C | +0.05 K | 14.9 % | v1.1.0-46-g1fb27ca5f12d |
| `runs/t42r/obl_26.0` | 711.5 ppm | 30 | 冷启动 | 0.067863 | 26.000° | 262.678°（φ = 82.7°） | 13.39 °C | +0.10 K | 9.3 % | v1.1.0-46-g1fb27ca5f12d |
| `runs/t42r/sl_m36_140` | 140.0 ppm | 30 | 冷启动 | 0.067863 | 19.900° | 262.678°（φ = 82.7°） | 3.54 °C | +0.08 K | 20.6 % | v1.1.0-46-g1fb27ca5f12d |
| `runs/t42r/sl_p43_3000` | 2991.0 ppm | 30 | 冷启动 | 0.067863 | 19.900° | 262.678°（φ = 82.7°） | 20.03 °C | +0.18 K | 6.0 % | v1.1.0-46-g1fb27ca5f12d |
| `runs/t42o/earth_pi` | 279.9 ppm | 40 | 冷启动 | 0.016700 | 23.440° | 102.700°（φ = 282.7°） | 12.89 °C | +0.06 K | 7.6 % | v0.39.0-38-g123210fdcec8 |

## 地表文件哈希

- landmap：`2de3e242452bd5451b1179ff1635288550a7e5d17807021bdb31d57888bcf0c2`
- landmap：`8214d58572f3ccc947d7aca6904b5118e91e0af2aaf25df851a45aad3e3da5fe`
- landmap：`8ce40cf733ddc5f0bc0177768ea06f944014993386ea3abf39c6b3af1fd281f0`
- landmap：`dca5a292225c4cb3a2df6b2913e264e7f486318ffbde452d33be152fb0941b78`（当前文件 `surf/earth_N064_surf_0172.sra`）
- topomap：`02eba779cf0ffbe80512796443cd9d65382c31aad986777b12ceab2b489eaf2b`
- topomap：`6141e1796c098e65ecceb26ee094ddc192bf59b87a063dd3d62d6fe4a9ac6b8d`
- topomap：`f1e41b69a8166cbd5eb960b23e5c2f4bc3c25677b4d09d22cee860890d119553`
- topomap：`85aa8af30a5587181b9d7c6ee3b7d201b49bfb874e82ac890ac95597c1c791ee`（当前文件 `surf/earth_N064_surf_0129.sra`）

## 复现命令

**`runs/t42r/cold_1000`**（manifest 记录的原始命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.00101325 --landmap surf/r22/nacrea_N064_surf_0172.sra --topomap surf/r22/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --workdir runs/t42r/cold_1000
```

**`runs/t42r/cold_140`**（manifest 记录的原始命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.000141855 --landmap surf/r22/nacrea_N064_surf_0172.sra --topomap surf/r22/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --workdir runs/t42r/cold_140
```

**`runs/t42r/cold_1400`**（manifest 记录的原始命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.00141855 --landmap surf/r22/nacrea_N064_surf_0172.sra --topomap surf/r22/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --workdir runs/t42r/cold_1400
```

**`runs/t42r/cold_2000`**（manifest 记录的原始命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.0020265 --landmap surf/r22/nacrea_N064_surf_0172.sra --topomap surf/r22/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --workdir runs/t42r/cold_2000
```

**`runs/t42r/cold_280`**（manifest 记录的原始命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.00028371 --landmap surf/r22/nacrea_N064_surf_0172.sra --topomap surf/r22/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --workdir runs/t42r/cold_280
```

**`runs/t42r/cold_3000`**（manifest 记录的原始命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.00303975 --landmap surf/r22/nacrea_N064_surf_0172.sra --topomap surf/r22/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --workdir runs/t42r/cold_3000
```

**`runs/t42r/cold_356`**（manifest 记录的原始命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.000360717 --landmap surf/r22/nacrea_N064_surf_0172.sra --topomap surf/r22/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --workdir runs/t42r/cold_356
```

**`runs/t42r/cold_560`**（manifest 记录的原始命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.00056742 --landmap surf/r22/nacrea_N064_surf_0172.sra --topomap surf/r22/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --workdir runs/t42r/cold_560
```

**`runs/t42r/cold_6000`**（manifest 记录的原始命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.0060795 --landmap surf/r22/nacrea_N064_surf_0172.sra --topomap surf/r22/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --workdir runs/t42r/cold_6000
```

**`runs/t42r/cold_712`**（manifest 记录的原始命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.000721434 --landmap surf/r22/nacrea_N064_surf_0172.sra --topomap surf/r22/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --workdir runs/t42r/cold_712
```

**`runs/t42r/warm_140`**（由参数重建的等价显式命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.000141855 --landmap surf/r22/nacrea_N064_surf_0172.sra --topomap surf/r22/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --override '{"eccentricity": 0.067863, "obliquity": 19.9, "lonvernaleq": 262.677744}' --restart runs/t42r/melt_2000/MOST_REST.00000 --workdir runs/t42r/warm_140
```

**`runs/t42r/warm_356`**（由参数重建的等价显式命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.000360717 --landmap surf/r22/nacrea_N064_surf_0172.sra --topomap surf/r22/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --override '{"eccentricity": 0.067863, "obliquity": 19.9, "lonvernaleq": 262.677744}' --restart runs/t42r/melt_2000/MOST_REST.00000 --workdir runs/t42r/warm_356
```

**`runs/t42r/warm_712`**（由参数重建的等价显式命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.000721434 --landmap surf/r22/nacrea_N064_surf_0172.sra --topomap surf/r22/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --override '{"eccentricity": 0.067863, "obliquity": 19.9, "lonvernaleq": 262.677744}' --restart runs/t42r/melt_2000/MOST_REST.00000 --workdir runs/t42r/warm_712
```

**`runs/t42r/melt_2000`**（manifest 记录的原始命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 10 --greenhouse-mode pco2 --pco2-bar 0.0020265 --landmap surf/r22/nacrea_N064_surf_0172.sra --topomap surf/r22/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --workdir runs/t42r/melt_2000
```

**`runs/t42r/abl_earth_orbit`**（manifest 记录的原始命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.000721434 --landmap surf/r22/nacrea_N064_surf_0172.sra --topomap surf/r22/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --override '{"eccentricity": 0.017465, "obliquity": 23.695, "lonvernaleq": 68.836615}' --workdir runs/t42r/abl_earth_orbit
```

**`runs/t42r/abl_equinox_year`**（manifest 记录的原始命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.000721434 --landmap surf/r22/nacrea_N064_surf_0172.sra --topomap surf/r22/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --override '{"lonvernaleq": 172.677744}' --workdir runs/t42r/abl_equinox_year
```

**`runs/t42r/abl_obliq_only`**（manifest 记录的原始命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.000721434 --landmap surf/r22/nacrea_N064_surf_0172.sra --topomap surf/r22/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --override '{"eccentricity": 0.017465, "lonvernaleq": 68.836615}' --workdir runs/t42r/abl_obliq_only
```

**`runs/t42r/abl_sh_year`**（manifest 记录的原始命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.000721434 --landmap surf/r22/nacrea_N064_surf_0172.sra --topomap surf/r22/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --override '{"lonvernaleq": 82.677744}' --workdir runs/t42r/abl_sh_year
```

**`runs/t42r/obl_14.5`**（manifest 记录的原始命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.000721434 --landmap surf/r22/nacrea_N064_surf_0172.sra --topomap surf/r22/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --override '{"obliquity": 14.5}' --workdir runs/t42r/obl_14.5
```

**`runs/t42r/obl_26.0`**（manifest 记录的原始命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.000721434 --landmap surf/r22/nacrea_N064_surf_0172.sra --topomap surf/r22/nacrea_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --override '{"obliquity": 26.0}' --workdir runs/t42r/obl_26.0
```

**`runs/t42r/sl_m36_140`**（manifest 记录的原始命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.000141855 --landmap surf/r22/sealevel/nacrea_sl_m36_N064_surf_0172.sra --topomap surf/r22/sealevel/nacrea_sl_m36_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --workdir runs/t42r/sl_m36_140
```

**`runs/t42r/sl_p43_3000`**（manifest 记录的原始命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/nacrea --planet satellite_nacrea --resolution T42 --ncpus 16 --years 30 --greenhouse-mode pco2 --pco2-bar 0.00303975 --landmap surf/r22/sealevel/nacrea_sl_p43_N064_surf_0172.sra --topomap surf/r22/sealevel/nacrea_sl_p43_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --workdir runs/t42r/sl_p43_3000
```

**`runs/t42o/earth_pi`**（manifest 记录的原始命令）：

```bash
python scripts/climate/gcm/run_exoplasim.py --world data/worlds/earth --planet planet_earth --resolution T42 --ncpus 16 --years 40 --greenhouse-mode pco2 --pco2-bar 0.00028371 --landmap surf/earth_N064_surf_0172.sra --topomap surf/earth_N064_surf_0129.sra --configure '{"twobandalbedo": true, "physicsfilter": "gp|exp|sp"}' --namelist '{"NHDIFF@oceanmod_namelist": "1", "HDIFFK@oceanmod_namelist": "1.0E4"}' --workdir runs/t42o/earth_pi
```

