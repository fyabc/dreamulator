为 dreamulator 世界生成口语化描述。

用户输入的参数: $ARGUMENTS

请运行以下命令:

```bash
uv run dreamulator narrate $ARGUMENTS
```

如果命令因缺少 `anthropic` 依赖而失败（提示 `uv sync --extra narrate`），先运行该安装命令然后重试。

将命令输出的描述内容直接展示给用户，不要添加额外解释。
