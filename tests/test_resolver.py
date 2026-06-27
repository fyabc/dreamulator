"""Tests for layer resolver."""

import pytest

from dreamulator.branch_manager import BranchManager
from dreamulator.models.layers import Layer
from dreamulator.resolver import LayerResolver


class TestLayerResolverRoot:
    def test_resolve_layer_with_data(self, tmp_path):
        # Create layer input structure
        astronomy_input = tmp_path / "layers" / "astronomy" / "input"
        astronomy_input.mkdir(parents=True)
        (astronomy_input / "stellar.yaml").write_text("name: test", encoding="utf-8")

        resolver = LayerResolver(tmp_path)
        source = resolver.resolve_layer(Layer.ASTRONOMY)

        assert source.input_dir == astronomy_input
        assert source.source == "root"

    def test_resolve_layer_without_data(self, tmp_path):
        resolver = LayerResolver(tmp_path)
        source = resolver.resolve_layer(Layer.PHYSICS)

        assert source.input_dir is None
        assert source.source == "not configured"

    def test_resolve_all_layers(self, tmp_path):
        # Create some layer data
        astronomy_input = tmp_path / "layers" / "astronomy" / "input"
        astronomy_input.mkdir(parents=True)
        (astronomy_input / "stellar.yaml").write_text("name: test", encoding="utf-8")

        resolver = LayerResolver(tmp_path)
        sources = resolver.resolve_all_layers()

        assert len(sources) == len(Layer)
        assert sources[Layer.ASTRONOMY].source == "root"
        assert sources[Layer.PHYSICS].source == "not configured"

    def test_get_input_dir(self, tmp_path):
        astronomy_input = tmp_path / "layers" / "astronomy" / "input"
        astronomy_input.mkdir(parents=True)
        (astronomy_input / "stellar.yaml").write_text("name: test", encoding="utf-8")

        resolver = LayerResolver(tmp_path)
        assert resolver.get_input_dir(Layer.ASTRONOMY) == astronomy_input
        assert resolver.get_input_dir(Layer.PHYSICS) is None

    def test_get_fork_layer_root(self, tmp_path):
        resolver = LayerResolver(tmp_path)
        assert resolver.get_fork_layer() is None


class TestLayerResolverBranch:
    def test_resolve_branch_layer(self, tmp_path):
        # Set up root world with astronomy data
        root_astronomy = tmp_path / "layers" / "astronomy" / "input"
        root_astronomy.mkdir(parents=True)
        (root_astronomy / "stellar.yaml").write_text("name: root", encoding="utf-8")

        # Create a branch
        branch_mgr = BranchManager(tmp_path)
        branch_mgr.create_branch("pangea", Layer.GEOLOGICAL)

        # Add geological data to branch
        branch_geo = tmp_path / "branches" / "pangea" / "layers" / "geological" / "input"
        (branch_geo / "plates.yaml").write_text("plates: []", encoding="utf-8")

        resolver = LayerResolver(tmp_path, "pangea")

        # Astronomy should come from root
        astronomy_source = resolver.resolve_layer(Layer.ASTRONOMY)
        assert astronomy_source.source == "root"
        assert astronomy_source.input_dir == root_astronomy

        # Geological should come from branch
        geo_source = resolver.resolve_layer(Layer.GEOLOGICAL)
        assert geo_source.source == "branch:pangea"
        assert geo_source.input_dir == branch_geo

    def test_branch_inherits_parent_layers(self, tmp_path):
        # Set up root with astronomy data
        root_astronomy = tmp_path / "layers" / "astronomy" / "input"
        root_astronomy.mkdir(parents=True)
        (root_astronomy / "stellar.yaml").write_text("name: root", encoding="utf-8")

        # Create a branch at geological layer
        branch_mgr = BranchManager(tmp_path)
        branch_mgr.create_branch("pangea", Layer.GEOLOGICAL)

        resolver = LayerResolver(tmp_path, "pangea")

        # Layers before fork should be inherited from root
        sources = resolver.resolve_all_layers()
        assert sources[Layer.ASTRONOMY].source == "root"
        assert sources[Layer.PHYSICS].source == "not configured"  # No data anywhere

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


