# 模拟引擎（src/dreamulator/engine/）规则

引擎继承 `BaseEngine`，声明 `layer`、`requires`、`input_files`、`output_files`，
由 `pipeline.py` 自动拓扑排序执行；`find_input()` 沿层级链向上搜索输入文件，
支持从分支继承数据。本文件承接根目录 `AGENTS.md` 拆出的输入数据模式；引擎
设计纪律（第一性计算、同物理等十条）见根目录。

## 输入模式与一致性校验

开发新引擎时，输入数据遵循以下模式（参考天文学引擎 `engine/astronomy.py`）：

1. **自变量/因变量分类**：每个引擎的数据模型明确区分自变量（输入）和因变量
   （输出）。自变量字段设为可选，通过 `model_validator` 确保至少提供一组完整
   自变量。
2. **混合输入模式**：允许可选的替代自变量集。例如 `Star` 模型支持 mass-only、
   luminosity-only、both 三种输入方式，引擎内部根据实际提供的字段选择计算路径。
3. **手动覆盖 + 一致性校验**：因变量字段允许用户手动填写（覆盖引擎计算值）。
   当用户同时提供自变量和因变量时，引擎正向计算预期值并与用户值比较：
   偏差 ≤ 阈值（通常 20%）→ 静默接受；偏差 > 阈值 → 记录 warning
   （`EngineResult.warnings`），严格模式下抛错。
4. **纯计算模块分离**：物理公式实现为纯函数模块（如 `engine/stellar_physics.py`），
   与引擎 IO 层（`engine/astronomy.py`）分离。纯函数无 IO、无 RNG，可独立
   单元测试。
