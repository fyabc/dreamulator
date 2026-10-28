"""Source patches for ExoPlaSim 3.4.2's PlaSim Fortran, built into a private copy.

The installed ``exoplasim`` package stays untouched.  :func:`patched_source_dir`
copies the package's build tree into a cache directory keyed by the patch hash,
applies every :class:`FortranPatch` by exact anchor replacement and compiles the
requested resolution there with ExoPlaSim's own ``compile.sh``.  The runner then
passes the copy's ``plasim/run`` as ``exoplasim.Model(source=...)``, so a
changed patch can never reuse a stale binary.

Patches (2026-10-26, T85 diagnosis):

- **River routing sub-steps** (``landmod.f90``, ``roffstep``).  PlaSim routes
  river water with the explicit linear upwind scheme of Sausen et al. (1994;
  PlaSim Reference Manual §3.5.3).  A land cell's old storage enters the next
  step multiplied by ``1 - Δt λ``, where ``λ`` (s⁻¹) is the sum of its outward
  face coefficients ``duroff``/``dvroff``.  Storage stays non-negative only for
  ``Δt λ <= 1``, and ``Δt λ > 2`` makes an alternating mode grow.  The flow
  coefficient scales as ``4.2 / Δx · slope^0.18``, so finer grids raise ``λ``
  faster than their shorter atmosphere step lowers ``Δt``: nacrea T85 at
  20 min reached ``Δt λ = 3.57`` and crashed, and T42 at 45 min reaches 1.53.
  The patch derives ``n = ceil(Δt · max λ)`` from the coefficients actually in
  use (once, on the first routing call, identical on every MPI rank), routes
  ``n`` sub-steps of ``Δt / n`` with the land source held over the step, and
  returns the step-mean runoff so the ocean receives the same water that left
  the storage.  ``n = 1`` runs the original code path unchanged.
- **Restart river storage** (``glaciermod.f90``, ``oroini``).  ``oroini``
  rebuilds the routing coefficients after ``landini`` read the restart file
  and unconditionally zeroed ``driver`` (river storage, m) and ``drunoff``,
  so every warm start silently drained the rivers.  The patch zeroes them on a
  cold start only.
- **Restart surface wetness** (``landmod.f90``, ``landini``).  The restart
  branch's ``limitwater`` block (hard-defined on) recomputed the evaporation
  wetness factor ``drhs = dwatc / (drhsfull · dwmax)`` on every cell without
  ``dsnow``, which is not restored at that point; sea cells got 0, so the
  first step after each restart had no open-ocean evaporation, and land cells
  lost the ``min(1, ·)`` cap of ``landstep``.  The patch keeps the restart
  value and recomputes only land cells whose soil capacity actually changed,
  with the ``landstep`` formula.
- **Restart leapfrog level** (``glaciermod.f90``, ``glacierini``).  Both
  branches scattered the current ``ln p_s`` into the previous time level
  (``call mpscsp(sp,spm,1)``), turning every restart into a forward start.
  The patch keeps the restart's ``spm`` unless it is a cold start or
  ``nspinit`` rebuilds ``sp`` from the orography.

With all four, a continuous run and a run split by a restart are bit-identical
(nacrea T42 and T85 checks, 2026-10-26).

- **High-frequency humidity output** (``plasim.f90``, ``gridpointd``).
  Spectral humidity ``sqout`` was refreshed only on ordinary output steps,
  while snapshots and high-cadence streams wrote that cache more often.
  With one ordinary output per five days, 1.5-hour snapshots repeated stale
  humidity, including an initial zero output cache after warm starts.
  Frequent output now refreshes the diagnostic transform each step, also
  keeping accumulated spectral humidity current. The transform writes only
  the output buffer; the integration state and physical parameters are kept.

Epistemic class: both are numerical-consistency repairs (stability and
conservation of an existing scheme); no physical parameter changes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

EXOPLASIM_VERSION = "3.4.2"


@dataclass(frozen=True)
class FortranPatch:
    """Replace one exact source fragment of ``plasim/src/<file>``."""

    name: str
    file: str
    anchor: str
    replacement: str


_ROFFSTEP_ORIGINAL = """      subroutine roffstep
      use landmod

