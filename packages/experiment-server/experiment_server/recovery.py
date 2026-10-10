"""Restore verified native checkpoint into a new simulation with fresh callbacks."""
import copy,warnings
import rebound
from .manager import get_case
from .worker import verified_checkpoint
from .storage import read
from .models import restore,state_of
from .config import PARTICLE_KEYS


def check(root,name):
    _,c=get_case(root,name);run=root/'runs'/name;status=read(run/'status.json');block,state=verified_checkpoint(run,status)
    c=copy.deepcopy(c);c['initial_state']=state;sim,config,refs=restore(c)
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore',message='You have to reset function pointers.*',category=RuntimeWarning)
        loaded=rebound.Simulation(str(block/'particles.bin'))
    actual=[{k:float(getattr(p,k)) for k in PARTICLE_KEYS} for p in loaded.particles]
    assert loaded.t==sim.t==status['epoch_yr'] and actual==state['particles']
    assert state_of(sim,config,refs)==state
    return {'name':name,'status':status['status'],'actual_epoch_yr':float(sim.t),'particles':sim.N,'all_particle_fields_exact':True,
            'spin16_exact':bool(refs),'externalODE_callback_reattached':bool(refs),'files_SHA_verified':True,'new_integration_added':False}
