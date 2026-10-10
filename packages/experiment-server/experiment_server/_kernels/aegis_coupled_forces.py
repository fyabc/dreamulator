"""Continuous J2 + equilibrium tides + spin torques, experimental REBOUND ABI.

Mignard constant-time-lag force matches the dissipative part of REBOUNDx
tides_spin (Eggleton et al. 1998), plus static equilibrium tide potential.
J2 is read from YAML independently of an assumed fluid Love number.
"""

import ctypes
import numpy as np
import rebound
from numba import carray, cfunc, njit, types
from .aegis_direct_j2 import integer_to_double_pointer, double_pointer
from .multisource_tides import combined_tide
from .multisource_fast import combined_tide_fast


@njit
def scalar_contributions(p, omega, source, target, radius, k2, k2tau, j2):
    """Force on target and heat power for tides/J2 raised on source."""
    rx=p[target,0]-p[source,0]; ry=p[target,1]-p[source,1]; rz=p[target,2]-p[source,2]
    vx=p[target,3]-p[source,3]; vy=p[target,4]-p[source,4]; vz=p[target,5]-p[source,5]
    r2 = rx*rx+ry*ry+rz*rz
    rnorm = np.sqrt(r2)
    g = 39.476926421373
    fx=0.;fy=0.;fz=0.
    wx=omega[0];wy=omega[1];wz=omega[2]
    normw = np.sqrt(wx*wx+wy*wy+wz*wz)
    if j2 != 0:
        sx=wx/normw;sy=wy/normw;sz=wz/normw
        z = rx*sx+ry*sy+rz*sz
        pref = 1.5*j2*g*p[source,9]*p[target,9]*radius**2/rnorm**5
        shape=5*z*z/r2-1
        fx+=pref*(shape*rx-2*z*sx);fy+=pref*(shape*ry-2*z*sy);fz+=pref*(shape*rz-2*z*sz)
    if k2 != 0:
        pref=-3*g*k2*p[target,9]**2*radius**5/rnorm**8
        fx+=pref*rx;fy+=pref*ry;fz+=pref*rz
    ux=vx-(wy*rz-wz*ry);uy=vy-(wz*rx-wx*rz);uz=vz-(wx*ry-wy*rx)
    radial = rx*vx+ry*vy+rz*vz
    pref = 3*g*k2tau*p[target,9]**2*radius**5/rnorm**10
    fx-=pref*(2*radial*rx+r2*ux);fy-=pref*(2*radial*ry+r2*uy);fz-=pref*(2*radial*rz+r2*uz)
    heat = pref*(2*radial**2+r2*(ux*ux+uy*uy+uz*uz))
    return fx,fy,fz,heat


def contributions(p,omega,source,target,radius,k2,k2tau,j2):
    fx,fy,fz,heat=scalar_contributions(p,omega,source,target,radius,k2,k2tau,j2)
    return np.array([fx,fy,fz]),heat


