"""Data models for Granola documents."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Attendee:
    name: str
    email: str | None = None
    is_organizer: bool = False


@dataclass
class TranscriptEntry:
    speaker: str
    text: str
    timestamp: float | None = None


@dataclass
class DocumentPanel:
    """AI-generated summary panel (e.g. 'Summary', 'Action Items')."""

    title: str
    content_markdown: str


@dataclass
class GranolaDocument:
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    notes_markdown: str = ""
    notes_prosemirror: dict | None = None
    attendees: list[Attendee] = field(default_factory=list)
    transcript: list[TranscriptEntry] = field(default_factory=list)
    panels: list[DocumentPanel] = field(default_factory=list)
    source_url: str | None = None
