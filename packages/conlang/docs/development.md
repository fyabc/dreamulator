# 开发指南

## 运行测试

```bash
# 仅运行 conlang 测试
cd packages/conlang && uv run pytest

# 从 dreamulator 根目录运行全部测试（conlang + dreamulator）
uv run pytest packages/conlang/tests/ tests/

# 带覆盖率报告
uv run pytest packages/conlang/tests/ --cov=conlang --cov-report=term-missing
```

## 代码检查

```bash
# Lint
uv run ruff check packages/conlang/src/ packages/conlang/tests/

# 自动格式化
uv run ruff format packages/conlang/src/ packages/conlang/tests/

# 类型检查
uv run mypy packages/conlang/src/
```

## 构建分发包

```bash
cd packages/conlang && uv build
# 产出在 packages/conlang/dist/
#   conlang-0.1.0-py3-none-any.whl
#   conlang-0.1.0.tar.gz
```

## 独立安装验证

```bash
pip install packages/conlang/dist/conlang-0.1.0-py3-none-any.whl
conlang version
conlang tokenize "p^h a"
```