!
!     make advection
!

      call mkradv(driver,drunoff,duroff,dvroff,darea,dls)

!
!     new water
!

      where(dls(:) > 0.) driver(:)=driver(:)+drunoff(:)*deltsec

      return
      end subroutine roffstep
"""

_ROFFSTEP_PATCHED = """      subroutine roffstep
      use landmod
!
!     dreamulator patch routing-cfl: the explicit upwind routing keeps the
!     storage non-negative only while deltsec times the total outflow rate
!     of a land cell is at most one.  The sub-step count follows from the
!     largest rate; the land source is held over the step and the step-mean
!     runoff (river discharge into sea cells included) is returned.
!
      real zsource(NHOR), zsum(NHOR), zdt
      real, save :: zratemax = -1.
      integer, save :: nsublast = 0
      integer js, nsub

      if (zratemax < 0.) call roffrate(zratemax)
      nsub = max(1, ceiling(deltsec*zratemax))
      if (nsub /= nsublast .and. mypid == NROOT) then
       write(nud,'(" routing-cfl: max outflow rate ",es14.7," 1/s, deltsec ",f9.2,  &
     &       " s, sub-steps ",i4)') zratemax, deltsec, nsub
      endif
      nsublast = nsub

      if (nsub == 1) then
       call mkradv(driver,drunoff,duroff,dvroff,darea,dls)
       where(dls(:) > 0.) driver(:)=driver(:)+drunoff(:)*deltsec
       return
      endif

      zdt = deltsec
      zsource(:) = drunoff(:)
      zsum(:) = 0.
      deltsec = zdt / real(nsub)
      do js = 1, nsub
       drunoff(:) = zsource(:)
       call mkradv(driver,drunoff,duroff,dvroff,darea,dls)
       where(dls(:) > 0.) driver(:)=driver(:)+drunoff(:)*deltsec
       zsum(:) = zsum(:) + drunoff(:)
      enddo
      drunoff(:) = zsum(:) / real(nsub)
      deltsec = zdt

      return
      end subroutine roffstep

!     ===================
!     SUBROUTINE ROFFRATE
!     ===================

      subroutine roffrate(prate)
      use landmod
!
!     Largest total outflow rate (1/s) over land cells for the routing
!     coefficients in use; the face conventions follow mkradv.
!
      real prate
      real zu(NLON,NLAT), zv(NLON,NLAT), zl(NLON,NLAT), zout(NLON,NLAT)
      integer jlon, jlat

      call mpgagp(zu,duroff,1)
      call mpgagp(zv,dvroff,1)
      call mpgagp(zl,dls,1)
      prate = 0.
      if (mypid == NROOT) then
       zout(:,:) = 0.
       do jlat = 1, NLAT
!       zonal face east of jlon drains jlon when positive, jlon+1 otherwise
        do jlon = 1, NLON
         zout(jlon,jlat) = zout(jlon,jlat) + max(zu(jlon,jlat),0.)
        enddo
        zout(1,jlat) = zout(1,jlat) + max(-zu(NLON,jlat),0.)
        do jlon = 2, NLON
         zout(jlon,jlat) = zout(jlon,jlat) + max(-zu(jlon-1,jlat),0.)
        enddo
!       meridional face south of jlat drains jlat when negative, jlat+1 otherwise
        zout(:,jlat) = zout(:,jlat) + max(-zv(:,jlat),0.)
        if (jlat > 1) zout(:,jlat) = zout(:,jlat) + max(zv(:,jlat-1),0.)
       enddo
       where (zl(:,:) <= 0.) zout(:,:) = 0.
       prate = maxval(zout)
      endif
      call mpbcr(prate)

      return
      end subroutine roffrate
"""

_OROINI_ORIGINAL = """      call mpscgp(zuroff,duroff,1)
      call mpscgp(zvroff,dvroff,1)

      driver(:)=0.
      drunoff(:)=0.

      return
      end subroutine oroini"""

_OROINI_PATCHED = """      call mpscgp(zuroff,duroff,1)
      call mpscgp(zvroff,dvroff,1)

