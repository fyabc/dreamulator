"""Continuous integration, immutable commits and explicit process signal handling."""
import os
for key in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMBA_NUM_THREADS','NUMEXPR_NUM_THREADS']:os.environ[key]='1'
import gzip
import hashlib
import json
import platform
import signal
import sys
import warnings
import time
from datetime import datetime,timezone
from pathlib import Path
import rebound
from .storage import atomic,read,registry,within,sha
from .models import restore,state_of,budget,sample


def utc():return datetime.now(timezone.utc).isoformat()


def code_identity():
    root=Path(__file__).parent;h=hashlib.sha256()
    for p in sorted(root.rglob('*.py')):h.update(p.relative_to(root).as_posix().encode());h.update(p.read_bytes())
    return h.hexdigest()


def commit(run,sim,config,refs,rows,status,meta,reasons):
    name='checkpoint-'+format(float(sim.t),'.9f').rstrip('0').rstrip('.')
    temp=run/(name+'.writing');final=run/name
    if final.exists():raise FileExistsError('该历元检查点已提交，禁止覆盖。')
    temp.mkdir()
    state=state_of(sim,config,refs);atomic(temp/'state.json',state)
    sim.save_to_file(str(temp/'particles.bin'),delete_file=True)
    with gzip.open(temp/'samples.json.gz','wt',encoding='utf-8') as f:json.dump({'samples':rows},f,ensure_ascii=False,allow_nan=False)
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore',message='You have to reset function pointers.*',category=RuntimeWarning)
        loaded=rebound.Simulation(str(temp/'particles.bin'))
    assert loaded.t==sim.t and loaded.N==sim.N
    from .config import PARTICLE_KEYS
    assert [{k:float(getattr(p,k)) for k in PARTICLE_KEYS} for p in loaded.particles]==state['particles']
    if refs:assert state['spin_state16']==rows[-1]['spin_state16']
    receipt={'epoch_yr':float(sim.t),'status':status,'sample_begin_yr':rows[0]['time_yr'],'sample_count':len(rows),
             'files':{p.name:{'sha256':sha(p),'bytes':p.stat().st_size} for p in temp.iterdir()},
             'run':meta,'reasons':reasons,'committed_utc':utc(),'native_BIN_particles_epoch_verified':True}
    atomic(temp/'receipt.json',receipt);temp.rename(final)
    atomic(run/'status.json',{'epoch_yr':float(sim.t),'status':status,'checkpoint':name,'run':meta,'reasons':reasons,'committed_utc':receipt['committed_utc']})
    print(json.dumps({'epoch_yr':sim.t,'status':status,'checkpoint':name}),flush=True)


def verified_checkpoint(run,state):
    block=within(run,state['checkpoint']);receipt=read(block/'receipt.json')
    for name,item in receipt['files'].items():
        if sha(within(block,name))!=item['sha256']:raise ValueError('检查点SHA不匹配。')
    portable=read(block/'state.json')
    if portable['epoch_yr']!=state['epoch_yr'] or portable['epoch_yr']!=receipt['epoch_yr']:raise ValueError('检查点历元不匹配。')
    return block,portable


def run(root,name,until,resume=False,token=None):
    import math
    if not math.isfinite(until) or until<=0:raise ValueError('目标须为正的有限绝对年。')
    r=registry(root);case=next(c for c in r['cases'] if c['name']==name);config_path=within(root,case['config'])
    if sha(config_path)!=case['config_sha256']:raise ValueError('初始配置SHA已改变。')
    config=read(config_path);runpath=root/'runs'/name;runpath.mkdir(parents=True,exist_ok=True)
    lock=runpath/'worker.lock';fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.write(fd,str(os.getpid()).encode());os.close(fd)
    try:
        if resume:
            status=read(runpath/'status.json')
            if status['status'] not in ['stopped_explicitly','running']:raise ValueError('完成／失败／裁剪组不可恢复。')
            _,state=verified_checkpoint(runpath,status);config['initial_state']=state
        elif (runpath/'status.json').exists():raise ValueError('已有实验不能用新启动覆盖。')
        sim,config,refs=restore(config)
        if until<=sim.t:raise ValueError('目标须为大于初态历元的绝对年。')
        meta={'name':name,'pid':os.getpid(),'started_utc':utc(),'start_epoch_yr':float(sim.t),'absolute_target_yr':until,
              'config_sha256':case['config_sha256'],'python':sys.version,'rebound':rebound.__version__,'platform':platform.platform(),
              'implementation_sha256':code_identity(),'explicit_resume':resume,'integration':config['integration']}
        stop=[False]
        for sig in [signal.SIGTERM,signal.SIGINT]:signal.signal(sig,lambda *args:stop.__setitem__(0,True))
        initial=budget(sim,config,refs);row,reasons=sample(sim,config,refs,initial);rows=[row]
        if reasons:commit(runpath,sim,config,refs,rows,'orbital_failed',meta,reasons);return
        if not resume:commit(runpath,sim,config,refs,rows,'running',meta,[])
        else:
            status.update(status='running',run=meta);atomic(runpath/'status.json',status)
        interval=config['integration']['interval_yr'];next_save=sim.t+config['integration']['checkpoint_yr']
        while True:
            request=runpath/'stop-request.json'
            if request.exists():
                message=read(request)
                if message.get('token')==token and message.get('pid')==os.getpid():stop[0]=True
            if stop[0]:
                if len(rows)>1:commit(runpath,sim,config,refs,rows,'stopped_explicitly',meta,[])
                else:
                    status=read(runpath/'status.json');status['status']='stopped_explicitly';atomic(runpath/'status.json',status)
                return
            target=min(until,sim.t+interval)
            if math.isclose(target,until,rel_tol=0,abs_tol=1e-10):target=until
            sim.integrate(target);row,reasons=sample(sim,config,refs,initial);rows.append(row)
            status='orbital_failed' if reasons else 'completed' if target==until else 'running'
            if sim.t>=next_save-1e-10 or status!='running':
                commit(runpath,sim,config,refs,rows,status,meta,reasons)
                if status!='running':return
                rows=[row];next_save+=config['integration']['checkpoint_yr']
    finally:lock.unlink(missing_ok=True)


def main():
    # Internal worker protocol only; public help is entirely Typer.
    root=Path(sys.argv[1]).resolve();name=sys.argv[2];until=float(sys.argv[3]);token=sys.argv[4];resume=len(sys.argv)>5 and sys.argv[5]=='resume'
    from .processes import identity
    actual=identity(os.getpid())
    h={'name':name,'pid':os.getpid(),'start_ticks':actual['start_ticks'],'token':token,'pending':False,
       'cpu_affinity':sorted(os.sched_getaffinity(0)) if hasattr(os,'sched_getaffinity') else []}
    runpath=root/'runs'/name;atomic(runpath/('worker-ready-'+token+'.json'),h)
    # Parent publishes command metadata; if startup exceeded its bounded wait, worker updatespending handle.
    hp=runpath/'handle.json'
    deadline=time.monotonic()+15
    while not hp.exists() and time.monotonic()<deadline:time.sleep(.1)
    if hp.exists():
        old=read(hp)
        if old.get('token')==token:
            old.update(h);atomic(hp,old)
    run(root,name,until,resume,token)


if __name__=='__main__':main()
