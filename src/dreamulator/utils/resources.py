"""CPU and memory budgets for process pools (standard library only, Linux, Windows, macOS).

The per-chunk stages size their pools from what the process may actually use: the CPUs of its
affinity mask and cgroup quota, and half the memory that is free right now (the project rule:
a job's peak stays below half the available memory, because running out reboots the machine).
"""

from __future__ import annotations

import math
import os
from pathlib import Path

#: Share of the currently available memory a pool may plan to use.
MEMORY_FRACTION = 0.5


def cpu_quota() -> int:
    """CPUs this process may use: affinity mask, capped by a cgroup CPU quota when one is set."""
    affinity = getattr(os, "sched_getaffinity", None)  # POSIX only
    try:
        n = len(affinity(0)) if affinity is not None else (os.cpu_count() or 1)
    except OSError:
        n = os.cpu_count() or 1
    for path in (Path("/sys/fs/cgroup/cpu.max"),):  # cgroup v2: "<quota> <period>" or "max ..."
        try:
            quota, period = path.read_text(encoding="utf-8").split()[:2]
        except (OSError, ValueError):
            continue
        if quota != "max":
            n = min(n, max(1, math.ceil(int(quota) / int(period))))
    try:  # cgroup v1
        q = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read_text(encoding="utf-8"))
        p = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read_text(encoding="utf-8"))
        if q > 0 and p > 0:
            n = min(n, max(1, math.ceil(q / p)))
    except (OSError, ValueError):
        pass
    return max(1, n)


def _linux_available() -> int | None:
    avail = None
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                avail = int(line.split()[1]) * 1024
                break
    except (OSError, ValueError):
        return None
    try:  # cgroup v2: limit minus the unreclaimable use (page cache is given back on demand)
        limit = Path("/sys/fs/cgroup/memory.max").read_text(encoding="utf-8").strip()
        stat = dict(
            line.split()[:2]
            for line in Path("/sys/fs/cgroup/memory.stat").read_text(encoding="utf-8").splitlines()
        )
        used = int(stat.get("anon", 0)) + int(stat.get("shmem", 0))
        if limit != "max" and avail is not None:
            avail = min(avail, int(limit) - used)
    except (OSError, ValueError):
        pass
    return avail


def _windows_available() -> int | None:
    import ctypes

    class _Status(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = _Status()
    status.dwLength = ctypes.sizeof(_Status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined,unused-ignore]
        return None
    return int(status.ullAvailPhys)


def available_memory_bytes() -> int | None:
    """Memory free for new allocations now, or None when the platform does not say."""
    if os.name == "nt":
        try:
            return _windows_available()
        except (OSError, AttributeError):
            return None
    avail = _linux_available()
    if avail is not None:
        return avail
    sysconf = getattr(os, "sysconf", None)  # other POSIX: physical memory as an upper bound
    if sysconf is None:
        return None
    try:
        return int(sysconf("SC_PAGE_SIZE") * sysconf("SC_PHYS_PAGES"))
    except (ValueError, OSError):
        return None


def worker_budget(
    per_worker_bytes: float,
    *,
    cap: int | None = None,
    threads_per_worker: int = 1,
    memory_fraction: float = MEMORY_FRACTION,
) -> int:
    """Pool size bounded by the CPU quota and by ``memory_fraction`` of the free memory."""
    n = max(1, cpu_quota() // max(1, threads_per_worker))
    avail = available_memory_bytes()
    if avail is not None and per_worker_bytes > 0:
        n = min(n, max(1, int(avail * memory_fraction // per_worker_bytes)))
    if cap is not None:
        n = min(n, cap)
    return max(1, n)
