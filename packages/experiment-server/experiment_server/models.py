"""Model dispatch. No force/axis fitting or integration occurs during restore."""
import math
import numpy as np
import rebound
from .config import AU, YEAR, ENERGY_UNIT, PARTICLE_KEYS, validate


def restore(config):
    config = validate(config); state = config['initial_state']
    sim = rebound.Simulation(); sim.units = tuple(config['units']); sim.G = state['G']
    for p in state['particles']: sim.add(**p)
    sim.t = state['epoch_yr']; sim.integrator = 'bs'
    sim.integrator.eps_rel = config['integration']['eps_rel']; sim.integrator.eps_abs = config['integration']['eps_abs']
    refs = ()
    if config['model'] == 'coupled_ctl':
        from ._kernels.aegis_coupled_forces import attach
        refs = attach(sim, state['settings'], state['spin_state16'])
        assert [float(refs[0].y[i]) for i in range(16)] == state['spin_state16']
    assert sim.N == len(state['particles'])
    assert [{k:float(getattr(p, k)) for k in PARTICLE_KEYS} for p in sim.particles] == state['particles']
    return sim, config, refs


def state_of(sim, config, refs):
    state = {'epoch_yr': float(sim.t), 'G': float(sim.G),
             'particles': [{k:float(getattr(p, k)) for k in PARTICLE_KEYS} for p in sim.particles]}
    if refs:
        state.update(settings=config['initial_state']['settings'], spin_state16=[float(refs[0].y[i]) for i in range(16)])
    return state


def angle(a, b):
    return float(np.degrees(np.arccos(np.clip(np.dot(a,b)/np.linalg.norm(a)/np.linalg.norm(b), -1, 1))))


def normal(inc, node):
    return np.array([math.sin(inc)*math.sin(node), -math.sin(inc)*math.cos(node), math.cos(inc)])


def budget(sim, config, refs):
    if refs:
        from ._kernels.aegis_coupled_forces import diagnostics
        d = diagnostics(sim, config['initial_state']['settings'], refs[0])
        return d['energy_plus_heat'], np.asarray(d['angular_momentum'])
    momentum = sum((p.m * np.cross(p.xyz, p.vxyz) for p in sim.particles), np.zeros(3))
    return sim.energy(), momentum


def sample(sim, config, refs, initial_budget):
    diag = config['diagnostics']; names = config['body_names']; e, l = budget(sim, config, refs); e0,l0 = initial_budget
    row = {'time_yr': float(sim.t), 'energy_heat_error': float((e-e0)/max(abs(e0),1e-30)),
           'angular_momentum_error': float(np.linalg.norm(l-l0)/max(np.linalg.norm(l0),1e-30)), 'bodies': {}, 'pairs': {}}
    reasons = []
    star = diag.get('star', diag.get('primary',0)); host = diag.get('host',star)
    hostnormal = np.array([0.,0.,1.])
    if host != star:
        o=sim.particles[host].orbit(primary=sim.particles[star]); hostnormal=normal(o.inc,o.Omega)
    for i,p in enumerate(sim.particles):
        primary=host if i in diag.get('moons',[]) else star
        b = {}
        if i != primary:
            o=p.orbit(primary=sim.particles[primary])
            b.update(a_au=float(o.a),e=float(o.e),i_ref_deg=float(np.degrees(o.inc)),node_deg=float(np.degrees(o.Omega)))
            radius=np.linalg.norm(np.asarray(p.xyz)-sim.particles[primary].xyz)
            if o.a <= 0 or o.e >= .9 or radius < p.r+sim.particles[primary].r: reasons.append(names[i]+': sampled orbital boundary')
            if refs and i in [2,3,4]:
                ho=sim.particles[host].orbit(primary=sim.particles[star]); hill=ho.a*(1-ho.e)*(sim.particles[host].m/(3*sim.particles[star].m))**(1/3)
                if radius>hill:reasons.append(names[i]+': sampled Hill boundary')
        if refs and i in [1,2,3,4]:
            w=np.asarray([refs[0].y[(i-1)*3+k] for k in range(3)])
            b.update(rotation_days=float(2*np.pi*365.25/np.linalg.norm(w)),stellar_season_deg=angle(w,hostnormal),spin_fixed_z_deg=angle(w,np.array([0.,0.,1.])),heat_code=float(refs[0].y[12+i-1]))
            if i in [2,3,4]:b['psi_deg']=angle(w,normal(o.inc,o.Omega))
        row['bodies'][names[i]]=b
    if refs:row['spin_state16']=[float(refs[0].y[i]) for i in range(16)]
    for a,b in diag.get('pairs',[]):
        p,q=sim.particles[a],sim.particles[b]
        row['pairs'][names[a]+'__'+names[b]]={'distance_km':float(np.linalg.norm(np.asarray(p.xyz)-q.xyz)*AU/1000),
              'relative_speed_km_s':float(np.linalg.norm(np.asarray(p.vxyz)-q.vxyz)*AU/1000/YEAR)}
    return row,reasons