class TestLayerResolverInherit:
    """Tests for _inherit: true branch data merge."""

    def _setup_branch(self, tmp_path, root_yaml: str, branch_yaml: str):
        """Helper: create root + branch astronomy/input/stellar.yaml."""
        root_input = tmp_path / "layers" / "astronomy" / "input"
        root_input.mkdir(parents=True)
        (root_input / "stellar.yaml").write_text(root_yaml, encoding="utf-8")

        branch_mgr = BranchManager(tmp_path)
        branch_mgr.create_branch("test_branch", Layer.ASTRONOMY)

        branch_input = (
            tmp_path / "branches" / "test_branch" / "layers" / "astronomy" / "input"
        )
        branch_input.mkdir(parents=True, exist_ok=True)
        (branch_input / "stellar.yaml").write_text(branch_yaml, encoding="utf-8")

    def test_no_inherit_returns_branch_only(self, tmp_path):
        self._setup_branch(
            tmp_path,
            root_yaml="stars:\n  - id: star_a\n    name: Alpha\n",
            branch_yaml="stars:\n  - id: star_b\n    name: Beta\n",
        )
        resolver = LayerResolver(tmp_path, "test_branch")
        data = resolver.load_layer_yaml("astronomy", "stellar.yaml")

        assert len(data["stars"]) == 1
        assert data["stars"][0]["id"] == "star_b"

    def test_inherit_merges_lists(self, tmp_path):
        self._setup_branch(
            tmp_path,
            root_yaml=(
                "stars:\n"
                "  - id: star_a\n"
                "    name: Alpha\n"
                "bodies:\n"
                "  - id: body_x\n"
                "    name: X\n"
            ),
            branch_yaml=(
                "_inherit: true\n"
                "bodies:\n"
                "  - id: body_y\n"
                "    name: Y\n"
            ),
        )
        resolver = LayerResolver(tmp_path, "test_branch")
        data = resolver.load_layer_yaml("astronomy", "stellar.yaml")

        # Stars inherited from root
        assert len(data["stars"]) == 1
        assert data["stars"][0]["id"] == "star_a"
        # Bodies merged: root's body_x + branch's body_y
        assert len(data["bodies"]) == 2
        ids = {b["id"] for b in data["bodies"]}
        assert ids == {"body_x", "body_y"}

    def test_inherit_override_by_id(self, tmp_path):
        self._setup_branch(
            tmp_path,
            root_yaml="bodies:\n  - id: body_x\n    name: Original\n    mass: 1.0\n",
            branch_yaml=(
                "_inherit: true\n"
                "bodies:\n"
                "  - id: body_x\n"
                "    name: Overridden\n"
                "    mass: 2.0\n"
            ),
        )
        resolver = LayerResolver(tmp_path, "test_branch")
        data = resolver.load_layer_yaml("astronomy", "stellar.yaml")

        assert len(data["bodies"]) == 1
        assert data["bodies"][0]["name"] == "Overridden"
        assert data["bodies"][0]["mass"] == 2.0

    def test_inherit_scalar_override(self, tmp_path):
        self._setup_branch(
            tmp_path,
            root_yaml="name: Root System\ncount: 5\n",
            branch_yaml="_inherit: true\nname: Branch System\n",
        )
        resolver = LayerResolver(tmp_path, "test_branch")
        data = resolver.load_layer_yaml("astronomy", "stellar.yaml")

        assert data["name"] == "Branch System"
        assert data["count"] == 5  # inherited

    def test_inherit_missing_parent_file(self, tmp_path):
        # Root has no stellar.yaml, only branch has it
        branch_mgr = BranchManager(tmp_path)
        branch_mgr.create_branch("test_branch", Layer.ASTRONOMY)

        branch_input = (
            tmp_path / "branches" / "test_branch" / "layers" / "astronomy" / "input"
        )
        branch_input.mkdir(parents=True, exist_ok=True)
        (branch_input / "stellar.yaml").write_text(
            "_inherit: true\nstars:\n  - id: star_a\n    name: Alpha\n",
            encoding="utf-8",
        )

        resolver = LayerResolver(tmp_path, "test_branch")
        data = resolver.load_layer_yaml("astronomy", "stellar.yaml")

        assert data is not None
        assert len(data["stars"]) == 1
        assert "_inherit" not in data

    def test_inherit_strips_key(self, tmp_path):
        self._setup_branch(
            tmp_path,
            root_yaml="name: Root\n",
            branch_yaml="_inherit: true\nextra: value\n",
        )
        resolver = LayerResolver(tmp_path, "test_branch")
        data = resolver.load_layer_yaml("astronomy", "stellar.yaml")

        assert "_inherit" not in data
        assert data["name"] == "Root"
        assert data["extra"] == "value"

    def test_no_file_returns_none(self, tmp_path):
        resolver = LayerResolver(tmp_path)
        data = resolver.load_layer_yaml("astronomy", "stellar.yaml")
        assert data is None

    def test_merge_by_body_id(self, tmp_path):
        """body_id (used by orbits) is also recognized as an ID key."""
        self._setup_branch(
            tmp_path,
            root_yaml=(
                "orbits:\n"
                "  - body_id: planet_a\n"
                "    parent_id: star\n"
                "    semi_major_axis_au: 1.0\n"
            ),
            branch_yaml=(
                "_inherit: true\n"
                "orbits:\n"
                "  - body_id: planet_b\n"
                "    parent_id: star\n"
                "    semi_major_axis_au: 2.0\n"
            ),
        )
        resolver = LayerResolver(tmp_path, "test_branch")
        data = resolver.load_layer_yaml("astronomy", "stellar.yaml")

        assert len(data["orbits"]) == 2
        ids = {o["body_id"] for o in data["orbits"]}
        assert ids == {"planet_a", "planet_b"}
