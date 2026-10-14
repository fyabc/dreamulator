#!/bin/bash
# ExoPlaSim 环境引导（任意 Ubuntu 容器/WSL 内可用，无需改 Dockerfile）。
#
# 用途：在目标机器上准备 gfortran 工具链 + Python venv + exoplasim==3.4.2
#      + meson/ninja，并强制把 pyfft 扩展编译出来（上游 compile_pyfft 失败时
#      只 print 不 raise，会把所有后处理悄悄弄死——见 src/dreamulator/gcm/
#      runner.py 的 ensure_environment）。
#
# 用法：
#   bash scripts/climate/gcm/bootstrap.sh [venv-dir]     # 默认 ./gcm_venv
#   PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple bash $0   # 镜像
#
# 刻意不用 uv：仓库树内的 uv.toml 会覆盖 index 配置（2026-10 terrain-diffusion
# 与 2026-10-05 meson 安装两次踩中）；纯 pip + venv 无此坑。
set -euo pipefail

VENV_DIR="${1:-gcm_venv}"

# 共享服务器常预设 MAKEFLAGS=-jN；PlaSim 的 makefile 缺 Fortran 模块依赖，
# 并行 make 会报 "Cannot open module file 'landmod.mod'"。runner.run_gcm
# 构建模型前也会清掉这些变量，这里先清，保证引导过程同样串行。
unset MAKEFLAGS MFLAGS GNUMAKEFLAGS

echo "== [1/4] Fortran 工具链 =="
if ! command -v gfortran >/dev/null; then
    if command -v apt-get >/dev/null; then
        # 容器内通常已是 root；WSL 下需要 sudo。
        SUDO=""
        [ "$(id -u)" != 0 ] && SUDO="sudo"
        $SUDO apt-get update -qq && $SUDO apt-get install -y -qq \
            gfortran gcc make
    else
        echo "未找到 gfortran，且不是 apt 系统——请手动安装 gfortran/gcc/make" >&2
        exit 1
    fi
else
    echo "gfortran $(gfortran --version | head -1) 已就绪"
fi

echo "== [2/4] Python venv: $VENV_DIR =="
python3 -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
python3 -m pip install --upgrade pip --quiet
# pyyaml：dreamulator.gcm.mapping 读世界 YAML；scipy：make_landmap 的最近邻重采样。
python3 -m pip install "exoplasim==3.4.2" netCDF4 matplotlib meson ninja pyyaml scipy
# 参数映射复用 EBM 的近日点推导（dreamulator.engine.physical_inputs），需要引擎的核心依赖。
# 用约束锁住 exoplasim 已装好的 numpy，避免 pyfft 扩展因 numpy 降级失效。
python3 -m pip freeze | grep -i -E '^(numpy|scipy)==' > "$VENV_DIR/gcm-pins.txt"
python3 -m pip install -c "$VENV_DIR/gcm-pins.txt" "pydantic>=2.11" "typer>=0.15" "rich>=13.0" \
    "astropy>=7.0" "jinja2>=3.1" "pillow>=10.0" "opensimplex>=0.4" "numba>=0.61" \
    "tifffile>=2026.7.14" "msgpack>=1.2.1"

echo "== [3/4] 编译 pyfft 扩展（PATH 需含 venv/bin 供 meson/ninja 探测）=="
python3 - <<'EOF'
import exoplasim
exoplasim.compile_pyfft()
# 编译后立即验证 import——上游失败时静默，这里必须显式报错。
import exoplasim.pyfft      # noqa: F401
import exoplasim.pyfft991   # noqa: F401
print("pyfft / pyfft991 import OK")
EOF

echo "== [4/4] 冒烟：映射 nacrea 参数（不跑模型）=="
HERE="$(cd "$(dirname "$0")" && pwd)"
WORLD="$HERE/../../../data/worlds/nacrea"
if [ -d "$WORLD" ]; then
    PYTHONPATH="$HERE/../../../src" python3 - "$WORLD" <<'EOF'
import sys
from dreamulator.gcm.mapping import map_world
params = map_world(sys.argv[1], "satellite_nacrea")
print(f"nacrea mapping OK: radius={params.radius:.4f} R_E, "
      f"flux={params.flux:.1f} W/m2, year={params.year:.1f} d")
EOF
else
    echo "（仓库内未找到 nacrea 数据，跳过映射冒烟）"
fi

echo "完成。后续运行：source $VENV_DIR/bin/activate && python scripts/climate/gcm/run_exoplasim.py ..."
