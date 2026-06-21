# 项目结构

```
packages/conlang/
├── pyproject.toml                 # 独立包配置（hatchling 构建）
├── README.md                      # 项目简介
├── docs/                          # 文档
│   ├── asciipa-reference.md       #   ASCIIPA 语法速查表
│   ├── asciipa-vs-xsampa.md       #   ASCIIPA 与 X-SAMPA 对比
│   ├── sca-guide.md               #   SCA 引擎开发指南
│   ├── cli.md                     #   命令行工具参考
│   ├── project-structure.md       #   项目结构（本文件）
│   ├── development.md             #   开发指南
│   ├── roadmap.md                 #   路线图
│   └── knowledge/                 #   领域知识库
│       └── sca.md                 #     SCA 音变理论与规则语法
├── src/conlang/
│   ├── __init__.py                # 包入口 + 版本号
│   ├── cli.py                     # 独立 CLI 入口（Typer）
│   ├── phonology/                 # 语音学模块
│   │   ├── __init__.py
│   │   ├── asciipa.py             #   ASCIIPA 词法分析器 + IPA 互转
│   │   ├── ipa_table.py           #   IPA 音标映射表（~100 音素）
│   │   ├── sca.py                 #   SCA 音变引擎
│   │   ├── features.py            #   音素特征矩阵
│   │   └── xsampa.py              #   X-SAMPA 转换 + TTS 桥接
│   ├── morphology/                # 形态学模块
│   │   ├── __init__.py
│   │   ├── fst.py                 #   有限状态转换器引擎
│   │   ├── affix.py               #   词缀规则工厂函数
│   │   └── harmony.py             #   元音和谐 + 辅音突变
│   └── lexicon/                   # 词汇学模块
│       ├── __init__.py
│       ├── entry.py               #   词典条目 Pydantic 模型
│       ├── database.py            #   YAML 持久化数据库
│       └── etymology.py           #   词源追踪链
└── tests/                         # 测试套件
    ├── test_asciipa.py            #   ASCIIPA tokenizer + 编解码
    ├── test_sca.py                #   SCA 引擎（含瓦克里克语集成测试）
    ├── test_morphology.py         #   FST + 元音和谐
    └── test_lexicon.py            #   词典数据库 + 词源追踪
```

## 模块说明

### phonology（语音学）

| 文件 | 职责 |
|:---|:---|
| `asciipa.py` | ASCIIPA 正则词法分析器，将字符串拆解为不可分割的 Token；IPA ↔ ASCIIPA 双向转换 |
| `ipa_table.py` | 完整的 IPA ↔ ASCIIPA 映射表，覆盖肺部气流辅音、非肺部气流辅音（搭嘴音、内爆音、挤喉音）、元音、附加符号 |
| `sca.py` | Token-aware SCA 引擎。支持音类定义、环境匹配（左右上下文 + 词边界 `#`）、概率规则 `[0.X]`、词频加权、多代模拟 |
| `features.py` | 音素特征矩阵数据库。支持 `[+voice]` `[manner:stop]` 式特征查询，为特征音变规则提供基础 |
| `xsampa.py` | ASCIIPA → X-SAMPA 转换桥，用于对接 eSpeak-NG TTS 引擎 |

### morphology（形态学）

| 文件 | 职责 |
|:---|:---|
| `fst.py` | 规则式有限状态转换器，支持前缀/后缀/中缀/环缀附着和解析 |
| `affix.py` | 词缀规则工厂函数：`suffix_rule()`、`prefix_rule()`、`agglutinative_chain()` |
| `harmony.py` | 元音和谐引擎（前/后元音分类 + 后缀交替）和辅音突变引擎（凯尔特语风格） |

### lexicon（词汇学）

| 文件 | 职责 |
|:---|:---|
| `entry.py` | Pydantic 模型：`LexemeEntry`（含 POS、Register、频率、语义场）、`CognateSet` |
| `database.py` | 内存词典数据库 + YAML 持久化。支持按词性/语域/语义场/标签过滤和全文搜索 |
| `etymology.py` | 词源追踪链：音变、借用、复合、语义漂移等派生类型的记录和追溯 |
