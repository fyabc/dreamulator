"""Declared phase or material interventions, not hidden seed rerolls."""
import copy,math
import numpy as np
import rebound
from .manager import get_case,register
from .models import restore,state_of,budget
from .config import PARTICLE_KEYS


def derive(root,name,from_name,lag,phase_deg,body):
    _,c=get_case(root,from_name);c=copy.deepcopy(c)
    if not math.isfinite(phase_deg) or lag is not None and (not math.isfinite(lag) or lag<=0):raise ValueError('相位及CTL值须为有限有效数。')
    sim,c,refs=restore(c);before=state_of(sim,c,refs);e0,l0=budget(sim,c,refs)
    if lag is not None:
        if c['model']!='coupled_ctl':raise ValueError('point_mass不接受CTL参数。')
        i=c['diagnostics'].get('heat_body',2)
        reference=c.get('provenance',{}).get('reference_k2tau_yr')
        if reference is None:raise ValueError('配置provenance.reference_k2tau_yr须明确给出，避免把倍率误乘当前值。')
        c['initial_state']['settings']['k2tau_yr'][i]=reference*lag
    if phase_deg:
        if body is None or body not in c['body_names']:raise ValueError('改变相位须显式提供合法body名。')
        i=c['body_names'].index(body);primary=c['diagnostics'].get('host',0) if i in c['diagnostics'].get('moons',[]) else c['diagnostics'].get('star',c['diagnostics'].get('primary',0))
        if i==primary:raise ValueError('中心体不能设自身相位。')
        p=sim.particles[i];o=p.orbit(primary=sim.particles[primary])
        sim.particles[i]=rebound.Particle(simulation=sim,primary=sim.particles[primary],m=p.m,r=p.r,a=o.a,e=o.e,inc=o.inc,Omega=o.Omega,omega=o.omega,M=o.M+math.radians(phase_deg))
        sim.move_to_com();new=sim.particles[i].orbit(primary=sim.particles[primary])
        assert all(abs(getattr(o,k)-getattr(new,k))<1e-10 for k in ['a','e','inc','Omega','omega'])
    e1,l1=budget(sim,c,refs);c['initial_state']=state_of(sim,c,refs)
    assert [p['m'] for p in before['particles']]==[p['m'] for p in c['initial_state']['particles']]
    assert before.get('spin_state16')==c['initial_state'].get('spin_state16')
    c.setdefault('provenance',{})['variant']={'from_name':from_name,'phase_body':body,'phase_delta_deg':phase_deg,'CTL_reference_factor':lag,
                    'all16state_preserved':True,'energy_jump_code':e1-e0,'angular_momentum_jump_code':(l1-l0).tolist(),
                    'physical_initial_state_changed':bool(phase_deg),'not_a_numerical_chaos_control':bool(phase_deg)}
    return register(root,name,c)
