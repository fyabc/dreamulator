"""Process-pool budgets from the CPU quota and the free memory."""

from __future__ import annotations

import pytest

from dreamulator.utils import resources


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


@pytest.mark.parametrize("available_gib", [8, 0, -1])
@pytest.mark.parametrize("requested", [None, 1, 4])
def test_single_worker_must_fit_before_a_pool_can_start(
    monkeypatch: pytest.MonkeyPatch, available_gib: int, requested: int | None
) -> None:
    monkeypatch.setattr(resources, "available_memory_bytes", lambda: available_gib * 2**30)
    with pytest.raises(MemoryError, match="Insufficient memory"):
        resources.worker_budget(9 * 2**30, requested_workers=requested)


def test_requested_pool_has_the_same_memory_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resources, "available_memory_bytes", lambda: 32 * 2**30)
    assert resources.worker_budget(9 * 2**30, requested_workers=1) == 1
    with pytest.raises(MemoryError, match=r"At most 1 worker\(s\) fit"):
        resources.worker_budget(9 * 2**30, requested_workers=2)
    # More requested workers than tasks do not make the real pool larger.
    assert resources.worker_budget(9 * 2**30, requested_workers=16, cap=1) == 1


def test_exact_memory_boundary_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resources, "available_memory_bytes", lambda: 36 * 2**30)
    assert resources.worker_budget(9 * 2**30, requested_workers=2) == 2


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
