"""Tests for grimoiresync.models — pure dataclass tests, no mocks needed."""

from __future__ import annotations

from datetime import datetime, timezone

from grimoiresync.models import Attendee, DocumentPanel, GranolaDocument, TranscriptEntry


class TestAttendee:
    def test_defaults(self):
        a = Attendee(name="Alice")
        assert a.name == "Alice"
        assert a.email is None
        assert a.is_organizer is False

    def test_all_fields(self):
        a = Attendee(name="Bob", email="bob@x.com", is_organizer=True)
        assert a.name == "Bob"
        assert a.email == "bob@x.com"
        assert a.is_organizer is True


class TestTranscriptEntry:
    def test_defaults(self):
        t = TranscriptEntry(speaker="Alice", text="hello")
        assert t.speaker == "Alice"
        assert t.text == "hello"
        assert t.timestamp is None

    def test_all_fields(self):
        t = TranscriptEntry(speaker="Bob", text="hi", timestamp=42.5)
        assert t.timestamp == 42.5


class TestDocumentPanel:
    def test_creation(self):
        p = DocumentPanel(title="Summary", content_markdown="content")
        assert p.title == "Summary"
        assert p.content_markdown == "content"


class TestGranolaDocument:
    def test_required_only_defaults(self, fixed_now):
        doc = GranolaDocument(
            id="d1", title="T", created_at=fixed_now, updated_at=fixed_now
        )
        assert doc.notes_markdown == ""
        assert doc.notes_prosemirror is None
        assert doc.attendees == []
        assert doc.transcript == []
        assert doc.panels == []
        assert doc.source_url is None

    def test_all_fields(self, sample_document):
        doc = sample_document
        assert doc.id == "doc-123"
        assert doc.title == "Team Standup"
        assert doc.notes_markdown == "Some notes here."
        assert doc.notes_prosemirror is not None
        assert len(doc.attendees) == 2
        assert len(doc.transcript) == 2
        assert len(doc.panels) == 2
        assert doc.source_url == "https://app.granola.so/doc/123"

    def test_mutable_field_independence(self, fixed_now):
        doc1 = GranolaDocument(
            id="a", title="A", created_at=fixed_now, updated_at=fixed_now
        )
        doc2 = GranolaDocument(
            id="b", title="B", created_at=fixed_now, updated_at=fixed_now
        )
        doc1.attendees.append(Attendee(name="X"))
        assert doc2.attendees == []
        doc1.transcript.append(TranscriptEntry(speaker="Y", text="z"))
        assert doc2.transcript == []
        doc1.panels.append(DocumentPanel(title="P", content_markdown="c"))
        assert doc2.panels == []
