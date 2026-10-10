"""Registry, verified inputs and native Linux background workers; never autorefills."""
import copy
import math
import os
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
import numpy as np
from .config import validate,read_config
from .models import restore,state_of,budget
from .storage import atomic,read,registry,within,sha,locked,valid_name
from .processes import identity as native_identity,matches


def identity(pid):
    return native_identity(pid)


def alive(handle,root):
    if handle.get('pending'):
        actual=identity(handle['pid'])
        return bool(actual and actual['state']!='Z' and actual['start_ticks']==handle['start_ticks'])
    actual=identity(handle['pid'])
    if handle.get('token'):return matches(actual,handle,root)
    return bool(actual and actual['state']!='Z' and actual['start_ticks']==handle['start_ticks']
                and b'experiment_server.worker' in actual['cmdline'] and str(root).encode() in actual['cmdline']
                and handle['name'].encode() in actual['cmdline'])


def native_check(config):
    sim,c,refs=restore(config);start=sim.t;e0,_=budget(sim,c,refs)
    sim.integrate(start+.002);changed=copy.deepcopy(c);changed['initial_state']=state_of(sim,c,refs)
    other,cc,rr=restore(changed);sim.integrate(start+.004);other.integrate(start+.004)
    pos=max(np.linalg.norm(np.asarray(p.xyz)-q.xyz)/max(np.linalg.norm(p.xyz),1e-12) for p,q in zip(sim.particles,other.particles))
    vel=max(np.linalg.norm(np.asarray(p.vxyz)-q.vxyz)/max(np.linalg.norm(p.vxyz),1e-12) for p,q in zip(sim.particles,other.particles))
    spin=max((abs(refs[0].y[i]-rr[0].y[i]) for i in range(16)),default=0) if refs else 0
    err=abs((budget(sim,c,refs)[0]-e0)/max(abs(e0),1e-30))
    if pos>=1e-7 or vel>=1e-7 or spin>=.01 or err>=1e-7:raise ValueError('短时恢复／能量校验失败，不注册。')
    return {'os':sys.platform,'rebound':__import__('rebound').__version__,'shortcheck_only_end_yr':start+.004,
            'relative_position_error':float(pos),'relative_velocity_error':float(vel),'spin_error':float(spin),'energy_error':float(err)}


def register(root,name,config,source=None):
    valid_name(name);config=validate(config)
    with locked(root):
        r=registry(root);dest=root/'inputs'/name
        if any(c['name']==name for c in r['cases']) or dest.exists() or (root/'runs'/name).exists():raise ValueError('实验名称已存在。')
        proof=native_check(config)
        dest.mkdir(parents=True);p=dest/'config.json';atomic(p,config)
        receipt={'name':name,'config_sha256':sha(p),'source_file':str(source) if source else None,
                 'source_file_sha256':sha(source) if source else None,'native_check':proof,'started':False}
        atomic(dest/'verification.json',receipt)
        r['cases'].append({'name':name,'config':p.relative_to(root).as_posix(),'config_sha256':sha(p),'model':config['model'],
                           'epoch_yr':config['initial_state']['epoch_yr'],'native_check':proof})
        atomic(root/'experiments.json',r)
    return receipt


def get_case(root,name):
    r=registry(root);c=next((c for c in r['cases'] if c['name']==name),None)
    if c is None:raise ValueError('未知实验名称。')
    p=within(root,c['config'])
    if sha(p)!=c['config_sha256']:raise ValueError('初始配置已更改；请用新名称注册。')
    return c,read_config(p)


def status(root):
    r=registry(root);result=[]
    for c in r['cases']:
        run=root/'runs'/c['name'];hp=run/'handle.json';sp=run/'status.json';h=read(hp) if hp.exists() else None
        result.append({'name':c['name'],'model':c['model'],'alive':alive(h,root) if h else False,
                       'saved':read(sp) if sp.exists() else None,'state':'registered' if not sp.exists() else read(sp)['status']})
    return {'max_active':r['max_active'],'cases':result}


