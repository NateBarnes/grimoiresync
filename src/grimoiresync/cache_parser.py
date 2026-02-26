"""Parse Granola's double-encoded JSON cache file."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .models import Attendee, DocumentPanel, GranolaDocument, TranscriptEntry

log = logging.getLogger(__name__)


def parse_cache(cache_path: Path) -> list[GranolaDocument]:
    """Parse the Granola cache file and return a list of documents."""
    raw_text = cache_path.read_text(encoding="utf-8")
    outer = json.loads(raw_text)

    # Double-encoded: outer["cache"] is a JSON string
    inner_str = outer.get("cache", "{}")
    inner = json.loads(inner_str) if isinstance(inner_str, str) else inner_str

    state = inner.get("state", {})
    documents = state.get("documents", {})
    meetings_meta = state.get("meetingsMetadata", {})
    transcripts = state.get("transcripts", {})
    document_panels = state.get("documentPanels", {})
    chat_context = state.get("multiChatState", {}).get("chatContext", {})

    results: list[GranolaDocument] = []

    for doc_id, doc in documents.items():
        # Skip deleted documents
        if doc.get("deleted_at"):
            continue
        try:
            granola_doc = _parse_document(
                doc_id, doc, meetings_meta, transcripts, document_panels,
                chat_context,
            )
            results.append(granola_doc)
        except Exception:
            log.warning("Failed to parse document %s", doc_id, exc_info=True)

    log.debug("Parsed %d documents from cache", len(results))
    return results


def _parse_timestamp(value: str | int | float | None) -> datetime:
    """Parse a timestamp string or number into a datetime."""
    if value is None:
        return datetime.now(tz=timezone.utc)
    if isinstance(value, (int, float)):
        # Epoch millis or seconds
        if value > 1e12:
            value = value / 1000
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        # Try ISO format
        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        # Try parsing as number string
        try:
            return _parse_timestamp(float(value))
        except ValueError:
            pass
    return datetime.now(tz=timezone.utc)


def _parse_panels_from_markdown(markdown: str) -> list[DocumentPanel]:
    """Split a markdown string on ## headers into DocumentPanel objects."""
    import re

    panels: list[DocumentPanel] = []
    # Split on ## headers (keeping the header text)
    parts = re.split(r"^## (.+)$", markdown, flags=re.MULTILINE)

    # parts[0] is content before first ## header
    # Then alternating: header_text, content, header_text, content, ...
    preamble = parts[0].strip()
    if preamble:
        panels.append(DocumentPanel(title="Summary", content_markdown=preamble))

    # Process header/content pairs
    for i in range(1, len(parts), 2):
        title = parts[i].strip()
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if title and content:
            panels.append(DocumentPanel(title=title, content_markdown=content))

    return panels


def _parse_document(
    doc_id: str,
    doc: dict,
    meetings_meta: dict,
    transcripts: dict,
    document_panels: dict,
    chat_context: dict | None = None,
) -> GranolaDocument:
    """Parse a single document from the cache."""
    title = doc.get("title", "Untitled Meeting")
    created_at = _parse_timestamp(doc.get("created_at") or doc.get("createdAt"))
    updated_at = _parse_timestamp(doc.get("updated_at") or doc.get("updatedAt"))

    # Notes: prefer pre-rendered markdown
    notes_markdown = doc.get("notes_markdown", "") or doc.get("notesMarkdown", "") or ""
    notes_prosemirror = doc.get("notes") or doc.get("notesProsemirror")

    # Attendees: try meetingsMetadata (keyed by doc_id), then doc.people, then google_calendar_event
    attendees: list[Attendee] = []
    meta = meetings_meta.get(doc_id, {})
    attendee_list = meta.get("attendees", [])

    if not attendee_list:
        # Fallback to doc.people.attendees
        people = doc.get("people", {})
        if isinstance(people, dict):
            attendee_list = people.get("attendees", [])

    if not attendee_list:
        # Fallback to google_calendar_event.attendees
        gcal = doc.get("google_calendar_event", {})
        if isinstance(gcal, dict):
            for gcal_att in gcal.get("attendees", []):
                name = gcal_att.get("displayName") or gcal_att.get("email", "Unknown")
                attendees.append(
                    Attendee(
                        name=name,
                        email=gcal_att.get("email"),
                        is_organizer=gcal_att.get("organizer", False),
                    )
                )

    if not attendees:
        for person in attendee_list:
            attendees.append(
                Attendee(
                    name=person.get("name", person.get("email", "Unknown")),
                    email=person.get("email"),
                    is_organizer=person.get("organizer", False)
                    or person.get("is_organizer", False),
                )
            )

    # Transcript: value is a list of entries with text, source, start_timestamp
    transcript: list[TranscriptEntry] = []
    transcript_data = transcripts.get(doc_id)
    if isinstance(transcript_data, list):
        entries = transcript_data
    elif isinstance(transcript_data, dict):
        entries = transcript_data.get("entries", transcript_data.get("segments", []))
    else:
        entries = []
    for entry in entries:
        if isinstance(entry, dict):
            transcript.append(
                TranscriptEntry(
                    speaker=entry.get("source", entry.get("speaker", "Unknown")),
                    text=entry.get("text", ""),
                    timestamp=entry.get("start_timestamp") or entry.get("timestamp"),
                )
            )

    # Panels (AI-generated sections): dict of {panel_id: panel_obj}
    # panel_obj has title, content (ProseMirror JSON), document_id
    panels: list[DocumentPanel] = []
    panel_data = document_panels.get(doc_id, {})
    if isinstance(panel_data, dict):
        panel_items = panel_data.values() if not panel_data.get("panels") else panel_data["panels"]
    elif isinstance(panel_data, list):
        panel_items = panel_data
    else:
        panel_items = []
    for panel in panel_items:
        if not isinstance(panel, dict):
            continue
        panel_title = panel.get("title", "")
        if not panel_title:
            continue
        # Content may be ProseMirror JSON or plain markdown
        panel_content_raw = panel.get("content")
        if isinstance(panel_content_raw, dict):
            from .prosemirror import prosemirror_to_markdown
            panel_md = prosemirror_to_markdown(panel_content_raw)
        else:
            panel_md = (
                panel.get("markdown", "")
                or panel.get("response", "")
                or (panel_content_raw if isinstance(panel_content_raw, str) else "")
            )
        if panel_md:
            panels.append(DocumentPanel(title=panel_title, content_markdown=panel_md))

    # v4 fallback: panels stored in multiChatState.chatContext.activeEditorMarkdown
    if not panels and chat_context:
        if chat_context.get("meetingId") == doc_id:
            active_md = chat_context.get("activeEditorMarkdown", "")
            if active_md:
                panels = _parse_panels_from_markdown(active_md)

    return GranolaDocument(
        id=doc_id,
        title=title,
        created_at=created_at,
        updated_at=updated_at,
        notes_markdown=notes_markdown,
        notes_prosemirror=notes_prosemirror,
        attendees=attendees,
        transcript=transcript,
        panels=panels,
        source_url=doc.get("source_url") or doc.get("sourceUrl"),
    )
