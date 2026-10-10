"""Meaningful portable recovery, generic input and manager boundary tests."""
import copy,json,sys,time,subprocess,types
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pytest
from typer.testing import CliRunner
from experiment_server.cli import app
from experiment_server.config import validate,read_config
from experiment_server.storage import init,read,atomic,sha
from experiment_server.manager import register,start,identity,alive,get_case
from experiment_server.worker import run
from experiment_server.recovery import check
from experiment_server.models import restore,state_of,sample,budget

PACKAGE=Path(__file__).parents[1]/'experiment_server'


def test_generic_input_roundtrip_commit_and_hash(tmp_path):
    root=tmp_path/'work';init(root,12);c=read_config(PACKAGE/'examples/two-body.json')
    register(root,'two',c);assert not (root/'runs').exists()
    run(root,'two',.2)
    proof=check(root,'two');assert proof['actual_epoch_yr']==.2 and proof['particles']==2 and not proof['spin16_exact']
    status=read(root/'runs/two/status.json');p=root/'runs/two'/status['checkpoint']/'state.json';p.write_bytes(p.read_bytes()+b' ')
    with pytest.raises(ValueError,match='SHA'):check(root,'two')


def test_closed_no_resume_and_fresh_names(tmp_path):
    root=tmp_path/'work';init(root,8);c=read_config(PACKAGE/'examples/two-body.json');register(root,'two',c)
    with pytest.raises(ValueError):register(root,'two',c)
    with pytest.raises(ValueError):register(root,'../escape',c)
    run(root,'two',.01)
    with pytest.raises(ValueError):run(root,'two',.02,resume=True)


def test_config_rejects_silent_invalid_physics():
    c=read_config(PACKAGE/'examples/two-body.json')
    for mutate in [lambda x:x['initial_state'].__setitem__('G',float('nan')),lambda x:x.__setitem__('unexpected',1),
                   lambda x:x['initial_state'].__setitem__('spin_state16',[1]*16),lambda x:x['diagnostics'].__setitem__('pairs',[[0,8]])]:
        x=copy.deepcopy(c);mutate(x)
        with pytest.raises(ValueError):validate(x)


def test_typer_help_and_no_unrequested_start(tmp_path):
    runner=CliRunner();r=runner.invoke(app,['--help']);assert r.exit_code==0 and 'import-state' in r.stdout and 'register' in r.stdout
    root=tmp_path/'new';r=runner.invoke(app,['init','--work-dir',str(root),'--max-active','12']);assert r.exit_code==0
    r=runner.invoke(app,['start','--work-dir',str(root),'--until','500000']);assert r.exit_code!=0 and not (root/'runs').exists()


def test_linux_command_identity_excludes_reused_and_zombie_pids():
    root=Path('/work');h={'name':'a','pid':123,'start_ticks':'456'}
    good={'start_ticks':'456','state':'R','cmdline':[b'python',b'-m',b'experiment_server.worker',str(root).encode(),b'a',b'500000']}
    with patch('experiment_server.manager.identity',return_value=good):assert alive(h,root)
    for bad in [{**good,'state':'Z'},{**good,'start_ticks':'987'},{**good,'cmdline':[b'python',b'a']}]:
        with patch('experiment_server.manager.identity',return_value=bad):assert not alive(h,root)


def test_batch_capacity_refuses_before_launch(tmp_path):
    root=tmp_path/'work';init(root,1);c=read_config(PACKAGE/'examples/two-body.json')
    register(root,'a',c);register(root,'b',c)
    r=read(root/'experiments.json')
    for case in r['cases']:case['native_check']['os']='linux'
    atomic(root/'experiments.json',r)
    fcntl=types.SimpleNamespace(LOCK_EX=1,LOCK_NB=2,flock=lambda *args:None)
    with patch.dict(sys.modules,{'fcntl':fcntl}),patch('experiment_server.manager.sys.platform','linux'),patch('experiment_server.manager.subprocess.Popen') as launched:
        with pytest.raises(ValueError,match='并发'):start(root,['a','b'],.2)
        assert not launched.called and not (root/'runs').exists()


def test_ctl_exact_state_original_sampler_and_save(tmp_path):
    c=read_config(PACKAGE/'examples/nacrea-blue-100k.json');sim,c,refs=restore(c);before=state_of(sim,c,refs)
    assert before==c['initial_state']
    e,l=budget(sim,c,refs);row,reasons=sample(sim,c,refs,(e,l));assert not reasons
    assert row['spin_state16']==c['initial_state']['spin_state16']
    assert row['bodies']['satellite_nacrea']['psi_deg']==pytest.approx(.2171208698,abs=1e-8)
    root=tmp_path/'work';init(root,8);c['integration']['interval_yr']=.002;c['integration']['checkpoint_yr']=.004
    register(root,'blue',c);run(root,'blue',100000.004);proof=check(root,'blue')
    assert proof['actual_epoch_yr']==100000.004 and proof['particles']==7 and proof['spin16_exact']


def test_ctl_variant_keeps_particles_spin_and_changes_only_declared_material(tmp_path):
    from experiment_server.variants import derive
    root=tmp_path/'work';init(root,8);c=read_config(PACKAGE/'examples/nacrea-zero.json');register(root,'base',c)
    derive(root,'lag045','base',.45,0,None);_,new=get_case(root,'lag045')
    assert new['initial_state']['particles']==c['initial_state']['particles']
    assert new['initial_state']['spin_state16']==c['initial_state']['spin_state16']
    assert new['initial_state']['settings']['k2tau_yr'][2]==c['provenance']['reference_k2tau_yr']*.45
    derive(root,'phase','base',None,.1,'satellite_vigil');_,new=get_case(root,'phase')
    assert new['initial_state']['particles']!=c['initial_state']['particles'] and new['initial_state']['spin_state16']==c['initial_state']['spin_state16']


def test_dynamic_plot_conservative_saved_pairs(tmp_path):
    from experiment_server.plotting import render
    root=tmp_path/'work';init(root,8);c=read_config(PACKAGE/'examples/two-body.json');register(root,'arbitrary',c);run(root,'arbitrary',.2)
    render(root,None,0,False,None);d=read(root/'plots/latest-sources.json')
    assert d['only_actual_saved_rows'] and d['cases'][0]['actual_window_yr']==[0,.2]
    assert 'star__planet.relative_speed_km_s' in d['cases'][0]['panel_statistics']
