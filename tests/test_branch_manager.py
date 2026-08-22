"""Tests for branch manager."""

import pytest

from dreamulator.branch_manager import BranchManager
from dreamulator.models.layers import Layer


class TestBranchManager:
    def test_create_branch(self, tmp_path):
        mgr = BranchManager(tmp_path)
        branch_dir = mgr.create_branch("pangea", Layer.GEOLOGICAL)

        assert branch_dir.exists()
        assert (branch_dir / "branch.yaml").exists()
        assert (branch_dir / "layers" / "geological" / "input").exists()
        assert (branch_dir / "layers" / "climate" / "input").exists()
        assert (branch_dir / "layers" / "civilization" / "input").exists()

    def test_create_branch_pre_fork_layers_not_created(self, tmp_path):
        mgr = BranchManager(tmp_path)
        branch_dir = mgr.create_branch("alt_astronomy", Layer.ASTRONOMY)

        # Layers before fork should not exist
        assert not (branch_dir / "layers" / "physics").exists()
        assert not (branch_dir / "layers" / "chemistry").exists()
        # Fork layer and after should exist
        assert (branch_dir / "layers" / "astronomy").exists()
        assert (branch_dir / "layers" / "geological").exists()

    def test_create_duplicate_branch_fails(self, tmp_path):
        mgr = BranchManager(tmp_path)
        mgr.create_branch("pangea", Layer.GEOLOGICAL)

        with pytest.raises(FileExistsError):
            mgr.create_branch("pangea", Layer.CLIMATE)

    def test_list_branches(self, tmp_path):
        mgr = BranchManager(tmp_path)
        assert mgr.list_branches() == []

        mgr.create_branch("pangea", Layer.GEOLOGICAL)
        mgr.create_branch("ice_age", Layer.CLIMATE)

        branches = mgr.list_branches()
        assert len(branches) == 2
        names = {b.name for b in branches}
        assert "pangea" in names
        assert "ice_age" in names

    def test_get_branch(self, tmp_path):
        mgr = BranchManager(tmp_path)
        mgr.create_branch("pangea", Layer.GEOLOGICAL, description="Test branch")

        metadata = mgr.get_branch("pangea")
        assert metadata.name == "pangea"
        assert metadata.fork_layer == Layer.GEOLOGICAL
        assert metadata.description == "Test branch"

    def test_get_branch_not_found(self, tmp_path):
        mgr = BranchManager(tmp_path)
        with pytest.raises(FileNotFoundError):
            mgr.get_branch("nonexistent")

    def test_delete_branch(self, tmp_path):
        mgr = BranchManager(tmp_path)
        mgr.create_branch("pangea", Layer.GEOLOGICAL)
        assert len(mgr.list_branches()) == 1

        mgr.delete_branch("pangea")
        assert len(mgr.list_branches()) == 0

    def test_promote_branch(self, tmp_path):
        mgr = BranchManager(tmp_path)
        mgr.create_branch("pangea", Layer.GEOLOGICAL)

        new_dir = mgr.promote_branch("pangea")
        assert new_dir.exists()
        assert (new_dir / "branch.yaml").exists()
        assert not (tmp_path / "branches" / "pangea").exists()

    def test_branch_dir(self, tmp_path):
        mgr = BranchManager(tmp_path)
        mgr.create_branch("pangea", Layer.GEOLOGICAL)

        branch_dir = mgr.branch_dir("pangea")
        assert branch_dir.exists()

    def test_branch_dir_not_found(self, tmp_path):
        mgr = BranchManager(tmp_path)
        with pytest.raises(FileNotFoundError):
            mgr.branch_dir("nonexistent")