!     dreamulator patch restart-river: keep the river storage and runoff
!     that landini read from a restart file
      if (nrestart == 0) then
       driver(:)=0.
       drunoff(:)=0.
      endif

      return
      end subroutine oroini"""

_WETNESS_ORIGINAL = """       do jhor=1,NHOR
          dwmax(jhor) = AMAX1(wsmax,0.0)
          if (dsnow(jhor) .le. 0.) then
             drhs(jhor) = 0.
             if (dwmax(jhor) > 0.) &
     &           drhs(jhor) = dwatc(jhor)/(drhsfull*dwmax(jhor))
          endif
       enddo
"""

_WETNESS_PATCHED = """!     dreamulator patch restart-wetness: drhs comes from the restart file;
!     recompute it only on land cells whose soil capacity changed, with the
!     landstep formula (dsnow is not restored yet, dsnowz is)
       do jhor=1,NHOR
          zdwmax0 = dwmax(jhor)
          dwmax(jhor) = AMAX1(wsmax,0.0)
          if (dls(jhor) > 0. .and. dwmax(jhor) /= zdwmax0                &
     &        .and. dsnowz(jhor) <= 0. .and. dglac(jhor) <= 0.5) then
             drhs(jhor) = 0.
             if (dwmax(jhor) > 0.)                                         &
     &           drhs(jhor) = AMIN1(1.,dwatc(jhor)/(drhsfull*dwmax(jhor)))
          endif
       enddo
"""

_LEAPFROG_ANCHORS = (
    "        call mpscsp(sp,spm,1)\n        \n        where (dsnowz(:) > 30.0)",
    "        call mpscsp(sp,spm,1)\n        \n        call mpgagp(zoro,doro,1)",
)

_HUMIDITY_OUTPUT_ORIGINAL = "      if (mod(nstep,nafter)==0 .and. nqspec == 1) then\n"
_HUMIDITY_OUTPUT_PATCHED = (
    "!     dreamulator patch output-humidity: frequent output consumes current q;\n"
    """!     refresh the diagnostic transform each step when those streams are on
      if (nqspec == 1 .and.                                          &
     &    (mod(nstep,nafter)==0 .or. nsnapshot > 0 .or.               &
     &     nhcadence > 0 .or. nwritehurricane > 0)) then