def make_callbacks(ode, radii, love, lag_products, inertias, j2, n=5, fully_coupled=False,all_permanent_figures=False,multisource_nacrea=False,fast_multisource=False):
    assert rebound.Simulation._particles.offset == 88
    assert rebound.ODE.r.offset == 128
    assert rebound.ODE._y1.offset == 96
    assert ctypes.sizeof(rebound.Particle) == 112
    ode_address = ctypes.addressof(ode)
    quadrupoles=np.asarray(j2 if isinstance(j2,(list,tuple,np.ndarray)) else [0.,j2,0.,0.,0.],dtype=np.float64)
    radii=np.asarray(radii,dtype=np.float64)
    love=np.asarray(love,dtype=np.float64)
    lag_products=np.asarray(lag_products,dtype=np.float64)
    inertias=np.asarray(inertias,dtype=np.float64)
    # Structured sources: Aegis index1, moons index2..4. Star has no tides of its own.
    # Tides on Aegis from star/moons, and on each moon from Aegis; no moon-moon tides.
    sources=np.array([1,1,1,1,2,3,4]+[1]*(n-5),dtype=np.int64)
    targets=np.array([0,2,3,4,1,1,1]+list(range(5,n)),dtype=np.int64)
    shape_only=np.zeros(len(sources),dtype=np.bool_)
    if all_permanent_figures:
        # Every other monopole acts on each satellite's permanent quadrupole.
        # Existing target=host pairs remain unchanged; extra pairs add neither
        # induced equilibrium tides nor dissipative lag terms.
        extra=[(s,t) for s in [2,3,4] for t in range(n) if t!=s and t!=1]
        sources=np.concatenate([sources,np.array([s for s,t in extra],dtype=np.int64)])
        targets=np.concatenate([targets,np.array([t for s,t in extra],dtype=np.int64)])
        shape_only=np.concatenate([shape_only,np.ones(len(extra),dtype=np.bool_)])
    pair_count=len(sources)
    tide_kernel=combined_tide_fast if fast_multisource else combined_tide

    @cfunc(types.void(types.CPointer(types.uint64)))
    def force_callback(words):
        head=carray(words,12)
        p=carray(integer_to_double_pointer(head[11]),(n,14))
        # Read pointer bits by bitcast to uint64 through an intrinsic is avoided:
        # y1 offset is ABI checked and loaded via typed pointer below.
        state_address=read_pointer(ode_address+96) if fully_coupled else read_pointer(ode_address+8)
        if state_address == 0:
            state_address=read_pointer(ode_address+8)
        y=carray(integer_to_double_pointer(state_address),16)
        for pair in range(pair_count):
            source=sources[pair]; target=targets[pair]
            w=y[(source-1)*3:(source-1)*3+3]
            k=love[source] if target<5 and not shape_only[pair] and not (multisource_nacrea and source==2) else 0.
            lag=lag_products[source] if target<5 and not shape_only[pair] and not (multisource_nacrea and source==2) else 0.
            fx,fy,fz,heat=scalar_contributions(p,w,source,target,radii[source],k,lag,quadrupoles[source])
            p[target,6]+=fx/p[target,9];p[target,7]+=fy/p[target,9];p[target,8]+=fz/p[target,9]
            p[source,6]-=fx/p[source,9];p[source,7]-=fy/p[source,9];p[source,8]-=fz/p[source,9]
        if multisource_nacrea:
            f,tau,power,U=tide_kernel(p,y[3:6],2,radii[2],love[2],lag_products[2])
            for target in range(n):
                if target==2:continue
                for axis in range(3):
                    p[target,6+axis]+=f[target,axis]/p[target,9]
                    p[2,6+axis]-=f[target,axis]/p[2,9]

    @cfunc(types.void(types.CPointer(types.uint64),types.CPointer(types.float64),types.CPointer(types.float64),types.float64))
    def spin_callback(ode_words,dy_ptr,y_ptr,t):
        head=carray(ode_words,17)
        sim_address=head[16]
        sim_head=carray(integer_to_uint64_pointer(sim_address),12)
        p=carray(integer_to_double_pointer(sim_head[11]),(n,14))
        y=carray(y_ptr,16); dy=carray(dy_ptr,16)
        for axis in range(16):dy[axis]=0.
        for pair in range(pair_count):
            source=sources[pair];target=targets[pair]
            w=y[(source-1)*3:(source-1)*3+3]
            k=love[source] if target<5 and not shape_only[pair] and not (multisource_nacrea and source==2) else 0.
            lag=lag_products[source] if target<5 and not shape_only[pair] and not (multisource_nacrea and source==2) else 0.
            fx,fy,fz,heat=scalar_contributions(p,w,source,target,radii[source],k,lag,quadrupoles[source])
            rx=p[target,0]-p[source,0];ry=p[target,1]-p[source,1];rz=p[target,2]-p[source,2]
            dy[(source-1)*3]-=(ry*fz-rz*fy)/inertias[source]
            dy[(source-1)*3+1]-=(rz*fx-rx*fz)/inertias[source]
            dy[(source-1)*3+2]-=(rx*fy-ry*fx)/inertias[source]
            dy[12+source-1]+=heat
        if multisource_nacrea:
            f,tau,power,U=tide_kernel(p,y[3:6],2,radii[2],love[2],lag_products[2])
            for axis in range(3):dy[3+axis]+=tau[axis]/inertias[2]
            dy[13]+=power

    return force_callback,spin_callback


