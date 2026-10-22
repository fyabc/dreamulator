# terrain-diffusion：学习式地形细化器

本链 ②B（refined 路径）的地形细节来源。[xandergos/terrain-diffusion]
（https://github.com/xandergos/terrain-diffusion）（MIT 许可，SIGGRAPH
2026，arXiv 2512.08309）是一个学习式地形生成模型：输入 23 km/px 的
粗条件场，输出 90 m/px 的地貌高程。它是数据源不是超分工具——本库
把它当作「给引擎粗地形长出真实细节」的外部生成器使用。

## 工作机制

模型是条件扩散（diffusion）架构。五个条件通道（高程 m、年均温 °C
海平面口径、温度变率、年降水 mm、降水变率 %，均在 23 km 网格）以
加噪引导的方式进入网络：条件场与噪声按 `cos(t)·cond + sin(t)·noise`
混合，SNR 参数控制条件强度。生成过程分两级：粗尺度 U-Net 先在
64×64 tile 上重新生成粗图（一个条件像素对应 256×256 输出像素），
再经 base + decoder 一致性级联放大 256 倍到最终分辨率，输出 int16
米值 GeoTIFF。

要点的推论：**它不是超分**。条件以加噪引导而非硬约束，即使 SNR
拉满，海岸线也不是严格锚定的——漂移量级约一个粗格（23 km，实测
符号一致率 97.5% @ SNR 0.2、94.5% @ SNR 1.0）。想要「粗场逐位保留、
细节补全」的语义会失望；它给的是「统计上一致的地貌再生成」。

## 实测能力与边界（RTX 3060 6 GB，2026-10 本库验证）

| 维度 | 实测 |
|------|------|
| 跑通性 | Windows + 6 GB 显存 fp32 全链无 OOM，约 0.6 s/tile |
| 确定性 | 同 seed 复跑输出逐位一致 |
| 海岸线 | 符号一致率 97.5%（SNR 0.2），陆面占比漂移 −1.5 pp |
| 大尺度锚定 | 高程分位数与条件场吻合（q50 −214 m vs −317 m） |
| 水文 | **不管**：生成场约 12–13.7% 陆地是封闭盆地（550 km 窗实测），排水、河网、湖语义全部由本库的 Priority-Flood 层补齐 |

## 与本库 SPL 链的分工

细化场自带地貌起伏（平原细节起伏实测 σ 31 m），所以 refined 路径
不需要 SPL 刻蚀也不需要粗糙度注入——那是引擎插值 DEM（②A 路径）
的需求。两条路径的组合即当初调研定的「SPL 管物理一致性、diffusion
管微观真实感」：河网树状、湖语义、流量分级这些**水文正确性**来自
本库算法；山脊碎部的**真实感**来自模型。

## 工程形态

以外部 venv 子进程调用（克隆在本机 `<external-project-dir>/
terrain-diffusion/`，`.venv` 随仓库），不进主项目依赖——其 3 GB CUDA
torch 会拖累 `uv sync --all-extras` 与 CI。推理走 `python -m
terrain_diffusion.inference.tiff_export` 模块直跑（绕开训练栈 import）。
`dreamulator export build`（`src/dreamulator/media/terrain_refine.py`）
封装了三段编排：条件场导出（主库）→ 条件 GeoTIFF 与扩散推理（td venv
子进程）→ 水文提取（主库）。

安装一次性步骤（CUDA GPU；Linux 上把 `.venv/Scripts/python.exe` 换成
`.venv/bin/python` 即可，`export build` 两种布局都认）：

```bash
git clone https://github.com/xandergos/terrain-diffusion <clone>
cd <clone> && uv venv --python 3.12 .venv
# CUDA 轮子必须直连官方源安装（--no-config 防止镜像覆盖 index；
# 经代理下载 2.7 GB 需 UV_HTTP_TIMEOUT=600）
cd ~ && UV_HTTP_TIMEOUT=600 uv --no-config pip install     --python <clone>/.venv/Scripts/python.exe     "https://download.pytorch.org/whl/cu128/torch-2.9.1%2Bcu128-cp312-cp312-win_amd64.whl"     "https://download.pytorch.org/whl/cu128/torchvision-0.24.1%2Bcu128-cp312-cp312-win_amd64.whl"
# 其余依赖按上游 requirements.txt 安装——推理路径还要 rasterio、
# infinite-tensor、numba、pyfastnoiselite 等，手工清单列不全；
# 已装好的 CUDA 版 torch 满足其版本约束，不会被替换
cd <clone> && uv --no-config pip install --python .venv/Scripts/python.exe     -r requirements.txt
```

首次推理自动从 HuggingFace 拉权重（约 1.1 GB，走代理）。

还需预下载 WorldClim 10′ 气候数据：上游 `inference/synthetic_map.py` 读
`<clone>/data/global/` 下的 `wc2.1_10m_bio_{1,4,12,15}.tif`，缺文件时它会用
`input()` 询问是否下载，而 `export build` 以子进程调用、无法应答，直接中止。
从 `https://geodata.ucdavis.edu/climate/worldclim/2_1/base/wc2.1_10m_bio.zip`
（约 50 MB）解压取出这四个文件放入该目录即可。

## 参考

- 仓库与权重：https://github.com/xandergos/terrain-diffusion
  （HF 权重 `xandergos/terrain-diffusion-90m`，约 1.1 GB）
- 论文：arXiv 2512.08309（SIGGRAPH 2026）
