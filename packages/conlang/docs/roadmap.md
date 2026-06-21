# 路线图

## 已完成

- [x] **Phase 1** —— phonology（ASCIIPA + SCA）、morphology（FST）、lexicon（词典库）

## 计划中

- [ ] **Phase 2** —— SCA v2 增强
  - 概率音变 + 词频加权的世代模拟
  - 特征矩阵音变规则（`[+aspirated] > [-aspirated]`）
  - 社会语域过滤器（神圣语/俗语分别演化）
- [ ] **Phase 3** —— syntax 句法模块
  - 语序生成器（SVO/SOV/VSO 等参数化）
  - 中心语方向参数
  - 依存句法树
  - 格标记分配
- [ ] **Phase 4** —— orthography 文字系统模块
  - 辅音音素文字（Abjad）转写器
  - 元音附标文字（Abugida）转写器
  - 音节文字（Syllabary）转写器
  - 语素文字（Logography）支持
- [ ] **Phase 5** —— TTS 深度集成
  - ToucanTTS (IMS-Toucan) 作为可选神经 TTS 后端，支持非肺部气流辅音（搭嘴音、挤喉音、内爆音）
  - eSpeak-NG 保留为轻量级后端（注：`[[...]]` 接口不支持搭嘴音等，详见 `espeak_ng.py` 文档）
  - 神经网络语音合成（Coqui TTS / VITS）
  - SCA + TTS 全自动流水线（规则推演 → 直接听到声音）
