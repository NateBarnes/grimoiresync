"""Shared fixtures for grimoiresync tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from grimoiresync.config import Config
from grimoiresync.models import Attendee, DocumentPanel, GranolaDocument, TranscriptEntry


@pytest.fixture
def sample_attendees() -> list[Attendee]:
    return [
        Attendee(name="Alice", email="alice@example.com", is_organizer=True),
        Attendee(name="Bob", email="bob@example.com"),
    ]


@pytest.fixture
def sample_transcript() -> list[TranscriptEntry]:
    return [
        TranscriptEntry(speaker="Alice", text="Hello everyone", timestamp=1000.0),
        TranscriptEntry(speaker="Bob", text="Hi Alice"),
    ]


@pytest.fixture
def sample_panels() -> list[DocumentPanel]:
    return [
        DocumentPanel(title="Summary", content_markdown="Meeting went well."),
        DocumentPanel(title="Action Items", content_markdown="- Follow up"),
    ]


@pytest.fixture
def fixed_now() -> datetime:
    return datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def sample_document(
    sample_attendees: list[Attendee],
    sample_transcript: list[TranscriptEntry],
    sample_panels: list[DocumentPanel],
    fixed_now: datetime,
) -> GranolaDocument:
    return GranolaDocument(
        id="doc-123",
        title="Team Standup",
        created_at=fixed_now,
        updated_at=fixed_now,
        notes_markdown="Some notes here.",
        notes_prosemirror={"type": "doc", "content": []},
        attendees=sample_attendees,
        transcript=sample_transcript,
        panels=sample_panels,
        source_url="https://app.granola.so/doc/123",
    )


@pytest.fixture
def minimal_document(fixed_now: datetime) -> GranolaDocument:
    return GranolaDocument(
        id="doc-minimal",
        title="Minimal",
        created_at=fixed_now,
        updated_at=fixed_now,
    )


@pytest.fixture
def sample_config() -> Config:
    return Config(vault_path=Path("/vault"), notes_subfolder="Meetings")
