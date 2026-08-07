window.BENCHMARK_DATA = {
  "lastUpdate": 1786104946940,
  "repoUrl": "https://github.com/fyabc/dreamulator",
  "entries": {
    "Benchmark": [
      {
        "commit": {
          "author": {
            "email": "fyabc@mail.ustc.edu.cn",
            "name": "fyabc",
            "username": "fyabc"
          },
          "committer": {
            "email": "fyabc@mail.ustc.edu.cn",
            "name": "fyabc",
            "username": "fyabc"
          },
          "distinct": true,
          "id": "4acbb6d3bee70c21ee3016a80ae0c9cd56680804",
          "message": "fix: benchmark CI 写权限——仓库 workflow 权限改 read and write + job permissions 声明\n\n仓库 Actions 设置 default_workflow_permissions 已由 read 改为 write\n（经用户确认；否则 GITHUB_TOKEN 无法推送 perf-dashboard 分支）。\nbenchmarks.yml job 加 contents: write / pull-requests: write。\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
          "timestamp": "2026-08-04T08:03:15+08:00",
          "tree_id": "b78888a0722408ede1164298303e95282ef29932",
          "url": "https://github.com/fyabc/dreamulator/commit/4acbb6d3bee70c21ee3016a80ae0c9cd56680804"
        },
        "date": 1785801839809,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/micro/test_climate.py::test_climate_256",
            "value": 74.9851548140104,
            "unit": "iter/sec",
            "range": "stddev: 0.006562259709334959",
            "extra": "mean: 13.335972999993828 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_cvt_mesh.py::test_cvt_mesh_4096",
            "value": 4.603246378745583,
            "unit": "iter/sec",
            "range": "stddev: 0.056379706800565754",
            "extra": "mean: 217.23799200000826 msec\nrounds: 2"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_scalar_noise_50k",
            "value": 1.8900597349031851,
            "unit": "iter/sec",
            "range": "stddev: 0.8472179707921019",
            "extra": "mean: 529.0838070000063 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_noise_100k",
            "value": 1200.3182283613278,
            "unit": "iter/sec",
            "range": "stddev: 0.00006626807610203632",
            "extra": "mean: 833.1124000051204 usec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_fbm_100k_6oct",
            "value": 246.0184133954511,
            "unit": "iter/sec",
            "range": "stddev: 0.00010357565584572644",
            "extra": "mean: 4.064736400005131 msec\nrounds: 5"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "fyabc@mail.ustc.edu.cn",
            "name": "fyabc",
            "username": "fyabc"
          },
          "committer": {
            "email": "fyabc@mail.ustc.edu.cn",
            "name": "fyabc",
            "username": "fyabc"
          },
          "distinct": true,
          "id": "5a678dc6cce4ab44fb96461fa2775fa6634b9254",
          "message": "@\nRelease v0.15.0: 慢自转气候参数化 + gaia-m 样板世界全面改造 + map.yaml 回归修复\n\n气候 3A.3a（慢自转参数化）：\n- config 新增 hadley_extent_deg / polar_cell_start_deg（默认保持地球行为），\n  hadley_cell_wind() 环流胞边界广义化（~Ω^-1/2 标度）\n- climate 引擎与地质管线共读 terrain_config.yaml 气候调优项，消除双路径分叉\n\ngaia-m 样板世界改造（物理自洽化）：\n- 新增 Cadence/Vigil 4:2:1 拉普拉斯卫星链，补上 e_m=0.0025 的共振泵浦机制\n- Aegis 轨道内移 0.2795→0.2722 AU（混合变暖路径），温室 72→75K\n- 有效倾角 9° 启用季节项；气候再校准：均温 9.2→14.4°C，Köppen 9→13 类\n- 海陆分布翻案：潮汐物理（大潮点深海/侧点偏陆）→ 不对称混合案\n  （Aegis 深渊洋、虚空洋、世界岛、破碎群岛带）；合并重复设定文档\n- roadmap-analysis.md → roadmap.md 重组，拆分竞品分析/文明层设计文档\n\n修复：\n- map.yaml 导出回归（v0.14.0 引入）：从零重建缺 planet_id 致 API 崩溃，\n  现完整写入标识字段 + 回归测试 tests/test_map/test_export.py\n- gaia-m 设定数据不一致（轨道年 80.5→77.3d、季节 20.1→19.3d、极夜 31→38.7d）\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n@",
          "timestamp": "2026-08-04T21:57:10+08:00",
          "tree_id": "49b86b984368096524351d3b9f6b65353b964514",
          "url": "https://github.com/fyabc/dreamulator/commit/5a678dc6cce4ab44fb96461fa2775fa6634b9254"
        },
        "date": 1785851936492,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/micro/test_climate.py::test_climate_256",
            "value": 78.72576244366321,
            "unit": "iter/sec",
            "range": "stddev: 0.006070220711729757",
            "extra": "mean: 12.702322199999116 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_cvt_mesh.py::test_cvt_mesh_4096",
            "value": 5.138896338504205,
            "unit": "iter/sec",
            "range": "stddev: 0.035796867140103016",
            "extra": "mean: 194.59431250000137 msec\nrounds: 2"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_scalar_noise_50k",
            "value": 1.9829271060172071,
            "unit": "iter/sec",
            "range": "stddev: 0.8071748599352694",
            "extra": "mean: 504.30497266666663 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_noise_100k",
            "value": 895.4419319322509,
            "unit": "iter/sec",
            "range": "stddev: 0.000057710480008699856",
            "extra": "mean: 1.116767000002028 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_fbm_100k_6oct",
            "value": 236.2473339487677,
            "unit": "iter/sec",
            "range": "stddev: 0.00004200962984674447",
            "extra": "mean: 4.23285200000123 msec\nrounds: 5"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "fyabc@mail.ustc.edu.cn",
            "name": "fyabc",
            "username": "fyabc"
          },
          "committer": {
            "email": "fyabc@mail.ustc.edu.cn",
            "name": "fyabc",
            "username": "fyabc"
          },
          "distinct": true,
          "id": "432c8f533d31cb59870e6cddb9b9a4fb44e5bad5",
          "message": "Release v0.16.0: 地理锚定 + 板块大小偏态化 + 测试 CI\n\n三大主题：\n- 地理锚定（geography.yaml 机器可读规格 + 陆地偏置场 + 构造后重锚定），\n  命名海陆落到指定位置；含\"锚定静默丢失\"回归的修复（terrain generate\n  同源加载 + 输出到正式 maps/）。\n- 板块构造真实感：板块数坍缩修复、板块大小偏态化（乘法加权 Voronoi\n  重分区保持出生偏态，roadmap #6）、边界低频 fBm 弯曲（#7）、俯冲海沟\n  仅洋壳 7 km relief（#8，gaia-m 最深 −10484 m）。\n- 测试 CI（tests.yml）：pytest 硬门槛 + ruff F,E9 硬门槛 + mypy 报告档；\n  F 类 lint 存量清零。\n\n前端图层系统重构（kind 分组多选 + 烘焙/显示分离）随本版本发布。\ngaia-m 全量重建：26 板 CV=0.97、均温 12.7 °C、13 Köppen 类。\n\n版本 0.15.0 → 0.16.0（pyproject.toml + uv.lock + frontend/package.json），\nCHANGELOG 已更新。\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
          "timestamp": "2026-08-06T21:53:55+08:00",
          "tree_id": "3204f2428eecb7d1039e43e618d6e83212004ba7",
          "url": "https://github.com/fyabc/dreamulator/commit/432c8f533d31cb59870e6cddb9b9a4fb44e5bad5"
        },
        "date": 1786024575244,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/micro/test_climate.py::test_climate_256",
            "value": 78.52015390138631,
            "unit": "iter/sec",
            "range": "stddev: 0.006126476190625739",
            "extra": "mean: 12.735583799999972 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_cvt_mesh.py::test_cvt_mesh_4096",
            "value": 5.0331371684898745,
            "unit": "iter/sec",
            "range": "stddev: 0.042303721016219424",
            "extra": "mean: 198.68324000000115 msec\nrounds: 2"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_scalar_noise_50k",
            "value": 1.935062484270611,
            "unit": "iter/sec",
            "range": "stddev: 0.8286436977474092",
            "extra": "mean: 516.7791779999978 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_noise_100k",
            "value": 972.5626461580641,
            "unit": "iter/sec",
            "range": "stddev: 0.00011046939189672695",
            "extra": "mean: 1.0282114000062847 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_fbm_100k_6oct",
            "value": 232.00482421554798,
            "unit": "iter/sec",
            "range": "stddev: 0.0001032920158270437",
            "extra": "mean: 4.310255199999347 msec\nrounds: 5"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "fyabc@mail.ustc.edu.cn",
            "name": "fyabc",
            "username": "fyabc"
          },
          "committer": {
            "email": "fyabc@mail.ustc.edu.cn",
            "name": "fyabc",
            "username": "fyabc"
          },
          "distinct": true,
          "id": "15ff7d9aa34f9212c644597f8586e4f13d67176a",
          "message": "feat(tectonics): 岛弧/造山带小圆弧涌现机制（Frank 1968 / Tovish 1978）\n\n问题：plate_002/016 等边界平直，岛链/山脉不真实。根因是结构性的——\nVoronoi 平分线（点种子的最近邻/加权平分）几何上只能是测地线或\nApollonius 弧，无论种子怎么动都产不出岛弧的小圆弧；噪声扭曲只能加\n抖动，加不出系统弧度（频率扫描实测：base_freq 0.6→6 弯曲度不变）。\n\n机制（涌现式，非初始规定）：\n- Frank (1968)：俯冲板作为刚性球壳嵌入球面，交线为小圆弧——岛弧曲率\n  的几何起源；Tovish (1978)/Heuret & Lallemand (2005)：弧半径 ↔ 俯冲角\n  ↔ 汇聚速率经验相关。\n- 每次构造 resample 后 _trench_arc_relaxation 从*当前*运动学状态推断目标\n  弧：欧拉极相对速度 → 汇聚速率 → 倾角（30–70°）→ 弧矢比 0.10–0.30；\n  俯冲边界凸向俯冲板（日本/阿留申式），陆陆碰撞凸向 indenter（喜马拉雅/\n  阿尔卑斯式，×0.7）。弧矢在 arc_state 逐 resample 松弛生长 → 弧度随演化\n  涌现；最终 boundary warp 会重直化边界，故 warp 后再应用一次已发育弧矢。\n- 弯折边界（L/Z 形）经 _split_bent_segment 拐点拆分为更直子段、各带独立弧；\n  法向量改用 cross(mid, chord) 保证垂直弦（边均值差在弯折段会平行于弦）。\n\n配置：trench_arc（0=关，默认 1）。\n\ngaia-m 实测：plate_002/016 碰撞带 sagitta/chord 0.139 → 0.184（日本弧\n≈0.2 区间）；整体边界呈\"分段弧+折点\"形态；偏态保持（21 板 CV=0.84）。\n全量测试 253 通过；ruff F,E9 绿；新代码 mypy 零错误。\n\n文档：terrain-pipeline.md §D.11-11、roadmap #7 更新。\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
          "timestamp": "2026-08-06T22:45:39+08:00",
          "tree_id": "396dd76c970179584ff77fd6a115ff0bb334fdf7",
          "url": "https://github.com/fyabc/dreamulator/commit/15ff7d9aa34f9212c644597f8586e4f13d67176a"
        },
        "date": 1786027624838,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/micro/test_climate.py::test_climate_256",
            "value": 52.78859724067992,
            "unit": "iter/sec",
            "range": "stddev: 0.008908999369397347",
            "extra": "mean: 18.943485000002624 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_cvt_mesh.py::test_cvt_mesh_4096",
            "value": 3.706031496401712,
            "unit": "iter/sec",
            "range": "stddev: 0.056211390637919384",
            "extra": "mean: 269.8304104999991 msec\nrounds: 2"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_scalar_noise_50k",
            "value": 1.431038279615696,
            "unit": "iter/sec",
            "range": "stddev: 1.1186744714313963",
            "extra": "mean: 698.7933266666696 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_noise_100k",
            "value": 935.8049063846895,
            "unit": "iter/sec",
            "range": "stddev: 0.00007313048983674819",
            "extra": "mean: 1.0685988000034286 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_fbm_100k_6oct",
            "value": 194.83967130539205,
            "unit": "iter/sec",
            "range": "stddev: 0.00024141409925759194",
            "extra": "mean: 5.132425000002172 msec\nrounds: 5"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "fyabc@mail.ustc.edu.cn",
            "name": "fyabc",
            "username": "fyabc"
          },
          "committer": {
            "email": "fyabc@mail.ustc.edu.cn",
            "name": "fyabc",
            "username": "fyabc"
          },
          "distinct": true,
          "id": "8dc3614573c7664b2eaa7226e1fe57fb65d7d844",
          "message": "fix(tectonics): 弧交织修复 + 汇聚带沿弧分段 + 裂谷海加强与分叉\n\n用户可视化验证后的三组修复：\n\n1. 岛弧交织（板块互插、窄连接，如 plate_006/018/019）——根因：加权 Voronoi\n   与弧翻转两个独立边界决定方在同一尺度叠加；小盘被两侧弧对夹成辫状；无\n   最小宽度约束。对策：\n   - _split_bent_segment 改 BFS 序连续拆分（按弦投影拆分把 Z/U 形边界的两臂\n     交错混入子段，弧翻转散射成飞地）；\n   - 翻转带贴真实边界（BFS 窄带）——弦贴透镜会在弯折处切下尖端成 enclave；\n   - 弧矢按撤退板局部宽度封顶（窄板弧自动减弱，杜绝两弧对夹）；\n   - 最终多数票边界平滑（_relax_boundaries）溶解 <3 cell 辫带；\n   - enclave 守卫吸收 <600 cell 碎片。\n   验证：enclave=0、边界干净、弧 sag/chord 0.145–0.272 保持。\n\n2. 汇聚带沿弧分段（日本列岛式）：~800 km 波长 fBm 调制隆起幅度\n   [−0.25, 1.35]× 与带宽 0.7–1.3× → 主岛 + 小岛 + 弧间断陷海，替代均匀缎带。\n\n3. 裂谷海加强（geography.yaml）：radius 整体 ×1.7、strength 加强（首版太弱\n   碎成湖泊串）；中段加西支分叉（仿东非大裂谷 Western Rift）。验证：裂谷\n   走廊水体 100% 连通——单一陆间海。\n\ngaia-m 重建：22 板 CV=0.83，用户可视化验证通过。\n文档：terrain-pipeline.md §6.2 沿弧分段调制说明。\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
          "timestamp": "2026-08-06T23:30:28+08:00",
          "tree_id": "fe382d4f15e1343842381b8a271edac75373aebd",
          "url": "https://github.com/fyabc/dreamulator/commit/8dc3614573c7664b2eaa7226e1fe57fb65d7d844"
        },
        "date": 1786030439756,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/micro/test_climate.py::test_climate_256",
            "value": 53.83478236648647,
            "unit": "iter/sec",
            "range": "stddev: 0.007878804953173337",
            "extra": "mean: 18.575351399999818 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_cvt_mesh.py::test_cvt_mesh_4096",
            "value": 3.6833940758473913,
            "unit": "iter/sec",
            "range": "stddev: 0.05582772722639379",
            "extra": "mean: 271.4887355000002 msec\nrounds: 2"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_scalar_noise_50k",
            "value": 1.3995259907168218,
            "unit": "iter/sec",
            "range": "stddev: 1.145303250254322",
            "extra": "mean: 714.5276376666724 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_noise_100k",
            "value": 951.0675733562902,
            "unit": "iter/sec",
            "range": "stddev: 0.00004189360223655554",
            "extra": "mean: 1.0514499999942473 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_fbm_100k_6oct",
            "value": 195.96317428670423,
            "unit": "iter/sec",
            "range": "stddev: 0.00008918128377638019",
            "extra": "mean: 5.102999600001112 msec\nrounds: 5"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "fyabc@mail.ustc.edu.cn",
            "name": "fyabc",
            "username": "fyabc"
          },
          "committer": {
            "email": "fyabc@mail.ustc.edu.cn",
            "name": "fyabc",
            "username": "fyabc"
          },
          "distinct": true,
          "id": "e1d7fcda5a48d0be2185b9f443d8004262ae5eaf",
          "message": "Release v0.17.0: 岛弧小圆弧涌现 + 汇聚带沿弧分段 + 交织/裂谷修复\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
          "timestamp": "2026-08-06T23:33:11+08:00",
          "tree_id": "ed73ebb295ef2495637024bcea14e56ab3e7c4ae",
          "url": "https://github.com/fyabc/dreamulator/commit/e1d7fcda5a48d0be2185b9f443d8004262ae5eaf"
        },
        "date": 1786030457001,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/micro/test_climate.py::test_climate_256",
            "value": 53.72663234002158,
            "unit": "iter/sec",
            "range": "stddev: 0.007747069801161366",
            "extra": "mean: 18.612742999994225 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_cvt_mesh.py::test_cvt_mesh_4096",
            "value": 3.527426862935449,
            "unit": "iter/sec",
            "range": "stddev: 0.07609193820729437",
            "extra": "mean: 283.49276650000377 msec\nrounds: 2"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_scalar_noise_50k",
            "value": 1.4446897579020244,
            "unit": "iter/sec",
            "range": "stddev: 1.104012815638267",
            "extra": "mean: 692.1901359999936 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_noise_100k",
            "value": 987.8962945948161,
            "unit": "iter/sec",
            "range": "stddev: 0.00006270708987377095",
            "extra": "mean: 1.0122520000038548 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_fbm_100k_6oct",
            "value": 198.00727066848532,
            "unit": "iter/sec",
            "range": "stddev: 0.00009538170762109891",
            "extra": "mean: 5.05031960000224 msec\nrounds: 5"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "name": "fyabc",
            "username": "fyabc",
            "email": "fyabc@mail.ustc.edu.cn"
          },
          "committer": {
            "name": "fyabc",
            "username": "fyabc",
            "email": "fyabc@mail.ustc.edu.cn"
          },
          "id": "ed2c4c86889541f384d85bddda0099865e6d4b43",
          "message": "docs: 重组 Phase 2——terrain-pipeline 原位瘦身 3748→2415 行（−35.6%）\n\n- 22 个二级标题（§1–§17、附录 A–D）编号与文字冻结保留，源码 § 引用不失效\n- 附录 A 改指针清单；附录 D 整体上浮为 knowledge/geology/cortial_2019_notes.md\n  （顺修重复编号 D.11/D.12 与截断表尾行）\n- §4/§5/§6 科学推导并入 plate_tectonics/terrain_synthesis；§8 物理并入\n  energy_balance §7 降水 + 指向新气候学三篇；原位留实现摘要+指针\n- 残留对齐：geology 索引列入 cortial 笔记；roadmap/design_patterns 的\n  §D.11/§D.12 引用改指新文件\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
          "timestamp": "2026-08-06T19:34:30Z",
          "url": "https://github.com/fyabc/dreamulator/commit/ed2c4c86889541f384d85bddda0099865e6d4b43"
        },
        "date": 1786061493181,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/micro/test_climate.py::test_climate_256",
            "value": 53.88279240409717,
            "unit": "iter/sec",
            "range": "stddev: 0.007799085428403021",
            "extra": "mean: 18.55880060002164 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_cvt_mesh.py::test_cvt_mesh_4096",
            "value": 3.7495786949948906,
            "unit": "iter/sec",
            "range": "stddev: 0.05095743593291544",
            "extra": "mean: 266.6966294999611 msec\nrounds: 2"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_scalar_noise_50k",
            "value": 1.4345893923955175,
            "unit": "iter/sec",
            "range": "stddev: 1.1152733215252442",
            "extra": "mean: 697.063567666684 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_noise_100k",
            "value": 977.8522336095449,
            "unit": "iter/sec",
            "range": "stddev: 0.00008914439367232689",
            "extra": "mean: 1.0226494000107778 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_fbm_100k_6oct",
            "value": 196.53798342101533,
            "unit": "iter/sec",
            "range": "stddev: 0.00004347043959701638",
            "extra": "mean: 5.088075000026038 msec\nrounds: 5"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "fyabc@mail.ustc.edu.cn",
            "name": "fyabc",
            "username": "fyabc"
          },
          "committer": {
            "email": "fyabc@mail.ustc.edu.cn",
            "name": "fyabc",
            "username": "fyabc"
          },
          "distinct": true,
          "id": "7d0eb4104fbaa4eff0b17bfc08b16c58a274cec7",
          "message": "feat(geography): 高程锚定——钉扎 + 汇聚抬升抑制 + 双峰基准服从作者 + 海平面旋钮\n\n问题 1 阶段 2（roadmap #9 修复）。默认行为（无 geography/无 target/offset=0）\n逐位不变；268 测试全绿（+15 锚定测试）。\n\n- GeographyFeature +elevation_target_m/pin_strength：校准与全部后处理之后的\n  凸组合钉扎（核心饱和、边缘平滑）；shallow_sea/isthmus 可表达水深/陆高\n- 汇聚抬升抑制：强负偏置场（bias<−0.5）对汇聚正抬升与岛弧乘连续阻尼\n  clip(2·bias+2, 0.1, 1.0)；正常造山带无感\n- _apply_base_override：|bias|>0.5 处双峰基准服从作者——top-N 地壳泄漏的\n  continental cell 不再于 authored 海洋内隆起成高原（gaia-m 裂谷核心曾\n  +2050 m，现权威海核全 <0，裂谷海 ~−100 m）\n- sea_level_offset_m：水面标量移动（冰期海退 −120 m → (−120,0] 出露）；\n  大陆架/沿海平原/岛弧/分类/气候陆海掩膜参数化\n- 文档同步：terrain-pipeline §3.5、roadmap #9、design_patterns 模式 9、\n  CHANGELOG [Unreleased]\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
          "timestamp": "2026-08-07T08:27:11+08:00",
          "tree_id": "9a55461de4500cc40a4ab11d7af4cb364e92572d",
          "url": "https://github.com/fyabc/dreamulator/commit/7d0eb4104fbaa4eff0b17bfc08b16c58a274cec7"
        },
        "date": 1786062475847,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/micro/test_climate.py::test_climate_256",
            "value": 52.639858365938274,
            "unit": "iter/sec",
            "range": "stddev: 0.008953227148576073",
            "extra": "mean: 18.99701159999836 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_cvt_mesh.py::test_cvt_mesh_4096",
            "value": 3.598315020623512,
            "unit": "iter/sec",
            "range": "stddev: 0.05884567452482062",
            "extra": "mean: 277.9078525000074 msec\nrounds: 2"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_scalar_noise_50k",
            "value": 1.390382828202577,
            "unit": "iter/sec",
            "range": "stddev: 1.1522824541515868",
            "extra": "mean: 719.2263739999968 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_noise_100k",
            "value": 927.7733976595229,
            "unit": "iter/sec",
            "range": "stddev: 0.00021896481391052227",
            "extra": "mean: 1.0778493999964667 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_fbm_100k_6oct",
            "value": 196.05851029025487,
            "unit": "iter/sec",
            "range": "stddev: 0.000055842645879541065",
            "extra": "mean: 5.100518199998305 msec\nrounds: 5"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "fyabc@mail.ustc.edu.cn",
            "name": "fyabc",
            "username": "fyabc"
          },
          "committer": {
            "email": "fyabc@mail.ustc.edu.cn",
            "name": "fyabc",
            "username": "fyabc"
          },
          "distinct": true,
          "id": "3adc2cbb81de255e221fb807f5e7182f9659aaee",
          "message": "feat(maps): 高度图导入 UI + map.yaml 导入溯源（问题 1 阶段 1）\n\n- 前端：MapViewerPage 顶栏 ImportElevationButton（隐藏 file input +\n  覆盖确认 + 导入中态）；成功后 invalidate elevation/voronoi/cvtMesh/\n  plates/mapMeta 五个 query（staleTime 5min 必须主动失效）；结果 banner\n  展示 source_format/输出分辨率/stale_layers；plates 404 时左栏空态提示；\n  静态模式按钮禁用（client.ts 既有 liveOnly 守卫）\n- 后端：import-elevation 端点 +notes Form 参数；新增\n  ElevationImportProvenance 模型与 MapManager.record_elevation_import，\n  溯源写入 map.yaml（导入图不含板块构造数据的机器可读标记）\n- 测试：test_import_elevation.py（importer 形状/重采样/溯源落盘）\n- 文档：usage/map-workflow.md §10、CHANGELOG\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
          "timestamp": "2026-08-07T09:03:45+08:00",
          "tree_id": "bef0a3d87a2e80ff393f18a36c120f79c0bc076d",
          "url": "https://github.com/fyabc/dreamulator/commit/3adc2cbb81de255e221fb807f5e7182f9659aaee"
        },
        "date": 1786064673927,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/micro/test_climate.py::test_climate_256",
            "value": 78.69441557672307,
            "unit": "iter/sec",
            "range": "stddev: 0.0066069605741811",
            "extra": "mean: 12.707381999997835 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_cvt_mesh.py::test_cvt_mesh_4096",
            "value": 4.8173332042095405,
            "unit": "iter/sec",
            "range": "stddev: 0.05758010541445486",
            "extra": "mean: 207.58373099999972 msec\nrounds: 2"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_scalar_noise_50k",
            "value": 1.9734917600242676,
            "unit": "iter/sec",
            "range": "stddev: 0.8160236920474656",
            "extra": "mean: 506.71607566666665 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_noise_100k",
            "value": 1028.4142633688389,
            "unit": "iter/sec",
            "range": "stddev: 0.0000815446260597983",
            "extra": "mean: 972.3707999967246 usec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_fbm_100k_6oct",
            "value": 261.6177099702568,
            "unit": "iter/sec",
            "range": "stddev: 0.00007088999060446752",
            "extra": "mean: 3.8223711999989973 msec\nrounds: 5"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "fyabc@mail.ustc.edu.cn",
            "name": "fyabc",
            "username": "fyabc"
          },
          "committer": {
            "email": "fyabc@mail.ustc.edu.cn",
            "name": "fyabc",
            "username": "fyabc"
          },
          "distinct": true,
          "id": "8f18f814690e1e8ac1d41506c9ee7efd68374f6d",
          "message": "feat(geography): 密集偏置场导入 / Gleba 模式（问题 1 阶段 3）\n\n- geography_raster.png 约定：灰度 [0,1] → bias [−1,1]（中灰中立），\n  与 feature 场同级叠加（raster_weight 调和，GeographySpec 新字段）\n- 导入场同等待遇：参与 plates 地壳切分、tectonics 后重锚、合成阶段\n  抬升抑制/基准服从/钉扎；bias 经 sample_raster_at_cells 最近像素采样，\n  run_terrain_pipeline 一次计算三处共用（纯函数确定性不变）\n- 穿线：run_terrain_pipeline(geography_raster=) → generate_plates/\n  apply_geography_crust/synthesize_terrain（keyword-only，默认 None 逐位不变）\n- 加载：engine find_input + CLI _load_geography_raster（resolver 逐层向上搜，\n  分支可替换/继承）\n- API：POST /api/worlds/{w}/geography-raster（校验可解码后重编码 16-bit PNG）\n- 前端：GeographyRasterButton（顶栏，静态模式禁用）+ client.uploadGeographyRaster\n- 测试 +7：采样/加载往返/中灰无扰/raster-only 地壳/端到端 authored 海保持水下\n- 文档：terrain-pipeline §3.5 密集偏置场小节、design_patterns 模式 9、\n  map-workflow §10、CHANGELOG\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
          "timestamp": "2026-08-07T09:28:51+08:00",
          "tree_id": "f733f1923bf5f66f8609b7ff40733e37947221c4",
          "url": "https://github.com/fyabc/dreamulator/commit/8f18f814690e1e8ac1d41506c9ee7efd68374f6d"
        },
        "date": 1786066186940,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/micro/test_climate.py::test_climate_256",
            "value": 53.56712655723319,
            "unit": "iter/sec",
            "range": "stddev: 0.007904073444840273",
            "extra": "mean: 18.66816579999977 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_cvt_mesh.py::test_cvt_mesh_4096",
            "value": 3.7032640988237664,
            "unit": "iter/sec",
            "range": "stddev: 0.053094955385671445",
            "extra": "mean: 270.03205099998695 msec\nrounds: 2"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_scalar_noise_50k",
            "value": 1.428800247529165,
            "unit": "iter/sec",
            "range": "stddev: 1.119355226781997",
            "extra": "mean: 699.8878966666666 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_noise_100k",
            "value": 974.2236022668997,
            "unit": "iter/sec",
            "range": "stddev: 0.00008316322554390367",
            "extra": "mean: 1.0264583999742172 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_fbm_100k_6oct",
            "value": 199.28166135221366,
            "unit": "iter/sec",
            "range": "stddev: 0.000060935382312260014",
            "extra": "mean: 5.018023200000243 msec\nrounds: 5"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "fyabc@mail.ustc.edu.cn",
            "name": "fyabc",
            "username": "fyabc"
          },
          "committer": {
            "email": "fyabc@mail.ustc.edu.cn",
            "name": "fyabc",
            "username": "fyabc"
          },
          "distinct": true,
          "id": "87d2b9ca492eb26d477116af596b928c3b63a890",
          "message": "feat(terrain): 大陆与边界真实感批次 + gaia-m 重建（2026-08 用户反馈）\n\n代码：\n- 克拉通低地化：continental_undulation_m（多尺度动态地形起伏）+\n  板块内部 0.4× 均匀偏差（_PLATE_OFFSET_LAND_FRACTION）\n- 洋中脊 0.35× + 板块偏差解耦（-0.6×off），脊顶回 -2500 m\n- _relabel_leaked_crust：top-N 地壳泄漏孤立陆块重标洋壳，\n  洒点岛屿改为仅岛弧/热点/钉扎涌现\n- _smooth_partition 边界多数投票平滑（4 轮；二-hop 试过回退）+\n  _merge_plate_enclaves 飞地合并\n- 古造山带/裂谷：双频 meander 路径 + 沿走向宽度 0.55-1.45× 变化\n- warp 成本场 octaves 3→1（边界更顺）\n\ngaia-m：\n- geography.yaml：南大洋四环洋带（压制设计外自发出陆南方大陆）、\n  南极浅海 -120 m / 地峡 +120 m 钉扎\n- terrain_config：boundary_warp 0.9→0.3、boundary_uplift_noise 0.8\n- 全量重建数据（LFS）\n\n效果：>2000m 陆地 29.7%→12.3%（地球 10-15%），均陆高 1615→1238 m，\n点名边界出水 23%→0%，边界切向转角 76.5°→38.4°/步\n\n文档：terrain-pipeline §6.1 真实感批次、roadmap #5 状态、CHANGELOG\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
          "timestamp": "2026-08-07T11:44:36+08:00",
          "tree_id": "1577d9ff8aacb6b0d4824181b68899502472fa4a",
          "url": "https://github.com/fyabc/dreamulator/commit/87d2b9ca492eb26d477116af596b928c3b63a890"
        },
        "date": 1786074351647,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/micro/test_climate.py::test_climate_256",
            "value": 57.70155858373678,
            "unit": "iter/sec",
            "range": "stddev: 0.008598039291761018",
            "extra": "mean: 17.33055439999589 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_cvt_mesh.py::test_cvt_mesh_4096",
            "value": 3.7054119191839465,
            "unit": "iter/sec",
            "range": "stddev: 0.05856347669373421",
            "extra": "mean: 269.87552850000895 msec\nrounds: 2"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_scalar_noise_50k",
            "value": 1.5122170884412451,
            "unit": "iter/sec",
            "range": "stddev: 1.0567110622440405",
            "extra": "mean: 661.2807166666622 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_noise_100k",
            "value": 956.9088628512847,
            "unit": "iter/sec",
            "range": "stddev: 0.00006273277335751149",
            "extra": "mean: 1.0450316000003568 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_fbm_100k_6oct",
            "value": 196.05616554309657,
            "unit": "iter/sec",
            "range": "stddev: 0.0000521293447830728",
            "extra": "mean: 5.100579199995536 msec\nrounds: 5"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "fyabc@mail.ustc.edu.cn",
            "name": "fyabc",
            "username": "fyabc"
          },
          "committer": {
            "email": "fyabc@mail.ustc.edu.cn",
            "name": "fyabc",
            "username": "fyabc"
          },
          "distinct": true,
          "id": "6c3c8ac46af4b61a12e7801edc7c4d984da4d063",
          "message": "feat(geography): per-plate 地壳下限 + gaia-m 南方大陆（板块构成接近地球）\n\n- crust_plate_floor（默认 0.10）：global top-N 阈值下整板近零陆壳问题\n  （gaia-m 曾 64% 板块 <20% 陆，地球 ~40%）；mean bias ≥ −0.3 的板块\n  板内最高分洋壳提升到下限；authored 洋豁免；全局比由倒水校准吸收\n- _relabel_leaked_crust 加 authored 门（仅清 bias < −0.3 区域泄漏，\n  与 floor 交互不互斥）\n- gaia-m 预设：南方大陆×2（澳洲/南美类似，strength 0.5–0.6）——地球\n  南半球 19% 陆地来自南方大陆，纯洋环设计无法接近地球板块构成\n\n效果：NH 41.3% / SH 16.9% / global 29.1%（地球 39/19/29）；\n板块构成 >50% 陆 2→5、混合 7→12、<20% 陆 16→15(32 板)\n\n文档：terrain-pipeline §6.1 补 floor 说明；CHANGELOG\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
          "timestamp": "2026-08-07T12:00:36+08:00",
          "tree_id": "62f4be9b6cedc31c1a89b512d40635aadb62887d",
          "url": "https://github.com/fyabc/dreamulator/commit/6c3c8ac46af4b61a12e7801edc7c4d984da4d063"
        },
        "date": 1786075302656,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/micro/test_climate.py::test_climate_256",
            "value": 55.42032012194861,
            "unit": "iter/sec",
            "range": "stddev: 0.007216214308398754",
            "extra": "mean: 18.04392320000261 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_cvt_mesh.py::test_cvt_mesh_4096",
            "value": 3.7992578241022814,
            "unit": "iter/sec",
            "range": "stddev: 0.0511557503935967",
            "extra": "mean: 263.2093019999999 msec\nrounds: 2"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_scalar_noise_50k",
            "value": 1.469499818558405,
            "unit": "iter/sec",
            "range": "stddev: 1.0867966560032722",
            "extra": "mean: 680.5036566666681 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_noise_100k",
            "value": 984.6213953506623,
            "unit": "iter/sec",
            "range": "stddev: 0.00007070557028750603",
            "extra": "mean: 1.0156187999996291 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_fbm_100k_6oct",
            "value": 197.7081669289914,
            "unit": "iter/sec",
            "range": "stddev: 0.00006550653536772002",
            "extra": "mean: 5.057959999999184 msec\nrounds: 5"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "fyabc@mail.ustc.edu.cn",
            "name": "fyabc",
            "username": "fyabc"
          },
          "committer": {
            "email": "fyabc@mail.ustc.edu.cn",
            "name": "fyabc",
            "username": "fyabc"
          },
          "distinct": true,
          "id": "9dd5ad850acef5664fb7c5dfdfcda829c2a1a11b",
          "message": "Release v0.18.0: 高程锚定与 Gleba 模式 + 真实感批次 + CI 全硬门槛 + docs 重组\n\nAdded:\n- 地理高程锚定（elevation_target_m/pin_strength）+ 海平面偏移旋钮\n- 高度图导入 UI + map.yaml 导入溯源\n- 密集偏置场导入 / Gleba 模式（geography_raster.png + raster_weight）\n- 大陆与边界真实感批次（克拉通低地化、洋中脊归位、泄漏重标、边界平滑、\n  古造山带 meander、per-plate 地壳下限、gaia-m 南方大陆/南大洋环/钉扎）\n- docs 重组全 Phase（terrain-pipeline 瘦身、knowledge 扩充、路线图单点收敛）\n\nChanged:\n- CI 全硬门槛（ruff 全规则 + format + mypy strict）；技术债三连清偿\n\nFixed:\n- roadmap #9 锚定裂谷推上海面；Pillow 13 弃用；scripts 下沉包内\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
          "timestamp": "2026-08-07T12:07:51+08:00",
          "tree_id": "a865b06a1874423c37948255d430d739e45140f5",
          "url": "https://github.com/fyabc/dreamulator/commit/9dd5ad850acef5664fb7c5dfdfcda829c2a1a11b"
        },
        "date": 1786075722588,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/micro/test_climate.py::test_climate_256",
            "value": 59.303721411711706,
            "unit": "iter/sec",
            "range": "stddev: 0.007544488151502081",
            "extra": "mean: 16.862348199998678 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_cvt_mesh.py::test_cvt_mesh_4096",
            "value": 3.7469015442624816,
            "unit": "iter/sec",
            "range": "stddev: 0.05768583697012882",
            "extra": "mean: 266.8871834999962 msec\nrounds: 2"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_scalar_noise_50k",
            "value": 1.5331805530836995,
            "unit": "iter/sec",
            "range": "stddev: 1.0418239868016814",
            "extra": "mean: 652.2389016666637 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_noise_100k",
            "value": 942.4010153799987,
            "unit": "iter/sec",
            "range": "stddev: 0.00008239176889564799",
            "extra": "mean: 1.0611194000006208 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_fbm_100k_6oct",
            "value": 195.14236787092375,
            "unit": "iter/sec",
            "range": "stddev: 0.00006446395459312598",
            "extra": "mean: 5.124463799995738 msec\nrounds: 5"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "fyabc@mail.ustc.edu.cn",
            "name": "fyabc",
            "username": "fyabc"
          },
          "committer": {
            "email": "fyabc@mail.ustc.edu.cn",
            "name": "fyabc",
            "username": "fyabc"
          },
          "distinct": true,
          "id": "39d195391163137fb2f90066ff9f728a0bb97703",
          "message": "fix(engine): 无 geography.yaml 的世界无法构建（v0.16.0 回归）+ terrain-dev 重建\n\n- BaseEngine 新增 optional_input_files（缺省合法、回退默认）；geological\n  的 terrain_config.yaml / geography.yaml 改可选（CLI 本就有\n  from_planet_config 回退，engine 校验却把它们当必需）\n- earth/terrain-dev 以 v0.18.0 真实感机制 force 重建（geological+climate）\n- CHANGELOG [Unreleased] 记录\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
          "timestamp": "2026-08-07T12:16:03+08:00",
          "tree_id": "9c0bef72f2ec04e1e9bde6caeff4b1262f0dbe0e",
          "url": "https://github.com/fyabc/dreamulator/commit/39d195391163137fb2f90066ff9f728a0bb97703"
        },
        "date": 1786076216209,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/micro/test_climate.py::test_climate_256",
            "value": 53.721503428506765,
            "unit": "iter/sec",
            "range": "stddev: 0.007997614954856782",
            "extra": "mean: 18.614519999999857 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_cvt_mesh.py::test_cvt_mesh_4096",
            "value": 3.6535443489508475,
            "unit": "iter/sec",
            "range": "stddev: 0.05522033664346736",
            "extra": "mean: 273.70681850000267 msec\nrounds: 2"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_scalar_noise_50k",
            "value": 1.4280514770687096,
            "unit": "iter/sec",
            "range": "stddev: 1.121010575008916",
            "extra": "mean: 700.254868999996 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_noise_100k",
            "value": 967.8477118744229,
            "unit": "iter/sec",
            "range": "stddev: 0.00006716317847315574",
            "extra": "mean: 1.0332203999979583 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_fbm_100k_6oct",
            "value": 197.74321990902425,
            "unit": "iter/sec",
            "range": "stddev: 0.00004793054744585714",
            "extra": "mean: 5.057063399999606 msec\nrounds: 5"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "fyabc@mail.ustc.edu.cn",
            "name": "fyabc",
            "username": "fyabc"
          },
          "committer": {
            "email": "fyabc@mail.ustc.edu.cn",
            "name": "fyabc",
            "username": "fyabc"
          },
          "distinct": true,
          "id": "0e45e0ecab8fc2472fb0f3285fbbcc6ffd80779d",
          "message": "feat(ocean): P1 管线集成 + 最小前端图层\n\n后端:\n- VoronoiCell +3 字段: ocean_current_east_m_s, ocean_current_north_m_s, sst_anomaly_c\n- climate_simulator stage 2.5 (风→洋流→SST修正→BFS→Koppen)\n- pipeline_types: ocean_* 配置段替换死参数 num_gyres\n- 回写自动通过 model_dump_json() (字段在 CVTMesh.cells 中)\n\n前端:\n- ColorMode + currents, 5th shader slot (u_currents)\n- layerBakes: speed heatmap (蓝→青→黄→红) + LayerTextures.currents\n- MapLayerPanel: 气候组 feature 叠加层\n- helpContent: 洋流条目 + koppen 措辞更新\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
          "timestamp": "2026-08-07T18:28:37+08:00",
          "tree_id": "23366e16c6501a2605a783976189fa0de161f480",
          "url": "https://github.com/fyabc/dreamulator/commit/0e45e0ecab8fc2472fb0f3285fbbcc6ffd80779d"
        },
        "date": 1786098566916,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/micro/test_climate.py::test_climate_256",
            "value": 29.375812685515825,
            "unit": "iter/sec",
            "range": "stddev: 0.0380711533112873",
            "extra": "mean: 34.041611400016336 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_cvt_mesh.py::test_cvt_mesh_4096",
            "value": 3.534094785390636,
            "unit": "iter/sec",
            "range": "stddev: 0.06506129374521309",
            "extra": "mean: 282.957888999988 msec\nrounds: 2"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_scalar_noise_50k",
            "value": 1.3767430722037317,
            "unit": "iter/sec",
            "range": "stddev: 1.167520413728339",
            "extra": "mean: 726.3519390000018 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_noise_100k",
            "value": 912.6262572741251,
            "unit": "iter/sec",
            "range": "stddev: 0.00008726106206928906",
            "extra": "mean: 1.0957388000065293 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_fbm_100k_6oct",
            "value": 192.40961760261166,
            "unit": "iter/sec",
            "range": "stddev: 0.00011440055350819627",
            "extra": "mean: 5.197245399995154 msec\nrounds: 5"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "fyabc@mail.ustc.edu.cn",
            "name": "fyabc",
            "username": "fyabc"
          },
          "committer": {
            "email": "fyabc@mail.ustc.edu.cn",
            "name": "fyabc",
            "username": "fyabc"
          },
          "distinct": true,
          "id": "35dc66b71becc2a87336a44b99e207f23a49d600",
          "message": "fix(ocean): CG→GMRES (Stommel op非对称) + Windows GBK编码修复\n\n- ocean_circulation.py: cg→gmres (Stommel A=β·G+R·L 的 G_east 非对称)\n- climate_simulator.py: Köppen→Koppen (GBK console)\n- climate.py: terrain_config.yaml→optional_input_files (earth/climate-dev缺该文件)\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
          "timestamp": "2026-08-07T18:38:14+08:00",
          "tree_id": "31b87980aa39d50bf1e3b94a90a17d519fc482c7",
          "url": "https://github.com/fyabc/dreamulator/commit/35dc66b71becc2a87336a44b99e207f23a49d600"
        },
        "date": 1786099149984,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/micro/test_climate.py::test_climate_256",
            "value": 48.7169134210861,
            "unit": "iter/sec",
            "range": "stddev: 0.024942689486837196",
            "extra": "mean: 20.526751999997828 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_cvt_mesh.py::test_cvt_mesh_4096",
            "value": 5.775197781321509,
            "unit": "iter/sec",
            "range": "stddev: 0.03767542994751061",
            "extra": "mean: 173.15424299999904 msec\nrounds: 2"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_scalar_noise_50k",
            "value": 2.2593123591245576,
            "unit": "iter/sec",
            "range": "stddev: 0.713803079391755",
            "extra": "mean: 442.6125479999949 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_noise_100k",
            "value": 1089.965299860278,
            "unit": "iter/sec",
            "range": "stddev: 0.00006847989011920933",
            "extra": "mean: 917.4604000037334 usec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_fbm_100k_6oct",
            "value": 271.75227497410685,
            "unit": "iter/sec",
            "range": "stddev: 0.00003130358008210983",
            "extra": "mean: 3.679822000000854 msec\nrounds: 5"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "fyabc@mail.ustc.edu.cn",
            "name": "fyabc",
            "username": "fyabc"
          },
          "committer": {
            "email": "fyabc@mail.ustc.edu.cn",
            "name": "fyabc",
            "username": "fyabc"
          },
          "distinct": true,
          "id": "cb1d22c488cfece8fed84292814ef281128e9b20",
          "message": "feat(ocean): P1 洋流管线集成 + 2D/3D 前端箭头\n\n后端:\n- VoronoiCell +3 字段: ocean_current_east_m_s, ocean_current_north_m_s, sst_anomaly_c\n- climate_simulator stage 2.5: Stommel GMRES 求解 + SST 平流\n- pipeline_types: ocean_* 配置段替换 num_gyres\n- RHS 符号修正 (curl_z → -curl_z → 回滚到 curl_z)\n- climate engine: terrain_config.yaml → optional_input_files\n\n前端:\n- 2D: MapSvgOverlay SVG 矢量箭头 (4.5° 网格, 品红暖流/青绿寒流)\n- 3D: GlobeCurrentArrows rAF canvas 叠加 (含背面剔除+边缘淡出)\n- GlobeViewer 新增 globeProjectRef (lon,lat)→screen 投影\n- ColorMode + currents, shader 5th slot, layerBakes, helpContent\n- 修复 east=r̂×k̂\n\n验证: earth/climate-dev 洋流方向正确 (湾流北流、秘鲁北流=向赤道、黑潮北流)\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
          "timestamp": "2026-08-07T20:14:45+08:00",
          "tree_id": "f6a65cded45d486779b25caff81c502de2be4a9d",
          "url": "https://github.com/fyabc/dreamulator/commit/cb1d22c488cfece8fed84292814ef281128e9b20"
        },
        "date": 1786104946133,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/micro/test_climate.py::test_climate_256",
            "value": 29.782705144997156,
            "unit": "iter/sec",
            "range": "stddev: 0.04079940197773421",
            "extra": "mean: 33.5765336000037 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_cvt_mesh.py::test_cvt_mesh_4096",
            "value": 3.468934840350081,
            "unit": "iter/sec",
            "range": "stddev: 0.0717577462838935",
            "extra": "mean: 288.2729270000013 msec\nrounds: 2"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_scalar_noise_50k",
            "value": 1.4480084535544437,
            "unit": "iter/sec",
            "range": "stddev: 1.1071788144665817",
            "extra": "mean: 690.6037029999984 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_noise_100k",
            "value": 939.0754163932642,
            "unit": "iter/sec",
            "range": "stddev: 0.000066415885564188",
            "extra": "mean: 1.0648772000024564 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_fbm_100k_6oct",
            "value": 192.6278768826978,
            "unit": "iter/sec",
            "range": "stddev: 0.00007509850569825057",
            "extra": "mean: 5.191356600005292 msec\nrounds: 5"
          }
        ]
      }
    ]
  }
}