"""Tests for branch models."""

from dreamulator.models.branch import BranchMetadata
from dreamulator.models.layers import Layer


class TestBranchMetadata:
    def test_default_values(self):
        branch = BranchMetadata(name="test")
        assert branch.name == "test"
        assert branch.parent is None
        assert branch.fork_layer is None
        assert branch.description == ""
        assert branch.tags == []

    def test_with_all_fields(self):
        branch = BranchMetadata(
            name="pangea",
            parent=None,
            fork_layer=Layer.GEOLOGICAL,
            description="Earth with Pangea supercontinent",
            tags=["geology", "supercontinent"],
        )
        assert branch.name == "pangea"
        assert branch.fork_layer == Layer.GEOLOGICAL
        assert len(branch.tags) == 2

    def test_is_root(self):
        root = BranchMetadata(name="root", parent=None)
        assert root.is_root() is True
        assert root.is_branch() is False

    def test_is_branch(self):
        branch = BranchMetadata(name="pangea", parent="root")
        assert branch.is_branch() is True
        assert branch.is_root() is False

    def test_serialization(self):
        branch = BranchMetadata(
            name="test",
            fork_layer=Layer.ASTRONOMY,
        )
        json_str = branch.model_dump_json()
        restored = BranchMetadata.model_validate_json(json_str)
        assert restored.name == branch.name
        assert restored.fork_layer == branch.fork_layer
