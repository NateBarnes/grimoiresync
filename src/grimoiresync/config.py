"""Configuration loading and defaults."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


_DEFAULT_CACHE_PATH = Path.home() / "Library/Application Support/Granola/cache-v3.json"
_DEFAULT_CONFIG_DIR = Path.home() / ".config" / "grimoiresync"
_DEFAULT_CONFIG_PATH = _DEFAULT_CONFIG_DIR / "config.yaml"


@dataclass
class Config:
    vault_path: Path
    notes_subfolder: str = "Meetings"
    granola_cache_path: Path = field(default_factory=lambda: _DEFAULT_CACHE_PATH)
    include_panels: bool = True
    include_transcript: bool = False
    auto_wikilinks: bool = True
    min_wikilink_length: int = 3

    @property
    def notes_dir(self) -> Path:
        if self.notes_subfolder:
            return self.vault_path / self.notes_subfolder
        return self.vault_path


def load_config(config_path: Path | None = None) -> Config:
    """Load config from YAML file, falling back to defaults where possible."""
    path = config_path or _DEFAULT_CONFIG_PATH
    path = Path(path).expanduser()

    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}\n"
            f"Create one at {_DEFAULT_CONFIG_PATH} or pass --config.\n"
            f"See config.example.yaml for reference."
        )

    raw = yaml.safe_load(path.read_text())
    if not raw or not isinstance(raw, dict):
        raise ValueError(f"Invalid config file: {path}")

    if "vault_path" not in raw:
        raise ValueError("'vault_path' is required in config")

    vault_path = Path(raw["vault_path"]).expanduser()

    kwargs: dict = {"vault_path": vault_path}
    if "notes_subfolder" in raw:
        kwargs["notes_subfolder"] = raw["notes_subfolder"]
    if "granola_cache_path" in raw:
        kwargs["granola_cache_path"] = Path(raw["granola_cache_path"]).expanduser()
    for key in (
        "include_panels",
        "include_transcript",
        "auto_wikilinks",
        "min_wikilink_length",
    ):
        if key in raw:
            kwargs[key] = raw[key]

    return Config(**kwargs)
