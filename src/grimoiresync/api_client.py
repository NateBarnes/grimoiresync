"""Granola HTTP API client (auth token + document/panel fetch)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import requests

from . import granola_crypto

log = logging.getLogger(__name__)

_SUPABASE_PLAIN = Path.home() / "Library/Application Support/Granola/supabase.json"

_API_LIST_URL = "https://api.granola.ai/v2/get-documents"
_API_BATCH_URL = "https://api.granola.ai/v1/get-documents-batch"

# The batch endpoint rejects large ID lists with HTTP 400 (observed OK at 50,
# failing at 100). Chunk requests well under that boundary — a single oversized
# request previously 400'd and wiped out ALL panel content on bulk/force syncs.
_PANEL_BATCH_SIZE = 25

# Granola's API requires a recent-looking client identity; without it some
# endpoints reject the request. The actual app sends a richer UA string but
# this is sufficient for the JSON endpoints we use.
_HEADERS_BASE = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Granola/1.0",
}


def _read_access_token_plain(path: Path = _SUPABASE_PLAIN) -> str | None:
    """Legacy: read the access token from Granola's unencrypted supabase.json.

    Returns None when the file is missing, malformed, or holds an expired token
    from an older Granola version.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    tokens_field = raw.get("workos_tokens")
    if not tokens_field:
        return None
    try:
        tokens = json.loads(tokens_field) if isinstance(tokens_field, str) else tokens_field
        return tokens.get("access_token")
    except (json.JSONDecodeError, TypeError):
        return None


def get_access_token() -> str | None:
    """Return the freshest available WorkOS access token.

    Prefers the encrypted supabase.json.enc (current Granola); falls back to
    the plain supabase.json if encryption isn't in use yet on this install.
    """
    token = granola_crypto.load_supabase_token()
    if token:
        return token
    return _read_access_token_plain()


def _post_json(url: str, token: str, body: dict, *, timeout: int = 30) -> dict | None:
    headers = dict(_HEADERS_BASE, Authorization=f"Bearer {token}")
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException:
        log.warning("Granola API request to %s failed", url, exc_info=True)
        return None
    try:
        return resp.json()
    except ValueError:
        log.warning("Granola API response was not JSON: %s", resp.text[:200])
        return None


def list_documents() -> tuple[list[dict], set[str]] | None:
    """Fetch the full list of documents via get-documents-v2.

    Returns (documents, deleted_ids) on success, or None if the API call fails
    (caller should treat as "API path unavailable"). `documents` may be empty
    even on success when the account has no notes.
    """
    token = get_access_token()
    if not token:
        log.warning("No Granola API token available")
        return None
    data = _post_json(_API_LIST_URL, token, {})
    if data is None:
        return None
    docs = data.get("docs") or data.get("documents") or []
    deleted_raw = data.get("deleted") or []
    deleted: set[str] = set()
    for entry in deleted_raw:
        if isinstance(entry, str):
            deleted.add(entry)
        elif isinstance(entry, dict) and entry.get("id"):
            deleted.add(entry["id"])
    log.debug("API returned %d documents (%d marked deleted)", len(docs), len(deleted))
    return docs, deleted


def fetch_panels(doc_ids: list[str]) -> dict[str, dict]:
    """Batch-fetch AI panel content for the given document IDs.

    Returns a dict mapping doc_id -> {"title": str, "content"|"html"|"markdown": ...}.
    Documents without panels are omitted. IDs are fetched in chunks of
    _PANEL_BATCH_SIZE because the batch endpoint 400s on large lists; a failed
    chunk drops only its own IDs, leaving the rest of the results intact.
    """
    if not doc_ids:
        return {}

    token = get_access_token()
    if not token:
        log.warning("No Granola API token found; skipping panel fetch")
        return {}

    results: dict[str, dict] = {}
    for start in range(0, len(doc_ids), _PANEL_BATCH_SIZE):
        chunk = doc_ids[start:start + _PANEL_BATCH_SIZE]
        data = _post_json(
            _API_BATCH_URL,
            token,
            {"document_ids": chunk, "include_last_viewed_panel": True},
        )
        if data is None:
            log.warning(
                "Panel batch %d-%d of %d failed; those docs will have no panel content",
                start, start + len(chunk), len(doc_ids),
            )
            continue
        documents = data if isinstance(data, list) else data.get("docs", [])
        _extract_panels(documents, results)

    log.debug("Fetched panels for %d of %d documents", len(results), len(doc_ids))
    return results


def _extract_panels(documents: list, results: dict[str, dict]) -> None:
    """Parse one batch response, adding recovered panels to `results` in place."""
    for doc in documents:
        if not isinstance(doc, dict):
            continue
        doc_id = doc.get("id")
        if not doc_id:
            continue

        panel = doc.get("last_viewed_panel")
        if isinstance(panel, dict):
            content = panel.get("content")
            title = panel.get("title", "Summary")
            if content and isinstance(content, dict):
                results[doc_id] = {"title": title, "content": content}
                continue
            if content and isinstance(content, str):
                results[doc_id] = {"title": title, "html": content}
                continue

        notes_md = doc.get("notes_markdown")
        if notes_md and isinstance(notes_md, str):
            results[doc_id] = {"title": "Summary", "markdown": notes_md}
            continue

        log.debug("No panel content for doc %s (%s)", doc.get("title", "?"), doc_id)
