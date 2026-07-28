"""Dreamulator - Fantasy world building and simulation tool grounded in real science."""

from importlib.metadata import PackageNotFoundError, version

# 版本号唯一来源是 pyproject.toml；此处运行时从已安装包的元数据读取，
# 升级版本只需改 pyproject.toml（配合 `uv version --bump`），无需再同步本文件。
try:
    __version__ = version("dreamulator")
except PackageNotFoundError:  # 包未安装时的兜底
    __version__ = "0.0.0"
