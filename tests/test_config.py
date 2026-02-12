"""Tests for grimoiresync.config — Config dataclass and load_config()."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from grimoiresync.config import Config, _DEFAULT_CONFIG_PATH, load_config


class TestConfig:
    def test_notes_dir_with_subfolder(self):
        cfg = Config(vault_path=Path("/vault"), notes_subfolder="Meetings")
        assert cfg.notes_dir == Path("/vault/Meetings")

    def test_notes_dir_empty_subfolder(self):
        cfg = Config(vault_path=Path("/vault"), notes_subfolder="")
        assert cfg.notes_dir == Path("/vault")

    def test_defaults(self):
        cfg = Config(vault_path=Path("/vault"))
        assert cfg.notes_subfolder == "Meetings"
        assert cfg.include_panels is True
        assert cfg.include_transcript is False
        assert cfg.auto_wikilinks is True
        assert cfg.min_wikilink_length == 3


class TestLoadConfig:
    def test_minimal_yaml(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("vault_path: /my/vault\n")
        cfg = load_config(cfg_file)
        assert cfg.vault_path == Path("/my/vault")
        assert cfg.notes_subfolder == "Meetings"
        assert cfg.include_panels is True

    def test_full_yaml(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "vault_path: /vault\n"
            "notes_subfolder: Notes\n"
            "granola_cache_path: /custom/cache.json\n"
            "include_panels: false\n"
            "include_transcript: true\n"
            "auto_wikilinks: false\n"
            "min_wikilink_length: 5\n"
        )
        cfg = load_config(cfg_file)
        assert cfg.vault_path == Path("/vault")
        assert cfg.notes_subfolder == "Notes"
        assert cfg.granola_cache_path == Path("/custom/cache.json")
        assert cfg.include_panels is False
        assert cfg.include_transcript is True
        assert cfg.auto_wikilinks is False
        assert cfg.min_wikilink_length == 5

    def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nonexistent.yaml")

    def test_yaml_returns_none(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("")  # safe_load returns None
        with pytest.raises(ValueError, match="Invalid config"):
            load_config(cfg_file)

    def test_yaml_returns_non_dict(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("- item1\n- item2\n")
        with pytest.raises(ValueError, match="Invalid config"):
            load_config(cfg_file)

    def test_missing_vault_path(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("notes_subfolder: Notes\n")
        with pytest.raises(ValueError, match="vault_path.*required"):
            load_config(cfg_file)

    def test_config_path_none_uses_default(self):
        with patch.object(Path, "exists", return_value=False):
            with pytest.raises(FileNotFoundError):
                load_config(None)

    def test_granola_cache_path_expanduser(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "vault_path: /vault\n"
            "granola_cache_path: ~/cache.json\n"
        )
        cfg = load_config(cfg_file)
        assert "~" not in str(cfg.granola_cache_path)

    def test_optional_field_overrides(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "vault_path: /vault\n"
            "notes_subfolder: Custom\n"
            "include_panels: false\n"
            "include_transcript: true\n"
            "auto_wikilinks: false\n"
            "min_wikilink_length: 7\n"
        )
        cfg = load_config(cfg_file)
        assert cfg.notes_subfolder == "Custom"
        assert cfg.include_panels is False
        assert cfg.include_transcript is True
        assert cfg.auto_wikilinks is False
        assert cfg.min_wikilink_length == 7