"""
)


def _leapfrog_patch(anchor: str) -> str:
    return anchor.replace(
        "        call mpscsp(sp,spm,1)\n",
        "!       dreamulator patch restart-leapfrog: keep the restart's previous level\n"
        "        if (nrestart == 0 .or. nspinit > 0) call mpscsp(sp,spm,1)\n",
    )


PATCHES: tuple[FortranPatch, ...] = (
    FortranPatch("routing-cfl", "landmod.f90", _ROFFSTEP_ORIGINAL, _ROFFSTEP_PATCHED),
    FortranPatch("restart-river", "glaciermod.f90", _OROINI_ORIGINAL, _OROINI_PATCHED),
    FortranPatch("restart-wetness", "landmod.f90", _WETNESS_ORIGINAL, _WETNESS_PATCHED),
    *(
        FortranPatch(f"restart-leapfrog-{i}", "glaciermod.f90", a, _leapfrog_patch(a))
        for i, a in enumerate(_LEAPFROG_ANCHORS, 1)
    ),
    FortranPatch(
        "output-humidity", "plasim.f90", _HUMIDITY_OUTPUT_ORIGINAL, _HUMIDITY_OUTPUT_PATCHED
    ),
)


def patch_id(patches: tuple[FortranPatch, ...] = PATCHES) -> str:
    """Short content hash of the patch set (pure); names the build cache."""
    digest = hashlib.sha256(EXOPLASIM_VERSION.encode())
    for p in patches:
        for part in (p.name, p.file, p.anchor, p.replacement):
            digest.update(part.encode())
            digest.update(b"\0")
    return digest.hexdigest()[:12]


def apply_patch_text(text: str, patch: FortranPatch) -> str:
    """Apply one patch to a source text (pure); the anchor must occur exactly once."""
    count = text.count(patch.anchor)
    if count != 1:
        raise RuntimeError(
            f"patch {patch.name}: anchor found {count} times in {patch.file} "
            f"(expected once; is this ExoPlaSim {EXOPLASIM_VERSION}?)"
        )
    return text.replace(patch.anchor, patch.replacement)


def _installed_package_dir() -> Path:
    import exoplasim

    return Path(exoplasim.__file__).resolve().parent


def default_cache_root() -> Path:
    """Build cache inside the active environment, never in the repository."""
    import sys

    return Path(sys.prefix) / "share" / "dreamulator-plasim"


def patched_source_dir(cache_root: Path | None = None) -> Path:
    """Copy of the ExoPlaSim package with :data:`PATCHES` applied; created once.

    The copy carries ``compile.sh``, the compiler option files and the
    ``plasim/`` tree, but none of the installed ``plasim/run`` binaries.
    """
    root = (cache_root or default_cache_root()) / f"exoplasim-{EXOPLASIM_VERSION}-{patch_id()}"
    stamp = root / "dreamulator_patches.json"
    if stamp.exists():
        return root
    src = _installed_package_dir()
    tmp = root.with_name(root.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)

    def _skip(directory: str, names: list[str]) -> set[str]:
        skipped = {n for n in names if n == "__pycache__"}
        if Path(directory).name in ("run", "bin"):
            skipped |= {n for n in names if n.endswith(".x") and n.startswith("most_plasim")}
        return skipped

    shutil.copytree(src, tmp, ignore=_skip, symlinks=True)
    hashes = {}
    for p in PATCHES:
        path = tmp / "plasim" / "src" / p.file
        path.write_text(apply_patch_text(path.read_text(encoding="utf-8"), p), encoding="utf-8")
    for name in sorted({p.file for p in PATCHES}):
        hashes[name] = hashlib.sha256((tmp / "plasim" / "src" / name).read_bytes()).hexdigest()
    (tmp / "dreamulator_patches.json").write_text(
        json.dumps(
            {
                "patch_id": patch_id(),
                "exoplasim": EXOPLASIM_VERSION,
                "patches": [p.name for p in PATCHES],
                "patched_source_sha256": hashes,
                "copied_from": str(src),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    tmp.rename(root)
    return root


def patched_executable(
    resolution: str, layers: int, ncpus: int, precision: int = 8, cache_root: Path | None = None
) -> Path:
    """Path of the patched PlaSim binary, compiling it in the cache copy if missing.

    Returns the ``plasim/run`` directory to pass as ``exoplasim.Model(source=...)``.
    """
    root = patched_source_dir(cache_root)
    nsp = int(resolution.upper().lstrip("T"))
    exe = root / "plasim" / "run" / f"most_plasim_t{nsp}_l{layers}_p{ncpus}.x"
    if exe.exists():
        return exe.parent

    # compile.sh builds every resolution in the one shared plasim/bld tree.
    # The build lock follows td_canvas_worker: POSIX flock, Windows
    # msvcrt.locking on byte 0 (LK_LOCK retries ~10 s, matching flock's
    # blocking wait); both release when the with-block closes the file.
    with (root / "build.lock").open("w") as lock:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(lock, fcntl.LOCK_EX)
        if not exe.exists():
            skip = ("MAKEFLAGS", "MFLAGS", "GNUMAKEFLAGS", "LD_PRELOAD")
            env = {k: v for k, v in os.environ.items() if k not in skip}
            log = root / f"compile_t{nsp}_l{layers}_p{ncpus}.log"
            with log.open("w", encoding="utf-8") as f:
                subprocess.run(
                    ["bash", "./compile.sh", "-n", str(ncpus), "-p", str(precision),
                     "-r", f"T{nsp}", "-v", str(layers)],
                    cwd=root, env=env, stdout=f, stderr=subprocess.STDOUT, check=False,
                )  # fmt: skip
            if not exe.exists():
                raise RuntimeError(f"patched PlaSim build failed; see {log}")
    return exe.parent


def provenance(source_dir: Path, executable: Path) -> dict[str, object]:
    """Patch record for the run manifest."""
    stamp: dict[str, object] = json.loads(
        (source_dir / "dreamulator_patches.json").read_text(encoding="utf-8")
    )
    stamp.pop("copied_from", None)
    stamp["executable_sha256"] = hashlib.sha256(executable.read_bytes()).hexdigest()
    return stamp
