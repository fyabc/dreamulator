window.BENCHMARK_DATA = {
  "lastUpdate": 1786062476410,
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
      }
    ]
  }
}