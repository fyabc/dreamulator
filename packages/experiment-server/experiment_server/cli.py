"""Typer public server commands; full configuration is explicit and input-driven."""
from pathlib import Path
from typing import Annotated
import copy,json
import typer
from .storage import init,locked,registry,atomic,read
from .config import read_config,import_portable
from . import __version__

app=typer.Typer(no_args_is_help=True,help='通用轨道实验服务器：显式初态、模型、工作目录、恢复和绘图。',pretty_exceptions_enable=False)
Work=Annotated[Path,typer.Option('--work-dir','-w',help='独立数据目录，代码与PID／结果分离。')]


def execute(fn,*args,**kwargs):
    try:return fn(*args,**kwargs)
    except (ValueError,FileNotFoundError,FileExistsError,KeyError,AssertionError,BlockingIOError) as e:
        typer.secho(f'错误：{e}',fg=typer.colors.RED,err=True);raise typer.Exit(1)


def output(data):typer.echo(json.dumps(data,ensure_ascii=False,indent=2))


@app.command('init')
def initialize(work_dir:Work,max_active:Annotated[int,typer.Option(help='并发上限，可按服务器资源调整。',min=1)]=8):
    """初始化空工作目录；不创建实验，不启动积分。"""
    execute(init,work_dir.resolve(),max_active);output({'work_dir':str(work_dir.resolve()),'max_active':max_active})


@app.command()
def register(work_dir:Work,name:Annotated[str,typer.Option(help='新实验唯一名称。')],config:Annotated[Path,typer.Option(exists=True,dir_okay=False,help='schema v1完整JSON初态配置。')]):
    """核验任意输入配置并注册到列表；不启动生产积分。"""
    from .manager import register as reg
    output(execute(reg,work_dir.resolve(),name,execute(read_config,config),config))


@app.command('import-state')
def import_state(work_dir:Work,name:Annotated[str,typer.Option()],state:Annotated[Path,typer.Option(exists=True,dir_okay=False,help='旧便携粒子／settings／16state JSON，保留实际历元。')]):
    """导入已有CTL便携状态为通用配置；不改历元、不丢失spinheat。"""
    from .manager import register as reg
    output(execute(reg,work_dir.resolve(),name,execute(import_portable,read(state)),state))


@app.command()
def variant(work_dir:Work,name:Annotated[str,typer.Option(help='新实验名。')],from_name:Annotated[str,typer.Option('--from-name',help='已注册实验的原始完整初态。')],lag:Annotated[float|None,typer.Option(help='相对参考k2tau的物理倍率；省略保持原参数。')]=None,phase_deg:Annotated[float,typer.Option(help='只改指定粒子的平均近点角，保留轨道形状及16state。')]=0.,body:Annotated[str|None,typer.Option(help='相位变化的body_name；必须显式指定。')]=None):
    """只改变声明的CTL／初相位，以新名字注册；不是随机抽种子。"""
    from .variants import derive
    output(execute(derive,work_dir.resolve(),name,from_name,lag,phase_deg,body))


@app.command()
def kick(work_dir:Work,name:Annotated[str,typer.Option(help='新实验名。')],from_name:Annotated[str,typer.Option('--from-name',help='已注册实验的原始完整初态。')],body:Annotated[str,typer.Option(help='受扰动天体的body_name。')],dv_m_s:Annotated[float,typer.Option('--dv-m-s',help='初态瞬时速度变化（m/s），可为负。')],direction:Annotated[str,typer.Option(help='相对母体的轨道系方向：tangential / radial / normal。')]='tangential'):
    """对指定天体在初态施加瞬时速度扰动（模拟撞击），以新名字注册；不改质量、位置与16state。"""
    from .variants import kick as _kick
    output(execute(_kick,work_dir.resolve(),name,from_name,body,dv_m_s,direction))


@app.command()
def capacity(work_dir:Work,max_active:Annotated[int,typer.Option(min=1)]):
    """修改并发上限，不停止或启动已有实验。"""
    with locked(work_dir.resolve()):
        r=execute(registry,work_dir.resolve());r['max_active']=max_active;atomic(work_dir.resolve()/'experiments.json',r)
    output({'max_active':max_active})


@app.command()
def status(work_dir:Work):
    """查看统一实验列表、保存历元和实际进程身份。"""
    from .manager import status as stat
    output(execute(stat,work_dir.resolve()))


@app.command()
def start(work_dir:Work,name:Annotated[list[str],typer.Option(help='显式选实验，可重复--name；不自动启动列表全部实验。')],until:Annotated[float,typer.Option(help='绝对目标年，非增量时长。')],resume:Annotated[bool,typer.Option(help='明确恢复未闭合保存；完成／失败／裁剪禁止恢复。')]=False):
    """Windows/Linux后台启动明确选定实验，按并发容量和保存状态检查。"""
    from .manager import start as launch
    output(execute(launch,work_dir.resolve(),name,until,resume))


@app.command('run')
def foreground(work_dir:Work,name:Annotated[str,typer.Option()],until:Annotated[float,typer.Option(help='绝对目标年。')],resume:bool=False):
    """前台运行单个实验，适合本机验证／调度器；后台仍用start。"""
    from .worker import run
    from .manager import get_case
    execute(get_case,work_dir.resolve(),name);execute(run,work_dir.resolve(),name,until,resume)


@app.command()
def stop(work_dir:Work,name:Annotated[str,typer.Option()]):
    """Windows/Linux请求准确worker在下一输出点保存并退出。"""
    from .manager import stop as halt
    output(execute(halt,work_dir.resolve(),name))


@app.command()
def verify(work_dir:Work,name:Annotated[str,typer.Option()]):
    """本平台短回调／新Simulation恢复核验；不认证长期稳定。"""
    from .manager import verify as check
    output(execute(check,work_dir.resolve(),name))


@app.command('check-checkpoint')
def check_checkpoint(work_dir:Work,name:Annotated[str,typer.Option()]):
    """核验最新检查点SHA、JSON/BIN历元及新Simulation状态。"""
    from .recovery import check
    output(execute(check,work_dir.resolve(),name))


@app.command()
def plot(work_dir:Work,name:Annotated[list[str]|None,typer.Option(help='可重复选实验；省略画列表内全部已保存数据。')]=None,last_years:Annotated[float,typer.Option(help='最近时间窗口；0表示全部实际保存历史。')]=0.,active_only:Annotated[bool,typer.Option(help='仅画saved status为running的实验。')]=False,font:Annotated[Path|None,typer.Option(help='可选已安装的本地中文字体文件，不下载。')]=None):
    """按配置的body_names和指定pair绘完整系统面板与图源JSON。"""
    from .plotting import render
    output(execute(render,work_dir.resolve(),name,last_years,active_only,font))


@app.command('version')
def version():typer.echo(__version__)


@app.command()
def spectra(work_dir:Work,name:Annotated[str,typer.Option()],body:Annotated[str,typer.Option(help='配置中的body_name。')],metric:Annotated[str,typer.Option(help='body字段；heat_flux表示累计热差分。')]='stellar_season_deg'):
    """保存序列有限频谱；拒绝缺段，不认证精确周期或长期安全。"""
    from .spectra import analyze
    output(execute(analyze,work_dir.resolve(),name,body,metric))
