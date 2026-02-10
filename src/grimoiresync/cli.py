"""Command-line interface for GrimoireSync."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import load_config
from .sync_engine import run_sync
from .sync_state import SyncState
from .watcher import watch


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="grimoiresync",
        description="Sync Granola meeting notes to Obsidian with auto-wikilinks",
    )
    parser.add_argument(
        "--config", "-c",
        type=Path,
        default=None,
        help="Path to config YAML (default: ~/.config/grimoiresync/config.yaml)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single sync pass and exit (no daemon)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be written without writing files",
    )

    args = parser.parse_args(argv)

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1) from None

    state = SyncState()

    if args.once:
        written = run_sync(config, state, dry_run=args.dry_run)
        if written:
            print(f"Synced {written} note(s)")
        else:
            print("Everything up to date")
    else:
        watch(config, state, dry_run=args.dry_run)
