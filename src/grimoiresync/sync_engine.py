"""Orchestrator: parse cache -> convert -> wikify -> write."""

from __future__ import annotations

import logging
from pathlib import Path

from .cache_parser import parse_cache
from .config import Config
from .note_writer import assemble_note, make_filename, write_note
from .sync_state import SyncState
from .wikilinks import inject_wikilinks, scan_vault_terms

log = logging.getLogger(__name__)


def find_note_by_granola_id(vault_path: Path, granola_id: str) -> Path | None:
    """Search the vault for a markdown file containing a specific granola_id."""
    needle = f"granola_id: {granola_id}"
    for md_file in vault_path.rglob("*.md"):
        try:
            with md_file.open("r", encoding="utf-8") as f:
                head = f.read(1024)
            if needle in head:
                return md_file
        except OSError:
            continue
    return None


def run_sync(
    config: Config,
    state: SyncState,
    *,
    dry_run: bool = False,
) -> int:
    """Run a single sync pass. Returns the number of notes written."""
    cache_path = config.granola_cache_path
    if not cache_path.exists():
        log.warning("Granola cache not found at %s", cache_path)
        return 0

    documents = parse_cache(cache_path)
    if not documents:
        log.debug("No documents found in cache")
        return 0

    # Filter to only documents that need syncing
    to_sync = [
        doc for doc in documents if state.needs_sync(doc.id, doc.updated_at)
    ]

    if not to_sync:
        log.debug("All %d documents are up to date", len(documents))
        return 0

    log.debug("%d of %d documents need syncing", len(to_sync), len(documents))

    # Scan vault for wikilink terms (only if enabled)
    terms: dict[str, str] = {}
    if config.auto_wikilinks:
        terms = scan_vault_terms(config.vault_path, min_length=config.min_wikilink_length)

    written = 0
    for doc in to_sync:
        try:
            content = assemble_note(
                doc,
                include_panels=config.include_panels,
                include_transcript=config.include_transcript,
            )

            if config.auto_wikilinks and terms:
                content = inject_wikilinks(content, terms, min_length=config.min_wikilink_length)

            new_filename = make_filename(doc)
            old_stored_path = state.get_previous_filename(doc.id)

            # Resolve stored path to absolute (backward compat: old entries are bare filenames)
            if old_stored_path:
                if "/" in old_stored_path or "\\" in old_stored_path:
                    old_abs = config.vault_path / old_stored_path
                else:
                    old_abs = config.notes_dir / old_stored_path
            else:
                old_abs = None

            expected_path = config.notes_dir / new_filename

            # Determine where to write
            if expected_path.exists():
                target_dir = config.notes_dir
            elif old_abs and old_abs.exists():
                target_dir = old_abs.parent
                if old_abs.name != new_filename and not dry_run:
                    old_abs.unlink()
                    log.info("Removed renamed file: %s", old_abs)
            elif old_stored_path:
                # Previously synced but not at expected or stored location -> search vault
                found = find_note_by_granola_id(config.vault_path, doc.id)
                if found:
                    target_dir = found.parent
                    if found.name != new_filename and not dry_run:
                        found.unlink()
                    log.info("Found moved note at %s, updating in place", found)
                else:
                    target_dir = config.notes_dir
            else:
                target_dir = config.notes_dir

            filepath = write_note(doc, target_dir, content, dry_run=dry_run)

            if not dry_run:
                rel_path = str(filepath.relative_to(config.vault_path))
                state.record_sync(doc.id, doc.updated_at, rel_path)

            written += 1

        except Exception:
            log.error("Failed to sync document %s (%s)", doc.id, doc.title, exc_info=True)

    log.info("Sync complete: %d notes written", written)
    return written