def start(root,names,until,resume=False):
    if not math.isfinite(until) or until<=0:raise ValueError('须指定正的绝对目标年。')
    if not names:raise ValueError('显式指定至少一个--name，避免意外批量启动。')
    with locked(root):
        r=registry(root);handles=[read(p) for p in (root/'runs').glob('*/handle.json')]
        live={h['name']:h for h in handles if alive(h,root)};pending=[]
        for name in dict.fromkeys(names):
            c,config=get_case(root,name);run=root/'runs'/name;sp=run/'status.json'
            if name in live:continue
            s=read(sp) if sp.exists() else None
            if (run/'worker.lock').exists():raise ValueError('worker.lock存在；先核PID与保存记录，不自动清锁。')
            if s and s['status'] in ['completed','orbital_failed','stopped_by_user_authorized_resource_pruning']:raise ValueError('闭合实验不能重启或延长。')
            if bool(s)!=resume:raise ValueError('已有保存需--resume；新实验不可用--resume。')
            if until <= (s['epoch_yr'] if s else c['epoch_yr']):raise ValueError('目标须大于恢复／初始历元。')
            if c['native_check']['os']!=sys.platform:raise ValueError('请在运行平台用verify重新校验此输入。')
            pending.append((c,config))
        if len(live)+len(pending)>r['max_active']:raise ValueError('超过已配置并发容量，本批次未启动。')
        cores=sorted(os.sched_getaffinity(0)) if hasattr(os,'sched_getaffinity') else list(range(os.cpu_count() or 1));used={i for h in live.values() for i in h.get('cpu_affinity',[])};started=[]
        for c,config in pending:
            name=c['name'];run=root/'runs'/name;run.mkdir(parents=True,exist_ok=True)
            token=uuid.uuid4().hex
            cmd=[sys.executable,'-u','-m','experiment_server.worker',str(root),name,str(until),token]+(['resume'] if resume else [])
            env=os.environ.copy();env['PYTHONPATH']=str(Path(__file__).resolve().parents[1])+os.pathsep+env.get('PYTHONPATH','')
            env['PYTHONUTF8']='1';env['NUMBA_CACHE_DIR']=str(root/'.cache/numba');env['MPLCONFIGDIR']=str(root/'.cache/matplotlib')
            for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMBA_NUM_THREADS','NUMEXPR_NUM_THREADS']:env[k]='1'
            core=next((i for i in cores if i not in used),cores[len(started)%len(cores)]);used.add(core)
            original=os.sched_getaffinity(0) if hasattr(os,'sched_getaffinity') else None
            if original is not None:os.sched_setaffinity(0,{core})
            try:
                kwargs={'creationflags':subprocess.CREATE_NO_WINDOW|subprocess.DETACHED_PROCESS} if sys.platform=='win32' else {'start_new_session':True}
                with (run/'run.log').open('ab') as log:proc=subprocess.Popen(cmd,cwd=root,stdout=log,stderr=subprocess.STDOUT,env=env,**kwargs)
            finally:
                if original is not None:os.sched_setaffinity(0,original)
            actual=identity(proc.pid)
            if actual is None:raise ValueError('worker在启动时退出，请查run.log；不自动重试。')
            h={'name':name,'pid':proc.pid,'start_ticks':actual['start_ticks'],'command':cmd,'cpu_affinity':[core] if original is not None else [],'absolute_target_yr':until,'token':token,'pending':True}
            # Workerhandshake uses actualPythonPID even when Windowsvenv uses a launcher shim.
            ready=run/('worker-ready-'+token+'.json')
            deadline=time.monotonic()+10
            while not ready.exists() and time.monotonic()<deadline:time.sleep(.1)
            if ready.exists():h=read(ready);h.update(command=cmd,cpu_affinity=h.get('cpu_affinity',[]),absolute_target_yr=until)
            atomic(run/'handle.json',h);started.append(h)
        return started


def stop(root,name):
    with locked(root):
        get_case(root,name);p=root/'runs'/name/'handle.json'
        if not p.exists():raise ValueError('没有已登记worker，不发送信号。')
        h=read(p)
        if not alive(h,root):raise ValueError('PID／启动时刻／命令不匹配，不发送信号。')
        if h.get('pending'):raise ValueError('worker尚未登记实际PID；稍后status核对，不提前停止启动器。')
        atomic(root/'runs'/name/'stop-request.json',{'name':name,'token':h['token'],'pid':h['pid'],'start_ticks':h['start_ticks']})
    return {'name':name,'request':'stop-file','pid':h['pid'],'note':'下一输出点保存并退出；随后status确认实际结束。'}


def verify(root,name):
    with locked(root):
        r=registry(root);c,config=get_case(root,name);proof=native_check(config)
        next(x for x in r['cases'] if x['name']==name)['native_check']=proof;atomic(root/'experiments.json',r)
        return proof
