# 查询构建进度

API 模式可以先发起后台构建，再查询各引擎的执行状态。前端使用 `api.startBuildJob`
传入世界名和构建选项，并保存返回的任务 ID；随后使用 `api.getBuildJob` 查询同一任务。
静态站只浏览已经发布的结果，不提供构建或进度查询。

## 发起与查询

以下请求在 `sample` 世界的 `climate-dev` 分支上重算气候。构建选项与同步接口一致：
`engine` 选择目标引擎，`branch` 选择分支，`force` 要求重新计算目标。省略选项时使用
世界根目录的完整管线及正常缓存规则。真实地球等参照世界的根目录为只读，必须选择分支。

```http
POST /api/worlds/sample/build-jobs
Content-Type: application/json

{"engine": "climate", "branch": "climate-dev", "force": true}
```

服务返回 HTTP 202 和任务快照。响应中的 `id` 是后续查询所用的任务 ID，初始 `state`
为 `queued`，表示请求已接收，后台函数即将执行。这一状态不代表有多个重算任务排队。

```http
GET /api/worlds/sample/build-jobs/{id}
```

前端可以每秒查询一次。运行期间，`state` 为 `running`，`current_engine` 标明当前引擎，
`elapsed_seconds` 给出开始执行以来的秒数。`updated_at` 记录最近一次阶段变化的 UTC 时间，
不是定时心跳。地质等引擎内部可以长时间处于同一阶段，前端应继续显示已耗时。

## 理解阶段与结果

任务的 `stages` 列出本次构建实际选中的引擎。阶段状态含义如下。

| 状态 | 含义 |
|------|------|
| `pending` | 这个引擎已经选中，还没有开始检查输入。 |
| `validating` | 引擎正在检查缓存和输入。 |
| `running` | 引擎正在计算。 |
| `succeeded` | 引擎已经完成计算并成功返回。 |
| `skipped` | 已有输出仍然有效，本次直接使用缓存。 |
| `failed` | 引擎执行或输入检查失败，具体原因在该阶段的 `errors` 中。 |
| `not_run` | 构建提前结束，这个引擎没有执行。 |

分支可能需要先补齐继承的天文数据。这项准备工作也作为真实阶段显示，阶段的
`bootstrap` 为 `true`，与正式分支计算分开计数。它沿用已有的上游准备规则。

构建结束时，任务状态为 `succeeded` 或 `failed`，`finished_at` 给出结束时间。
`result` 提供执行数量与错误汇总，其口径与同步构建一致：缓存跳过的阶段和上游准备
不计入 `engines_run`。运行异常另在任务的 `error` 中说明，已完成的阶段仍然可查。
所有阶段跳过缓存也算成功完成。

## 服务范围与重试

一个 API 服务进程同时只执行一项构建。同一世界的重复点击，以及其他世界在此期间
发起的构建，都会返回 HTTP 409；同步 `POST /build` 使用同一运行锁。任务结束后可以
重新发起请求，服务不会自动重跑失败任务。

未知世界、分支或任务返回 HTTP 404。不存在的目标引擎或无效分支名返回 HTTP 422。
服务保留最近 100 个任务，任务状态存储在服务进程内。重启或开发模式热重载后，旧 ID
返回 HTTP 404；前端应说明该次状态已不可查询，再让用户检查结果和决定是否重算。
需要跨服务进程排队、断点恢复或长期任务存档时，另行设计持久化任务系统。

本文对应 [后台任务实现](../../src/dreamulator/build_jobs.py)和
[API 路由](../../src/dreamulator/api_routes/worlds.py)。后台执行采用
[FastAPI 的 BackgroundTasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)。
