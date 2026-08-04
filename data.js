window.BENCHMARK_DATA = {
  "lastUpdate": 1785851937267,
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
      }
    ]
  }
}