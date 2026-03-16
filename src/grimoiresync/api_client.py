"""Fetch AI panel content from the Granola API."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import requests

log = logging.getLogger(__name__)

_SUPABASE_PATH = Path.home() / "Library/Application Support/Granola/supabase.json"
_API_URL = "https://api.granola.ai/v1/get-documents-batch"


def _read_access_token(path: Path = _SUPABASE_PATH) -> str | None:
    """Read the WorkOS access token from Granola's supabase.json."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        workos_str = raw.get("workos_tokens")
        if not workos_str:
            return None
        workos = json.loads(workos_str) if isinstance(workos_str, str) else workos_str
        return workos.get("access_token")
    except Exception:
        log.debug("Failed to read access token from %s", path, exc_info=True)
        return None


def fetch_panels(doc_ids: list[str]) -> dict[str, dict]:
    """Batch-fetch AI panel content for the given document IDs.

    Returns a dict mapping doc_id -> ProseMirror content dict for documents
    that have panel data. Documents without panels are omitted.
    """
    if not doc_ids:
        return {}

    token = _read_access_token()
    if not token:
        log.warning("No Granola API token found; skipping panel fetch")
        return {}

    try:
        resp = requests.post(
            _API_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "document_ids": doc_ids,
                "include_last_viewed_panel": True,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        log.warning("Granola API request failed; falling back to local cache", exc_info=True)
        return {}

    documents = data if isinstance(data, list) else data.get("docs", [])

    results: dict[str, dict] = {}

    for doc in documents:
        if not isinstance(doc, dict):
            continue
        doc_id = doc.get("id")
        if not doc_id:
            continue

        # Primary: last_viewed_panel
        panel = doc.get("last_viewed_panel")
        if isinstance(panel, dict):
            content = panel.get("content")
            title = panel.get("title", "Summary")
            if content and isinstance(content, dict):
                # ProseMirror JSON
                results[doc_id] = {"title": title, "content": content}
                continue
            if content and isinstance(content, str):
                # HTML string
                results[doc_id] = {"title": title, "html": content}
                continue

        # Fallback: notes_markdown from the API response
        notes_md = doc.get("notes_markdown")
        if notes_md and isinstance(notes_md, str):
            results[doc_id] = {"title": "Summary", "markdown": notes_md}
            continue

        log.debug("No panel content for doc %s (%s)", doc.get("title", "?"), doc_id)

    log.debug("Fetched panels for %d of %d documents", len(results), len(doc_ids))
    return results
