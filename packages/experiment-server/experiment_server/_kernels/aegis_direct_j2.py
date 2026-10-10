"""Independent conservative J2 force, compiled callback for REBOUND 5.1.1.

The ABI is checked against ctypes before compilation. No variational particles
are supported. The primary receives the equal/opposite reaction force.
"""

import ctypes

import numpy as np
import rebound
from numba import carray, cfunc, types
from numba.extending import intrinsic


@intrinsic
def integer_to_double_pointer(typing_context, source):
    signature = types.CPointer(types.float64)(source)

    def codegen(context, builder, sig, args):
        return builder.inttoptr(args[0], context.get_value_type(sig.return_type))

    return signature, codegen


@intrinsic
def double_pointer(typing_context, source):
    signature = types.CPointer(types.float64)(source)

    def codegen(context, builder, sig, args):
        return builder.bitcast(args[0], context.get_value_type(sig.return_type))

    return signature, codegen


def make_j2_callback(primary_index, satellite_indices, j2, radius_au, spin, particle_count=None):
    assert ctypes.sizeof(ctypes.c_void_p) == 8
    assert rebound.Simulation._particles.offset == 88
    assert rebound.Simulation.N.offset == 72
    assert rebound.Simulation.G.offset == 8
    assert ctypes.sizeof(rebound.Particle) == 112
    assert rebound.Particle.m.offset == 72
    assert rebound.Particle.ax.offset == 48
    n_real = particle_count if particle_count is not None else 4 + len(satellite_indices)
    indices = np.array(satellite_indices, dtype=np.int64)
    sx, sy, sz = spin

    @cfunc(types.void(types.CPointer(types.uint64)))
    def acceleration(sim_words):
        words = carray(sim_words, 12)
        particles = carray(integer_to_double_pointer(words[11]), (n_real, 14))
        gravitational_constant = carray(double_pointer(sim_words), 2)[1]
        primary_mass = particles[primary_index, 9]
        for i in indices:
            rx = particles[i, 0] - particles[primary_index, 0]
            ry = particles[i, 1] - particles[primary_index, 1]
            rz = particles[i, 2] - particles[primary_index, 2]
            r2 = rx * rx + ry * ry + rz * rz
            z = rx * sx + ry * sy + rz * sz
            factor = 1.5 * j2 * gravitational_constant * primary_mass * radius_au**2 / (r2**2 * np.sqrt(r2))
            shape = 5 * z * z / r2 - 1
            ax = factor * (shape * rx - 2 * z * sx)
            ay = factor * (shape * ry - 2 * z * sy)
            az = factor * (shape * rz - 2 * z * sz)
            particles[i, 6] += ax
            particles[i, 7] += ay
            particles[i, 8] += az
            ratio = particles[i, 9] / primary_mass
            particles[primary_index, 6] -= ratio * ax
            particles[primary_index, 7] -= ratio * ay
            particles[primary_index, 8] -= ratio * az

    return acceleration


def total_energy(sim, primary_index, satellite_indices, j2, radius_au, spin):
    primary = sim.particles[primary_index]
    extra = 0.0
    for i in satellite_indices:
        sat = sim.particles[i]
        r = np.array([sat.x - primary.x, sat.y - primary.y, sat.z - primary.z])
        norm = np.linalg.norm(r)
        z = np.dot(r, spin)
        extra += sim.G * primary.m * sat.m * j2 * radius_au**2 / (2 * norm**3) * (3 * z**2 / norm**2 - 1)
    return sim.energy() + extra
