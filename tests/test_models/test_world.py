"""Tests for world manager."""

import pytest

from dreamulator.world_manager import WorldManager


class TestWorldManager:
    def test_create_and_list_world(self, tmp_worlds_dir):
        mgr = WorldManager(worlds_dir=tmp_worlds_dir)

        # Create a world using the earthlike template
        world_dir = mgr.create_world("test_world", template="earthlike", seed=42)
        assert world_dir.exists()
        assert (world_dir / "world.yaml").exists()
        assert (world_dir / "layers").exists()
        assert (world_dir / "layers" / "stellar" / "input").exists()

        # List should contain the world
        worlds = mgr.list_worlds()
        assert "test_world" in worlds

    def test_create_duplicate_fails(self, tmp_worlds_dir):
        mgr = WorldManager(worlds_dir=tmp_worlds_dir)
        mgr.create_world("test_world", template="earthlike")

        with pytest.raises(FileExistsError):
            mgr.create_world("test_world", template="earthlike")

    def test_load_world(self, tmp_worlds_dir):
        mgr = WorldManager(worlds_dir=tmp_worlds_dir)
        mgr.create_world("test_world", template="earthlike", seed=42)

        config = mgr.load_world("test_world")
        assert config.metadata.name == "test_world"
        assert config.seed.seed == 42
        assert "stellar" in config.layers
        assert config.layers["stellar"].configured is True

    def test_delete_world(self, tmp_worlds_dir):
        mgr = WorldManager(worlds_dir=tmp_worlds_dir)
        mgr.create_world("test_world", template="earthlike")
        assert "test_world" in mgr.list_worlds()

        mgr.delete_world("test_world")
        assert "test_world" not in mgr.list_worlds()

    def test_validate_world(self, tmp_worlds_dir):
        mgr = WorldManager(worlds_dir=tmp_worlds_dir)
        mgr.create_world("test_world", template="earthlike")

        errors = mgr.validate_world("test_world")
        assert len(errors) == 0

    def test_invalid_template(self, tmp_worlds_dir):
        mgr = WorldManager(worlds_dir=tmp_worlds_dir)

        with pytest.raises(FileNotFoundError, match="Template"):
            mgr.create_world("test_world", template="nonexistent")
