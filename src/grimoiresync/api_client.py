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

    results: dict[str, dict] = {}
    documents = data if isinstance(data, list) else data.get("docs", [])

    for doc in documents:
        if not isinstance(doc, dict):
            continue
        doc_id = doc.get("id")
        if not doc_id:
            continue
        panel = doc.get("last_viewed_panel")
        if not panel or not isinstance(panel, dict):
            continue
        content = panel.get("content")
        if content and isinstance(content, dict):
            title = panel.get("title", "Summary")
            results[doc_id] = {"title": title, "content": content}

    log.debug("Fetched panels for %d of %d documents", len(results), len(doc_ids))
    return results
