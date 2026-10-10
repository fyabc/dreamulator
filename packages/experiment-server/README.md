# experiment-server

独立、可入库的Python实验工具包。统一 `server` 或 `python -m experiment_server` Typer入口，Windows与Linux共用初态、数值模型、状态保存、后台管理、恢复和绘图代码。导入包不启动实验；不依赖Dreamulator worldbuilder路径，不修改正式世界YAML。

## 安装与帮助

```text
uv venv --python 3.12 .venv-experiments
uv pip install --python .venv-experiments/bin/python -e /path/to/experiment-server
.venv-experiments/bin/python -m experiment_server --help
```

Windows将Python路径改为 `.venv-experiments/Scripts/python.exe`。也可安装wheel后直接 `server --help`。固定数值依赖见pyproject.toml；Typer中文帮助明确每个选项。不要在正在运行的旧服务器共享虚拟环境中升级依赖，用新环境部署此包。

## 同一套Windows/Linux命令

```text
server init --work-dir /persistent/experiments --max-active 12
server register --work-dir /persistent/experiments --name trial --config /path/to/config.json
server start --work-dir /persistent/experiments --name trial --until 500000
server status --work-dir /persistent/experiments
server stop --work-dir /persistent/experiments --name trial
server check-checkpoint --work-dir /persistent/experiments --name trial
server plot --work-dir /persistent/experiments --last-years 0
```

Windows的work-dir可为 `D:/Data/experiments`。后台启动隐藏窗口，Linux脱离SSH session；worker登记实际PID／启动时刻／唯一token，Windowsvenv启动器不冒充积分PID。停止写入针对准确worker token的请求文件，worker在下一个输出点保存并退出；status确认实际结束。原生LinuxSIGTERM／Ctrl+C仍可保存。异常锁不自动删除，不按超时推定实验终止。

`run`用于前台／调度器单组；`start --name a --name b`显式批量启动，容量检查先于launch。并发上限 `capacity --max-active N`，注册数量不限、不会自动启动列表全体；每组主要一个CPU核、数学库线程1。Windows暂不强制processor-group affinity，交由OS调度；Linux优先使用不同可用逻辑核。额度较大不表示单条BS多线程加速。

`start --resume`仅明确恢复未闭合保存，完成／采样失败／资源裁剪不能重启或延长。保存检查点不会反复重启积分。旧Nacrea shell启动的活动worker不是本包worker，不直接接管其PID；它们跑完或明确停机后，可以 `import-state` 将已提交portable-state.json以新实验名导入，保留原epoch／粒子／16state，不能把t改0伪装新初态。

## 通用初始配置

外部JSON指定 `schema_version`、`model`、`units`、`body_names`、`initial_state`、`diagnostics`、`integration`和`provenance`。没有隐式Nacrea preset或随机seed；所有粒子x/y/z/vx/vy/vz/m/r与实际历元必须明确。body_names和指定pair决定动态绘图面板。

- `point_mass`：任意数量（至少2）的正质量粒子，保守N体／BS模型。示例 `experiment_server/examples/two-body.json`。不接受潮汐参数后静默忽略。
- `coupled_ctl`：保留已核验的pairedCTL／J2-spin后端。结构为索引0恒星、1自转母星、2/3/4三颗自转卫星，四spin＋四累计heat共16维；可有其它保守外行星。body名称可变，但结构不是任意数目的自转天体。保留REBOUND5.1.1 ABI断言；不支持未验证的额外形状或多源潮汐。

示例 `nacrea-zero.json`是原0年低Vigil e初态；`nacrea-blue-100k.json`是当前选择蓝线的真实成熟100k原始状态。二者不是同一物理干预历史。通用包可接收其它合法同模型配置，不重新拟合ψ、季节或周期。

CTL完整settings包含radii_au／k2／k2tau_yr／inertias／j2_array；配置半径与粒子半径必须一致。`integration`指定eps_rel、eps_abs、interval_yr、checkpoint_yr，保存间隔是输出间隔整数倍，不是BS内部积分步长。严格拒绝未知模型／关键字段、无效索引、NaN、负质量／非法结构。

## 新实验与复现

```text
server variant -w /persistent/experiments --from-name base --name CTL045 --lag .45
server variant -w /persistent/experiments --from-name base --name phase01 --phase-deg .1 --body satellite_vigil
```

`lag`相对显式 `provenance.reference_k2tau_yr`，不是反复乘已有倍率。相位变更记录能量／角动量变化，保留质量和16state；参数与相位对照分开，不随机抽很多seed直到凉。同参数同初态复算通常应重复，差异需先查平台／版本／缓存／恢复史，不能从两个不同历史断言唯一数值混沌。

注册／verify仅做丢弃的.004yr回调与新Simulation恢复校验，不启动生产长积分。工作目录只存inputs、experiments.json、runs、plots、cache；代码包不带PID／长轨迹。每个不可变checkpoint含state.json、particles.bin、samples.json.gz、receipt.json，最后原子切status；检查点SHA、粒子全字段、JSON/BINepoch和外部ODE均核验。

绘图默认全部实际保存历史，`--last-years 20000`看滑窗，`--name`重复选组，`--active-only`只画saved status为running的组。动态显示天体a/e/i／spin／season／heat、配置指定pair的实际最小距离及同样本速度、径向壳和守恒误差。500yr统计与20/100/500yr热均线，缺段断线，不造未来。优先系统Noto等CJK字体，缺中文字体回退英文，无字体下载。

## 物理边界与维护

内部耗散不直接等火山、气候／生态事件；2yr距离不证连续安全，径向壳负不等碰撞。CTL无温度—黏度—J2反馈，有限轨迹不认证永久材料形状或Myr/Gyr。同名蓝线保持500k证据只是当前叙事基线，服务器未来替换需另做同窗比较。

测试：`python -m pytest tests -q`，覆盖通用两体、CTL精确粒子／16state、短积分commit/恢复、SHA篡改拒绝、容量预检、Typer帮助、真实Windows/Linux后台握手／停止／检查点。数值核仅把局部imports改为包内relative imports；不复用旧路径绑定的run.py／stage500窗口监控。

建议入库落点 `packages/experiment-server`，作为可选研究包，不添加为worldbuilder默认依赖。先审查source ZIP／wheel验证、同配置跨平台数值差异，再在具备push的环境提交。当前版本只准备private交接，未commit／push。
