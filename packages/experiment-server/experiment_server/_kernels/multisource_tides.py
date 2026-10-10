"""Linear instantaneous equilibrium + first-order constant-lag tensor tides.

Only Nacrea is treated with a combined tidal tensor. The tensor is the sum of
all other monopoles. Includes cross terms, paired orbital reaction, spin torque
and nonnegative heat. This is still linear equilibrium tide, not ocean modes,
frequency-dependent rheology, thermal evolution or a dynamical deformable body.
"""

import numpy as np
from numba import njit

G=39.476926421373


@njit
def combined_tide(p,w,source,radius,k2,lag):
    nbody=p.shape[0]
    tensor=np.zeros((3,3));derivative=np.zeros((3,3))
    for target in range(nbody):
        if target==source:continue
        r=p[target,:3]-p[source,:3]
        v=p[target,3:6]-p[source,3:6]
        length=np.sqrt(np.dot(r,r));normal=r/length
        radial=np.dot(normal,v);ndot=(v-normal*radial)/length
        amplitude=G*p[target,9]/length**3
        for j in range(3):
            for k in range(3):
                shape=3*normal[j]*normal[k]-(1. if j==k else 0.)
                tensor[j,k]+=amplitude*shape
                derivative[j,k]+=amplitude*(-3*radial/length*shape+3*(ndot[j]*normal[k]+normal[j]*ndot[k]))
    wx,wy,wz=w
    W=np.array([[0.,-wz,wy],[wz,0.,-wx],[-wy,wx,0.]])
    corotating=derivative-W@tensor+tensor@W
    heat_pref=radius**5*lag/(6*G)
    static_pref=radius**5*k2/(6*G)
    forces=np.zeros((nbody,3));torque=np.zeros(3)
    # For symmetric traceless A, A:dT/dr = GM/r^4*(6An-15(nAn)n).
    for target in range(nbody):
        if target==source:continue
        r=p[target,:3]-p[source,:3]
        length=np.sqrt(np.dot(r,r));normal=r/length
        for A,coefficient in [(tensor,static_pref),(corotating,-heat_pref)]:
            An=A@normal;projection=np.dot(normal,An)
            f=coefficient*G*p[target,9]/length**4*(6*An-15*projection*normal)
            forces[target]+=f
        torque-=np.cross(r,forces[target])
    heat=heat_pref*np.sum(corotating*corotating)
    potential=-radius**5*k2/(12*G)*np.sum(tensor*tensor)
    return forces,torque,heat,potential