from numba.extending import intrinsic

@intrinsic
def integer_to_uint64_pointer(context,value):
    signature=types.CPointer(types.uint64)(value)
    def codegen(ctx,builder,sig,args):return builder.inttoptr(args[0],ctx.get_value_type(sig.return_type))
    return signature,codegen

@njit
def read_pointer(address):
    return carray(integer_to_uint64_pointer(address),1)[0]


def attach(sim,settings,spin_state):
    ode=sim.create_ode(16,needs_nbody=True)
    for i,value in enumerate(spin_state):ode.y[i]=value
    force,rhs=make_callbacks(ode,settings['radii_au'],settings['k2'],settings['k2tau_yr'],settings['inertias'],settings.get('j2_array',settings['j2']),n=sim.N,fully_coupled=str(sim.integrator)=='bs',all_permanent_figures=settings.get('all_permanent_figures',False),multisource_nacrea=settings.get('multisource_nacrea',False),fast_multisource=settings.get('fast_multisource',False))
    sim._afp=ctypes.cast(force.ctypes,rebound.simulation.AFF)
    sim._additional_forces=sim._afp
    ode._dfp=ctypes.cast(rhs.ctypes,type(ode._derivatives))
    ode._derivatives=ode._dfp
    sim.force_is_velocity_dependent=1
    return ode,force,rhs


def diagnostics(sim,settings,ode):
    spins=np.array([ode.y[i] for i in range(12)]).reshape(4,3)
    radii=settings['radii_au'];love=settings['k2'];quadrupoles=settings.get('j2_array',[0.,settings['j2'],0.,0.,0.])
    extra=0.
    pairs=[(1,0),(1,2),(1,3),(1,4),(2,1),(3,1),(4,1)]+[(1,i) for i in range(5,sim.N)]
    if settings.get('all_permanent_figures',False):
        pairs+=[(s,t) for s in [2,3,4] for t in range(sim.N) if t!=s and t!=1]
    for source,target in pairs:
        s=sim.particles[source]; t=sim.particles[target]
        r=np.array([t.x-s.x,t.y-s.y,t.z-s.z]); rn=np.linalg.norm(r)
        if quadrupoles[source]!=0:
            axis=spins[source-1]/np.linalg.norm(spins[source-1]);z=np.dot(r,axis)
            extra+=sim.G*s.m*t.m*quadrupoles[source]*radii[source]**2/(2*rn**3)*(3*z*z/rn**2-1)
        if target<5 and (source==1 or target==1) and not (source==2 and settings.get('multisource_nacrea',False)):extra-=.5*sim.G*love[source]*t.m**2*radii[source]**5/rn**6
    if settings.get('multisource_nacrea',False):
        p=np.array([[q.x,q.y,q.z,q.vx,q.vy,q.vz,0.,0.,0.,q.m,q.r,0.,0.,0.] for q in sim.particles])
        extra+=combined_tide(p,spins[1],2,radii[2],love[2],0.)[3]
    rotational=sum(.5*settings['inertias'][i+1]*np.dot(spins[i],spins[i]) for i in range(4))
    total_l=np.zeros(3)
    for p in sim.particles:total_l+=p.m*np.cross([p.x,p.y,p.z],[p.vx,p.vy,p.vz])
    for i in range(4):total_l+=settings['inertias'][i+1]*spins[i]
    heat=sum(ode.y[i] for i in range(12,16))
    return {'energy_plus_heat':sim.energy()+extra+rotational+heat,'angular_momentum':total_l.tolist(),'heat_integrated':heat,'spins':spins.tolist()}
