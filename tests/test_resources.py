"""Process-pool budgets from the CPU quota and the free memory."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dreamulator.utils import resources

if TYPE_CHECKING:
    import pytest


def test_memory_bounds_the_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resources, "cpu_quota", lambda: 64)
    monkeypatch.setattr(resources, "available_memory_bytes", lambda: 32 * 2**30)
    # a Windows-class machine: 16 GiB usable for 9 GiB workers -> one process
    assert resources.worker_budget(9 * 2**30) == 1
    monkeypatch.setattr(resources, "available_memory_bytes", lambda: 1024 * 2**30)
    assert resources.worker_budget(9 * 2**30) == 56  # 512 GiB / 9 GiB
    assert resources.worker_budget(1 * 2**30) == 64  # then the CPU quota binds
    assert resources.worker_budget(1 * 2**30, cap=4) == 4
    assert resources.worker_budget(1 * 2**30, threads_per_worker=16) == 4


def test_unknown_memory_falls_back_to_the_cpu_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resources, "cpu_quota", lambda: 8)
    monkeypatch.setattr(resources, "available_memory_bytes", lambda: None)
    assert resources.worker_budget(9 * 2**30) == 8


def test_cgroup_quota_caps_the_cpus(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    real = resources.Path

    def fake(p: str):  # type: ignore[no-untyped-def]
        if p == "/sys/fs/cgroup/cpu.max":
            f = tmp_path / "cpu.max"
            f.write_text("400000 100000\n", encoding="utf-8")
            return f
        return real(p)

    monkeypatch.setattr(resources, "Path", fake)
    assert resources.cpu_quota() <= 4
