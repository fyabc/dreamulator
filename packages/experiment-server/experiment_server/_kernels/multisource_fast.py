"""Allocation-light equivalent of linear multi-source tide tensor algebra.

Reference implementation remains multisource_tides.combined_tide. This kernel
uses scalar3-vector arithmetic and fixed tensor loops; physics is unchanged.
"""

import numpy as np
from numba import njit

G=39.476926421373


@njit
def combined_tide_fast(p,w,source,radius,k2,lag):
    nbody=p.shape[0]
    tensor=np.zeros((3,3));derivative=np.zeros((3,3))
    for target in range(nbody):
        if target==source:continue
        rx=p[target,0]-p[source,0];ry=p[target,1]-p[source,1];rz=p[target,2]-p[source,2]
        vx=p[target,3]-p[source,3];vy=p[target,4]-p[source,4];vz=p[target,5]-p[source,5]
        length=np.sqrt(rx*rx+ry*ry+rz*rz)
        nx=rx/length;ny=ry/length;nz=rz/length
        radial=nx*vx+ny*vy+nz*vz
        dx=(vx-nx*radial)/length;dy=(vy-ny*radial)/length;dz=(vz-nz*radial)/length
        amplitude=G*p[target,9]/length**3
        for j in range(3):
            nj=nx if j==0 else ny if j==1 else nz
            dj=dx if j==0 else dy if j==1 else dz
            for k in range(3):
                nk=nx if k==0 else ny if k==1 else nz
                dk=dx if k==0 else dy if k==1 else dz
                shape=3*nj*nk-(1. if j==k else 0.)
                tensor[j,k]+=amplitude*shape
                derivative[j,k]+=amplitude*(-3*radial/length*shape+3*(dj*nk+nj*dk))
    wx=w[0];wy=w[1];wz=w[2]
    W=np.zeros((3,3))
    W[0,1]=-wz;W[0,2]=wy;W[1,0]=wz;W[1,2]=-wx;W[2,0]=-wy;W[2,1]=wx
    cp=radius**5*lag/(6*G);sp=radius**5*k2/(6*G)
    response=np.zeros((3,3));heat=0.;norm=0.
    for j in range(3):
        for k in range(3):
            value=derivative[j,k]
            for a in range(3):value+=tensor[j,a]*W[a,k]-W[j,a]*tensor[a,k]
            heat+=cp*value*value
            norm+=tensor[j,k]*tensor[j,k]
            response[j,k]=sp*tensor[j,k]-cp*value
    forces=np.zeros((nbody,3));torque=np.zeros(3)
    for target in range(nbody):
        if target==source:continue
        rx=p[target,0]-p[source,0];ry=p[target,1]-p[source,1];rz=p[target,2]-p[source,2]
        length=np.sqrt(rx*rx+ry*ry+rz*rz)
        nx=rx/length;ny=ry/length;nz=rz/length
        ax=response[0,0]*nx+response[0,1]*ny+response[0,2]*nz
        ay=response[1,0]*nx+response[1,1]*ny+response[1,2]*nz
        az=response[2,0]*nx+response[2,1]*ny+response[2,2]*nz
        projection=nx*ax+ny*ay+nz*az
        scale=G*p[target,9]/length**4
        fx=scale*(6*ax-15*projection*nx);fy=scale*(6*ay-15*projection*ny);fz=scale*(6*az-15*projection*nz)
        forces[target,0]=fx;forces[target,1]=fy;forces[target,2]=fz
        torque[0]-=ry*fz-rz*fy;torque[1]-=rz*fx-rx*fz;torque[2]-=rx*fy-ry*fx
    potential=-radius**5*k2/(12*G)*norm
    return forces,torque,heat,potential
