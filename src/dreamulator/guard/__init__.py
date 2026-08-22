"""守护轴（Guard / Harness）——校验 · 审计 · 设定维护的共享内核。

与生成轴（``engine`` / ``map`` / ``civmap``）正交：生成轴产出 derived 数据，
守护轴校验「设定 vs derived vs 理论」的一致性并做过期检测。设计总纲见
``docs/design/harness.md``。

包结构（对应 harness.md §4.1）：

- ``facts.py``    — 事实上下文（扩展 doc_render，§5），agent 取证的事实库
- ``queries.py``  — 几何/空间查询（纯函数，§6，P2）
- ``stale.py``    — 过期检测（指纹 + 渲染 diff，§7，P1）
- ``critique.py`` — 拷问编排（griller/answerer，§9，P3）

内核四块全是纯函数、无 RNG、可单测（与 ``physical_inputs.py`` 同风格）。
"""

from dreamulator.guard.adr import (
    DEFAULT_MAX_ACCEPTED,
    accept,
    archive,
    count_accepted,
    deprecate,
    supersede,
)
from dreamulator.guard.critique import DIMENSIONS, Dimension, gather_facts
from dreamulator.guard.facts import build_fact_context
from dreamulator.guard.queries import list_queries, run_query
from dreamulator.guard.stale import (
    NO_YAML_FINGERPRINT,
    Finding,
    check_broken_refs,
    check_decision_records,
    layer_input_fingerprint,
    render_claims,
    write_baseline,
)

__all__ = [
    "DEFAULT_MAX_ACCEPTED",
    "DIMENSIONS",
    "Dimension",
    "Finding",
    "NO_YAML_FINGERPRINT",
    "accept",
    "archive",
    "build_fact_context",
    "check_broken_refs",
    "check_decision_records",
    "count_accepted",
    "deprecate",
    "gather_facts",
    "layer_input_fingerprint",
    "list_queries",
    "render_claims",
    "run_query",
    "supersede",
    "write_baseline",
]
