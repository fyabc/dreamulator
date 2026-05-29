"""Tests for layer resolver."""

import pytest

from dreamulator.branch_manager import BranchManager
from dreamulator.models.layers import Layer
from dreamulator.resolver import LayerResolver


class TestLayerResolverRoot:
    def test_resolve_layer_with_data(self, tmp_path):
        # Create layer input structure
        stellar_input = tmp_path / "layers" / "stellar" / "input"
        stellar_input.mkdir(parents=True)
        (stellar_input / "stellar.yaml").write_text("name: test", encoding="utf-8")

        resolver = LayerResolver(tmp_path)
        source = resolver.resolve_layer(Layer.STELLAR)

        assert source.input_dir == stellar_input
        assert source.source == "root"

    def test_resolve_layer_without_data(self, tmp_path):
        resolver = LayerResolver(tmp_path)
        source = resolver.resolve_layer(Layer.PHYSICS)

        assert source.input_dir is None
        assert source.source == "not configured"

    def test_resolve_all_layers(self, tmp_path):
        # Create some layer data
        stellar_input = tmp_path / "layers" / "stellar" / "input"
        stellar_input.mkdir(parents=True)
        (stellar_input / "stellar.yaml").write_text("name: test", encoding="utf-8")

        resolver = LayerResolver(tmp_path)
        sources = resolver.resolve_all_layers()

        assert len(sources) == len(Layer)
        assert sources[Layer.STELLAR].source == "root"
        assert sources[Layer.PHYSICS].source == "not configured"

    def test_get_input_dir(self, tmp_path):
        stellar_input = tmp_path / "layers" / "stellar" / "input"
        stellar_input.mkdir(parents=True)
        (stellar_input / "stellar.yaml").write_text("name: test", encoding="utf-8")

        resolver = LayerResolver(tmp_path)
        assert resolver.get_input_dir(Layer.STELLAR) == stellar_input
        assert resolver.get_input_dir(Layer.PHYSICS) is None

    def test_get_fork_layer_root(self, tmp_path):
        resolver = LayerResolver(tmp_path)
        assert resolver.get_fork_layer() is None


class TestLayerResolverBranch:
    def test_resolve_branch_layer(self, tmp_path):
        # Set up root world with stellar data
        root_stellar = tmp_path / "layers" / "stellar" / "input"
        root_stellar.mkdir(parents=True)
        (root_stellar / "stellar.yaml").write_text("name: root", encoding="utf-8")

        # Create a branch
        branch_mgr = BranchManager(tmp_path)
        branch_mgr.create_branch("pangea", Layer.GEOLOGICAL)

        # Add geological data to branch
        branch_geo = tmp_path / "branches" / "pangea" / "layers" / "geological" / "input"
        (branch_geo / "plates.yaml").write_text("plates: []", encoding="utf-8")

        resolver = LayerResolver(tmp_path, "pangea")

        # Stellar should come from root
        stellar_source = resolver.resolve_layer(Layer.STELLAR)
        assert stellar_source.source == "root"
        assert stellar_source.input_dir == root_stellar

        # Geological should come from branch
        geo_source = resolver.resolve_layer(Layer.GEOLOGICAL)
        assert geo_source.source == "branch:pangea"
        assert geo_source.input_dir == branch_geo

    def test_branch_inherits_parent_layers(self, tmp_path):
        # Set up root with stellar data
        root_stellar = tmp_path / "layers" / "stellar" / "input"
        root_stellar.mkdir(parents=True)
        (root_stellar / "stellar.yaml").write_text("name: root", encoding="utf-8")

        # Create a branch at geological layer
        branch_mgr = BranchManager(tmp_path)
        branch_mgr.create_branch("pangea", Layer.GEOLOGICAL)

        resolver = LayerResolver(tmp_path, "pangea")

        # Layers before fork should be inherited from root
        sources = resolver.resolve_all_layers()
        assert sources[Layer.STELLAR].source == "root"
        assert sources[Layer.ORBITAL].source == "not configured"  # No data anywhere

    def test_get_branch_metadata(self, tmp_path):
        branch_mgr = BranchManager(tmp_path)
        branch_mgr.create_branch("pangea", Layer.GEOLOGICAL, description="Test")

        resolver = LayerResolver(tmp_path, "pangea")
        metadata = resolver.get_branch_metadata()

        assert metadata is not None
        assert metadata.name == "pangea"
        assert metadata.fork_layer == Layer.GEOLOGICAL

    def test_get_fork_layer(self, tmp_path):
        branch_mgr = BranchManager(tmp_path)
        branch_mgr.create_branch("pangea", Layer.GEOLOGICAL)

        resolver = LayerResolver(tmp_path, "pangea")
        assert resolver.get_fork_layer() == Layer.GEOLOGICAL

    def test_branch_not_found(self, tmp_path):
        resolver = LayerResolver(tmp_path, "nonexistent")
        with pytest.raises(FileNotFoundError):
            resolver.resolve_all_layers()
