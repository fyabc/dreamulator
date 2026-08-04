window.BENCHMARK_DATA = {
  "lastUpdate": 1785801840239,
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
      }
    ]
  }
}