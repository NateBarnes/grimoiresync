"""Orchestrator: fetch docs (API or cache) -> render -> wikify -> write."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from .api_client import fetch_panels, list_documents
from .cache_parser import parse_api_documents, parse_cache
from .config import Config
from .health import get_monitor
from .models import GranolaDocument
from .note_writer import assemble_note, make_filename, write_note
from .sync_state import SyncState
from .wikilinks import inject_wikilinks, scan_vault_terms

log = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """Result of one run_sync pass. Health checks consume the extra fields."""

    written: int = 0
    documents: list[GranolaDocument] = field(default_factory=list)
    source: str | None = None
    fetched_was_none: bool = False

    # Keep `assert run_sync(...) == N` working for callers that only care about
    # the written count (notably existing tests and any external CLI scripts).
    def __eq__(self, other: object) -> bool:
        if isinstance(other, SyncResult):
            return (
                self.written == other.written
                and self.documents == other.documents
                and self.source == other.source
                and self.fetched_was_none == other.fetched_was_none
            )
        if isinstance(other, int):
            return self.written == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self.written, self.source, self.fetched_was_none))

    def __int__(self) -> int:
        return self.written

    def __bool__(self) -> bool:
        return self.written > 0


def find_note_by_granola_id(vault_path: Path, granola_id: str) -> Path | None:
    """Search the vault for a markdown file containing a specific granola_id."""
    needle = f"granola_id | {granola_id}"
    for md_file in vault_path.rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
            if needle in content:
                return md_file
        except OSError:
            continue
    return None


def _fetch_via_api(state: SyncState) -> tuple[list[GranolaDocument], list[str]] | None:
    """Fetch the document list from the API and parse into GranolaDocuments.

    Returns (all_documents, to_sync_ids) or None when the API path is
    unavailable so the caller can fall back to the local cache.
    """
    result = list_documents()
    if result is None:
        return None
    raw_docs, _deleted = result

    documents_initial = parse_api_documents(raw_docs)
    to_sync_ids = [d.id for d in documents_initial if state.needs_sync(d.id, d.updated_at)]
    if not to_sync_ids:
        return documents_initial, []

    api_panels = fetch_panels(to_sync_ids)
    documents = parse_api_documents(raw_docs, api_panels=api_panels)
    return documents, to_sync_ids


def _fetch_via_cache(
    cache_path: Path, state: SyncState
) -> tuple[list[GranolaDocument], list[str]] | None:
    """Legacy path for older Granola installs that still write plain JSON."""
    if not cache_path.exists():
        return None
    documents_initial = parse_cache(cache_path)
    if not documents_initial:
        return None
    to_sync_ids = [d.id for d in documents_initial if state.needs_sync(d.id, d.updated_at)]
    if not to_sync_ids:
        return documents_initial, []
    api_panels = fetch_panels(to_sync_ids)
    documents = parse_cache(cache_path, api_panels=api_panels)
    return documents, to_sync_ids


def run_sync(
    config: Config,
    state: SyncState,
    *,
    dry_run: bool = False,
) -> SyncResult:
    """Run a single sync pass. Returns a SyncResult with metrics for health checks."""
    fetched = _fetch_via_api(state)
    source: str | None = "API"
    if fetched is None or not fetched[0]:
        # API unavailable or returned nothing — try the legacy local cache.
        fetched = _fetch_via_cache(config.granola_cache_path, state)
        source = "cache"
    if fetched is None:
        log.warning(
            "Could not fetch documents via API or local cache (%s)",
            config.granola_cache_path,
        )
        return SyncResult(written=0, documents=[], source=None, fetched_was_none=True)

    documents, to_sync_ids = fetched
    if not to_sync_ids:
        log.debug("All %d documents are up to date (source=%s)", len(documents), source)
        return SyncResult(written=0, documents=documents, source=source)

    log.debug(
        "%d of %d documents need syncing (source=%s)",
        len(to_sync_ids), len(documents), source,
    )

    to_sync_set = set(to_sync_ids)
    to_sync = [doc for doc in documents if doc.id in to_sync_set]

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

            if old_stored_path:
                if "/" in old_stored_path or "\\" in old_stored_path:
                    old_abs = config.vault_path / old_stored_path
                else:
                    old_abs = config.notes_dir / old_stored_path
            else:
                old_abs = None

            expected_path = config.notes_dir / new_filename

            if expected_path.exists():
                target_dir = config.notes_dir
            elif old_abs and old_abs.exists():
                target_dir = old_abs.parent
                if old_abs.name != new_filename and not dry_run:
                    old_abs.unlink()
                    log.info("Removed renamed file: %s", old_abs)
            elif old_stored_path:
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
                get_monitor().record_doc_write_success(doc.id)

            written += 1

        except Exception as exc:
            if not dry_run:
                get_monitor().record_doc_write_failure(doc.id, doc.title, str(exc))
            log.error("Failed to sync document %s (%s)", doc.id, doc.title, exc_info=True)

    log.info("Sync complete: %d notes written (source=%s)", written, source)
    return SyncResult(written=written, documents=documents, source=source)
