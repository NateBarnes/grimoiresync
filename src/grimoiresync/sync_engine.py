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
        log.info("No documents found in cache")
        return 0

    # Filter to only documents that need syncing
    to_sync = [
        doc for doc in documents if state.needs_sync(doc.id, doc.updated_at)
    ]

    if not to_sync:
        log.info("All %d documents are up to date", len(documents))
        return 0

    log.info("%d of %d documents need syncing", len(to_sync), len(documents))

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

            # Handle renames: if the filename changed, remove the old file
            new_filename = make_filename(doc)
            old_filename = state.get_previous_filename(doc.id)
            if old_filename and old_filename != new_filename and not dry_run:
                old_path = config.notes_dir / old_filename
                if old_path.exists():
                    old_path.unlink()
                    log.info("Removed renamed file: %s", old_path)

            filepath = write_note(doc, config.notes_dir, content, dry_run=dry_run)

            if not dry_run:
                state.record_sync(doc.id, doc.updated_at, filepath.name)

            written += 1

        except Exception:
            log.error("Failed to sync document %s (%s)", doc.id, doc.title, exc_info=True)

    log.info("Sync complete: %d notes written", written)
    return written
