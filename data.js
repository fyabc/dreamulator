window.BENCHMARK_DATA = {
  "lastUpdate": 1792523939982,
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
          "id": "90b8b3ece88ce2f1570452b445ddfc525c3137e7",
          "message": "docs(privacy): 计算环境规格泛化——型号与配额出库，测速环境保留\n\n设计文档不再记录计算环境的具体硬件型号与配额数字：资源登记块改为\n量级表述（多卡 GPU 服务器/单卡百 GB 级显存/配额数十核/TB 级内存），\n本机侧改消费级 GPU 泛称；渲染链硬件基线保留 RTX 3060 作跑通样例但\n去整机型号；S6 PoC 与实测能力表等测速记录保留实测环境。全历史同步\n泛化随后以 filter-repo 文本替换完成（提交结构不变）。\n\nCo-Authored-By: Claude Code <noreply@anthropic.com>",
          "timestamp": "2026-10-18T05:45:05+08:00",
          "tree_id": "ef86143cd9f76f5ab0159f977905af890091d141",
          "url": "https://github.com/fyabc/dreamulator/commit/90b8b3ece88ce2f1570452b445ddfc525c3137e7"
        },
        "date": 1792273768640,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/micro/test_climate.py::test_climate_256",
            "value": 0.31557961947576996,
            "unit": "iter/sec",
            "range": "stddev: 0.14790347627314548",
            "extra": "mean: 3.1687724374 sec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_cvt_mesh.py::test_cvt_mesh_4096",
            "value": 2.977990059629997,
            "unit": "iter/sec",
            "range": "stddev: 0.028428625682628158",
            "extra": "mean: 335.79695699999945 msec\nrounds: 2"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_scalar_noise_50k",
            "value": 1.4235318546570213,
            "unit": "iter/sec",
            "range": "stddev: 1.125963996436519",
            "extra": "mean: 702.4781333333318 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_noise_100k",
            "value": 950.0866288986189,
            "unit": "iter/sec",
            "range": "stddev: 0.00008101019120404393",
            "extra": "mean: 1.0525356000002262 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_fbm_100k_6oct",
            "value": 195.60803623546886,
            "unit": "iter/sec",
            "range": "stddev: 0.00012348853976584497",
            "extra": "mean: 5.112264399997457 msec\nrounds: 5"
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
          "id": "9c81817dfa8b13955ac2703b2e5b917f11919264",
          "message": "fix(map,media): 区域链行星半径两修——分支导出 root 兜底 + 图纸经纬网按 meta 半径\n\n- read_radius_km 加 world_dir 参数：分支 maps 目录只有构建产物、没有手写\n  map.yaml 时回退同行星根目录，不再静默回退地球 6371 km（此前 --branch 导出\n  的包 meta radius_km 与窗口数学整体失真：nacrea 6817 km 半径下 550 km 窗\n  实盖约 588 km，横向比例差 6.5%）\n- carto/biome 图纸经纬网与度数刻度从硬编码 111.19 km/° 改为按 meta 半径\n  （ColorizeInputs.km_per_deg，load_inputs 从 radius_km 取 πR/180；旧包\n  回退地球值）\n- 手册差距清单勾销（经纬网地球常数项删除；相邻块对齐项改已定向画布方案）\n- 测试：半径回退 2 项 + 经纬网行星比例 1 项\n\nCo-Authored-By: Claude Code <noreply@anthropic.com>",
          "timestamp": "2026-10-18T10:12:25+08:00",
          "tree_id": "fff07ab514bfa68ee29fe4f5fc1cb18f32130b9a",
          "url": "https://github.com/fyabc/dreamulator/commit/9c81817dfa8b13955ac2703b2e5b917f11919264"
        },
        "date": 1792292532598,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/micro/test_climate.py::test_climate_256",
            "value": 0.32537031647417536,
            "unit": "iter/sec",
            "range": "stddev: 0.08542385494318512",
            "extra": "mean: 3.0734211123999997 sec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_cvt_mesh.py::test_cvt_mesh_4096",
            "value": 3.2722140360698084,
            "unit": "iter/sec",
            "range": "stddev: 0.011681116939844853",
            "extra": "mean: 305.60348100000215 msec\nrounds: 2"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_scalar_noise_50k",
            "value": 1.5047392266029505,
            "unit": "iter/sec",
            "range": "stddev: 1.0611758702248044",
            "extra": "mean: 664.5669776666665 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_noise_100k",
            "value": 977.1932859061588,
            "unit": "iter/sec",
            "range": "stddev: 0.00009458676810187867",
            "extra": "mean: 1.023338999993939 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_fbm_100k_6oct",
            "value": 199.71174405715522,
            "unit": "iter/sec",
            "range": "stddev: 0.00004982537417140781",
            "extra": "mean: 5.0072167999985595 msec\nrounds: 5"
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
          "id": "45d2c3bcbb657b8ba4793821a87269476dc3994b",
          "message": "fix(media): relief 遥感图经纬网补传行星半径——_graticule 第三调用点漏改\n\n首批半径修复只改了 carto/biome 两处调用点，relief_render 的同名调用仍走\n地球默认 111.19 km/°，三种图纸度数刻度不一致（~7%）。补传\ninputs.km_per_deg 后三图同源；五包遥感图已重渲，探针实证 118.98。\n\nCo-Authored-By: Claude Code <noreply@anthropic.com>",
          "timestamp": "2026-10-18T11:26:39+08:00",
          "tree_id": "6e8260eaceec5db9577d1b69250af4ac0de162fa",
          "url": "https://github.com/fyabc/dreamulator/commit/45d2c3bcbb657b8ba4793821a87269476dc3994b"
        },
        "date": 1792296120666,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/micro/test_climate.py::test_climate_256",
            "value": 0.4602645772837127,
            "unit": "iter/sec",
            "range": "stddev: 0.05762751854081117",
            "extra": "mean: 2.1726633969999996 sec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_cvt_mesh.py::test_cvt_mesh_4096",
            "value": 3.817945987476151,
            "unit": "iter/sec",
            "range": "stddev: 0.004209598294343169",
            "extra": "mean: 261.92093949999776 msec\nrounds: 2"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_scalar_noise_50k",
            "value": 1.9586330229016642,
            "unit": "iter/sec",
            "range": "stddev: 0.8149485731947738",
            "extra": "mean: 510.56016533333326 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_noise_100k",
            "value": 1237.9350846656318,
            "unit": "iter/sec",
            "range": "stddev: 0.000047964847583896186",
            "extra": "mean: 807.7967999994939 usec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_fbm_100k_6oct",
            "value": 240.27278457548644,
            "unit": "iter/sec",
            "range": "stddev: 0.000257459136285368",
            "extra": "mean: 4.161936200002003 msec\nrounds: 5"
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
          "id": "5089758fadf52880a77ea78d0b693a567f9945e5",
          "message": "docs(climatology,usage,design): 云场统计律 + 竞品云生成调研入库与用法登记\n\ncloud_field_statistics.md：单点光学厚度近似指数分布（Marchand 2010 全文核验）、\n空间谱一维 −5/3（Cahalan & Joseph 1989 经 Davis 1997 转引核验）、间歇性乘性级串\n（Lovejoy-Schertzer）与梯度联合指纹，及四条律到生成参数的映射表。\ncloud_generation_competitors.md：Guerrilla Decima（weather map 三通道契约、\n形状/侵蚀分离）、Frostbite、SatelliteCloudGenerator（locality 尺度多变）、\nGaia Sky（球面采样）、CloudNoiseGen、UE-ML 体积云，到本管线的取舍映射。\ncli.md 补 export clouds 用法段；roadmap 登记气象图层链 L2 原型完成；\nclimatology 索引与 competitor-analysis 速查行同步。\n\nCo-Authored-By: Claude Code <noreply@anthropic.com>",
          "timestamp": "2026-10-20T09:12:26+08:00",
          "tree_id": "8e16f785c731047cbad0036f9a4a9042cde63c67",
          "url": "https://github.com/fyabc/dreamulator/commit/5089758fadf52880a77ea78d0b693a567f9945e5"
        },
        "date": 1792458858979,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/micro/test_climate.py::test_climate_256",
            "value": 0.4521902216935473,
            "unit": "iter/sec",
            "range": "stddev: 0.11592463132167634",
            "extra": "mean: 2.2114587004 sec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_cvt_mesh.py::test_cvt_mesh_4096",
            "value": 3.719473728165913,
            "unit": "iter/sec",
            "range": "stddev: 0.012847884848107248",
            "extra": "mean: 268.8552394999988 msec\nrounds: 2"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_scalar_noise_50k",
            "value": 1.9421095870706824,
            "unit": "iter/sec",
            "range": "stddev: 0.821836996623093",
            "extra": "mean: 514.9040026666659 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_noise_100k",
            "value": 1172.6488566348305,
            "unit": "iter/sec",
            "range": "stddev: 0.00008425232985393759",
            "extra": "mean: 852.7701999980764 usec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_fbm_100k_6oct",
            "value": 242.0592815766853,
            "unit": "iter/sec",
            "range": "stddev: 0.0001293857226989099",
            "extra": "mean: 4.131219400001385 msec\nrounds: 5"
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
          "id": "2f38fe190453c14526b19ea95d1532951e85753b",
          "message": "chore(release): v1.1.0 发布准备——CHANGELOG 重排与版本号同步\n\nCHANGELOG 未发布区 64 条重排为 [1.1.0]：面向用户的新功能、行为变化\n（含区域包目录迁移方法、2D 地图 WebGL 2 要求）、修复列在前面；新增\n「数据与正典」小节（nacrea 轨道集合收尾与两档口径、earth plates.json\n修正、兼容性说明）与「已知问题」小节（板块速度两处写法不一致、第 51\n次旋回周期矛盾）；51 条地质时间轴等研究条目原文收进「内部与研究」。\n补写两个漏记条目：export clouds 程序化云纹理（51dc3ea）、轨道集合\n收尾（637bf2a）。\n\n版本号 1.0.1 → 1.1.0：pyproject.toml + uv.lock（已 uv sync\n--all-extras）、frontend/package.json + package-lock.json；roadmap\n头部「最后更新」与状态快照版本号同步。\n\nCo-Authored-By: Claude Code <noreply@anthropic.com>",
          "timestamp": "2026-10-20T11:13:46+08:00",
          "tree_id": "3f6b8dbf4df11431a47e71553ffd920157deb6fe",
          "url": "https://github.com/fyabc/dreamulator/commit/2f38fe190453c14526b19ea95d1532951e85753b"
        },
        "date": 1792468278366,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/micro/test_climate.py::test_climate_256",
            "value": 0.3154733102976315,
            "unit": "iter/sec",
            "range": "stddev: 0.14536063052633777",
            "extra": "mean: 3.1698402602000018 sec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_cvt_mesh.py::test_cvt_mesh_4096",
            "value": 3.0311990619312326,
            "unit": "iter/sec",
            "range": "stddev: 0.00828746966641766",
            "extra": "mean: 329.90245099999527 msec\nrounds: 2"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_scalar_noise_50k",
            "value": 1.436587029399248,
            "unit": "iter/sec",
            "range": "stddev: 1.1165603864267384",
            "extra": "mean: 696.094270333333 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_noise_100k",
            "value": 975.4150537388128,
            "unit": "iter/sec",
            "range": "stddev: 0.00006554585440920315",
            "extra": "mean: 1.0252045999976644 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_fbm_100k_6oct",
            "value": 192.28751690990933,
            "unit": "iter/sec",
            "range": "stddev: 0.00012913403173100716",
            "extra": "mean: 5.200545599996076 msec\nrounds: 5"
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
          "id": "d26230dea8c11839dc0d4a25585d68901df915f1",
          "message": "feat(export): 0e region_window 方位等距窗口（pack v4）+ 分支感知 refine + 湖泊冰情制图\n\n- region_export：窗口改局部方位等距（换算直用 td_canvas.CanvasGeometry 单源），\n  极区中心与跨 ±180° 窗口解锁，|lat|>75° 上限退休、只剩对跖点退化拒绝；\n  Clough-Tocher 与窗口取格改在 AEQ 平面 km 坐标（经度解缠整段删除）；\n  pack v4：新增 projection 字段、extent_km/km_per_px 精确均匀、pixel_box 退役\n- terrain_refine：conditioning 改 AEQ 采样（pitch 沿用旧导出网格纬向口径）；\n  修复 map_dir 写死根目录、忽略 source.branch 的隐藏 bug——此前 --branch 导出\n  的包细化时会悄悄读根世界引擎气候（TD 条件场与月径流形状），改走 MapManager\n  的 branch → root 解析\n- 新通道 lake_ice.months.npy（月均温 <0 的月数，class 最近邻）+ meta 图例；\n  ColorizeInputs 增 projection 与 lake_ice_months\n- carto/biome/relief：投影感知经纬网（两轴独立步长、经线向极收敛、纬线成弧、\n  标签落图框交点并回绕 ±180°）；carto 对 12 个月冰封湖按永久冰体惯例画淡冰色\n  + 图例「常年封冻湖」\n- packs QA API：按 meta.projection 分派 v4 AEQ / v3 等距圆柱逆算（旧包兼容）\n- cli_export：refine 示例路径改现行包位置、carto rich 标签转义修复\n- 文档：cli/terrain-chain/blender-render-pipeline/gaea-refinement 同步\n- 测试：窗口数学重写（真距/极区/反经线/对跖点）、pack v4 字段、冰封月通道正负断言\n\nCo-Authored-By: Claude Code <noreply@anthropic.com>",
          "timestamp": "2026-10-20T23:07:09+08:00",
          "tree_id": "b8c9690df62f67fa11e62513705cdea3f85c9b65",
          "url": "https://github.com/fyabc/dreamulator/commit/d26230dea8c11839dc0d4a25585d68901df915f1"
        },
        "date": 1792509388582,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/micro/test_climate.py::test_climate_256",
            "value": 0.3167201438916869,
            "unit": "iter/sec",
            "range": "stddev: 0.14903165317922382",
            "extra": "mean: 3.157361536000008 sec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_cvt_mesh.py::test_cvt_mesh_4096",
            "value": 3.167555087999809,
            "unit": "iter/sec",
            "range": "stddev: 0.019638928475129255",
            "extra": "mean: 315.70090249999794 msec\nrounds: 2"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_scalar_noise_50k",
            "value": 1.4693635546243184,
            "unit": "iter/sec",
            "range": "stddev: 1.088234791696884",
            "extra": "mean: 680.5667643333351 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_noise_100k",
            "value": 977.1266379596912,
            "unit": "iter/sec",
            "range": "stddev: 0.00006866439724298568",
            "extra": "mean: 1.0234087999975827 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_fbm_100k_6oct",
            "value": 197.40758827677465,
            "unit": "iter/sec",
            "range": "stddev: 0.00007331549786574537",
            "extra": "mean: 5.065661399996202 msec\nrounds: 5"
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
          "id": "12f264696c9f9f1aa19906945fc90d98422f6b70",
          "message": "Merge feature/s2-canvas-hydrology: S2 外存水文 + S3 画布裁窗 + CLI 收敛\n\n- S2：分块 Priority-Flood 三段式（Barnes 2016）、eps 坡道、Fill-Spill-Merge\n  湖级联、Barnes 2017 分块汇流、磁盘管线与矢量河段提取\n- S3：AEQ 画布裁窗写出既有 pack 词汇，海深/湖面/河段与渲染链对齐\n- 渲染：河湖裁剪改为只删除完全在水中的河段；湖体按完整填平足迹断链绘制\n- CLI：export 收敛为六命令（layers/region/build/render/clouds/canvas），\n  画布河网阈值默认 27000（与区域链同物理起点）\n- 文档与测试同步（沙盒 oracle 对拍、画布链测试、湖足迹单测）",
          "timestamp": "2026-10-21T03:07:11+08:00",
          "tree_id": "9a67bf2f3b3ff7e4521fd4673a54d27b8444e455",
          "url": "https://github.com/fyabc/dreamulator/commit/12f264696c9f9f1aa19906945fc90d98422f6b70"
        },
        "date": 1792523311156,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/micro/test_climate.py::test_climate_256",
            "value": 0.30967344090062754,
            "unit": "iter/sec",
            "range": "stddev: 0.14099538147828064",
            "extra": "mean: 3.2292081525999974 sec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_cvt_mesh.py::test_cvt_mesh_4096",
            "value": 2.78957304571921,
            "unit": "iter/sec",
            "range": "stddev: 0.023887485524691564",
            "extra": "mean: 358.47779699999904 msec\nrounds: 2"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_scalar_noise_50k",
            "value": 1.3598057253900306,
            "unit": "iter/sec",
            "range": "stddev: 1.182226693352025",
            "extra": "mean: 735.3991686666651 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_noise_100k",
            "value": 900.8070871204721,
            "unit": "iter/sec",
            "range": "stddev: 0.00021481066683680188",
            "extra": "mean: 1.110115599996675 msec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_fbm_100k_6oct",
            "value": 192.4531276558175,
            "unit": "iter/sec",
            "range": "stddev: 0.00006316016484580995",
            "extra": "mean: 5.196070400000963 msec\nrounds: 5"
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
          "id": "bb05849d5f67f389fcf5271e1adb7359291650e5",
          "message": "Merge docs/canvas-hydrology: 画布链技术参考 + td_canvas 正式入库\n\n- 新增 docs/design/pipelines/canvas-hydrology.md（画布契约、外存水文、\n  裁窗与渲染衔接、验证与限制），CLI 用法页与设计索引同步\n- td_canvas 几何换算模块入库，修复干净克隆下 region_export 导入失败\n  导致的 tests workflow 红灯",
          "timestamp": "2026-10-21T03:18:00+08:00",
          "tree_id": "6a5806d1e96e610d7c204afc0e33212356438fc9",
          "url": "https://github.com/fyabc/dreamulator/commit/bb05849d5f67f389fcf5271e1adb7359291650e5"
        },
        "date": 1792523938022,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/micro/test_climate.py::test_climate_256",
            "value": 0.46700842002862225,
            "unit": "iter/sec",
            "range": "stddev: 0.10542387457224148",
            "extra": "mean: 2.1412890156000004 sec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_cvt_mesh.py::test_cvt_mesh_4096",
            "value": 3.7806392789571173,
            "unit": "iter/sec",
            "range": "stddev: 0.00900472342990807",
            "extra": "mean: 264.5055309999975 msec\nrounds: 2"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_scalar_noise_50k",
            "value": 1.9356165118989967,
            "unit": "iter/sec",
            "range": "stddev: 0.8255416096685161",
            "extra": "mean: 516.6312613333304 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_noise_100k",
            "value": 1201.307695500609,
            "unit": "iter/sec",
            "range": "stddev: 0.00007330882624680758",
            "extra": "mean: 832.4262000030558 usec\nrounds: 5"
          },
          {
            "name": "benchmarks/micro/test_noise.py::test_kernel_fbm_100k_6oct",
            "value": 247.7482164605715,
            "unit": "iter/sec",
            "range": "stddev: 0.00004105612778241318",
            "extra": "mean: 4.036356000000296 msec\nrounds: 5"
          }
        ]
      }
    ]
  }
}