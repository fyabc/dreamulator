---
name: narrate
description: 为 dreamulator 世界生成口语化描述（调用 dreamulator narrate）。当用户要求描述、介绍或叙述某个世界或分支时使用（如 narrate earth --branch l4-companion）。
---

为 dreamulator 世界生成口语化描述。

用户输入的参数: $ARGUMENTS

（宿主没有替换上面的 `$ARGUMENTS` 时，从用户请求中读取世界名与选项，例如 `earth --branch l4-companion`。）

请运行以下命令:

```bash
uv run dreamulator narrate $ARGUMENTS
```

如果命令因缺少 `anthropic` 依赖而失败（提示 `uv sync --extra narrate`），先运行该安装命令然后重试。

将命令输出的描述内容直接展示给用户，不要添加额外解释。
