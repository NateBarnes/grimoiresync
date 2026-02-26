"""Tests for grimoiresync.cache_parser — parse_cache, _parse_timestamp, _parse_document."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from datetime import datetime as real_datetime

import pytest

from grimoiresync.cache_parser import (
    _parse_document,
    _parse_panels_from_markdown,
    _parse_timestamp,
    parse_cache,
)
from grimoiresync.models import GranolaDocument


class TestParseTimestamp:
    def test_none_returns_now(self):
        with patch("grimoiresync.cache_parser.datetime") as mock_dt:
            sentinel = datetime(2024, 1, 1, tzinfo=timezone.utc)
            mock_dt.now.return_value = sentinel
            mock_dt.fromtimestamp = datetime.fromtimestamp
            mock_dt.strptime = datetime.strptime
            result = _parse_timestamp(None)
            assert result == sentinel
            mock_dt.now.assert_called_once_with(tz=timezone.utc)

    def test_int_epoch_seconds(self):
        ts = 1700000000  # < 1e12
        result = _parse_timestamp(ts)
        expected = datetime.fromtimestamp(1700000000, tz=timezone.utc)
        assert result == expected

    def test_int_epoch_millis(self):
        ts = 1700000000000  # > 1e12
        result = _parse_timestamp(ts)
        expected = datetime.fromtimestamp(1700000000, tz=timezone.utc)
        assert result == expected

    def test_iso_string_with_millis_z(self):
        result = _parse_timestamp("2024-06-15T12:30:45.123Z")
        assert result.year == 2024
        assert result.month == 6
        assert result.day == 15
        assert result.hour == 12
        assert result.minute == 30
        assert result.second == 45
        assert result.tzinfo == timezone.utc

    def test_iso_string_without_millis_z(self):
        result = _parse_timestamp("2024-06-15T12:30:45Z")
        assert result == datetime(2024, 6, 15, 12, 30, 45, tzinfo=timezone.utc)

    def test_iso_string_no_z(self):
        result = _parse_timestamp("2024-06-15T12:30:45")
        assert result == datetime(2024, 6, 15, 12, 30, 45, tzinfo=timezone.utc)

    def test_numeric_string(self):
        result = _parse_timestamp("1700000000")
        expected = datetime.fromtimestamp(1700000000, tz=timezone.utc)
        assert result == expected

    def test_unparseable_string_returns_now(self):
        with patch("grimoiresync.cache_parser.datetime") as mock_dt:
            sentinel = datetime(2024, 1, 1, tzinfo=timezone.utc)
            mock_dt.now.return_value = sentinel
            mock_dt.fromtimestamp = datetime.fromtimestamp
            mock_dt.strptime = datetime.strptime
            result = _parse_timestamp("not-a-date")
            assert result == sentinel

    def test_non_str_int_float_returns_now(self):
        with patch("grimoiresync.cache_parser.datetime") as mock_dt:
            sentinel = datetime(2024, 1, 1, tzinfo=timezone.utc)
            mock_dt.now.return_value = sentinel
            mock_dt.fromtimestamp = datetime.fromtimestamp
            mock_dt.strptime = datetime.strptime
            result = _parse_timestamp([])
            assert result == sentinel

    def test_float_epoch_seconds(self):
        result = _parse_timestamp(1700000000.5)
        expected = datetime.fromtimestamp(1700000000.5, tz=timezone.utc)
        assert result == expected


class TestParseDocument:
    def test_basic_document(self):
        doc = {"title": "My Meeting", "created_at": 1700000000, "updated_at": 1700000000}
        result = _parse_document("d1", doc, {}, {}, {})
        assert result.id == "d1"
        assert result.title == "My Meeting"

    def test_missing_title(self):
        doc = {"created_at": 1700000000, "updated_at": 1700000000}
        result = _parse_document("d1", doc, {}, {}, {})
        assert result.title == "Untitled Meeting"

    def test_attendees_from_meetings_metadata(self):
        doc = {"created_at": 1700000000, "updated_at": 1700000000}
        meta = {
            "d1": {
                "attendees": [
                    {"name": "Alice", "email": "alice@x.com", "organizer": True},
                    {"name": "Bob", "email": "bob@x.com"},
                ]
            }
        }
        result = _parse_document("d1", doc, meta, {}, {})
        assert len(result.attendees) == 2
        assert result.attendees[0].name == "Alice"
        assert result.attendees[0].is_organizer is True

    def test_attendees_fallback_to_people(self):
        doc = {
            "created_at": 1700000000,
            "updated_at": 1700000000,
            "people": {
                "attendees": [{"name": "Carol", "email": "carol@x.com"}]
            },
        }
        result = _parse_document("d1", doc, {}, {}, {})
        assert len(result.attendees) == 1
        assert result.attendees[0].name == "Carol"

    def test_attendees_fallback_to_gcal(self):
        doc = {
            "created_at": 1700000000,
            "updated_at": 1700000000,
            "google_calendar_event": {
                "attendees": [
                    {"displayName": "Dave", "email": "dave@x.com", "organizer": True},
                    {"email": "eve@x.com"},  # no displayName, falls back to email
                ]
            },
        }
        result = _parse_document("d1", doc, {}, {}, {})
        assert len(result.attendees) == 2
        assert result.attendees[0].name == "Dave"
        assert result.attendees[0].is_organizer is True
        assert result.attendees[1].name == "eve@x.com"

    def test_people_not_a_dict(self):
        doc = {"created_at": 1700000000, "updated_at": 1700000000, "people": "not-dict"}
        result = _parse_document("d1", doc, {}, {}, {})
        assert result.attendees == []

    def test_gcal_not_a_dict(self):
        doc = {
            "created_at": 1700000000,
            "updated_at": 1700000000,
            "google_calendar_event": "not-dict",
        }
        result = _parse_document("d1", doc, {}, {}, {})
        assert result.attendees == []

    def test_transcript_as_list(self):
        transcript_data = {"d1": [{"source": "Alice", "text": "Hello", "start_timestamp": 1.0}]}
        doc = {"created_at": 1700000000, "updated_at": 1700000000}
        result = _parse_document("d1", doc, {}, transcript_data, {})
        assert len(result.transcript) == 1
        assert result.transcript[0].speaker == "Alice"
        assert result.transcript[0].timestamp == 1.0

    def test_transcript_as_dict_with_entries(self):
        transcript_data = {
            "d1": {"entries": [{"speaker": "Bob", "text": "Hi"}]}
        }
        doc = {"created_at": 1700000000, "updated_at": 1700000000}
        result = _parse_document("d1", doc, {}, transcript_data, {})
        assert len(result.transcript) == 1
        assert result.transcript[0].speaker == "Bob"

    def test_transcript_as_dict_with_segments(self):
        transcript_data = {
            "d1": {"segments": [{"source": "Carol", "text": "Hey"}]}
        }
        doc = {"created_at": 1700000000, "updated_at": 1700000000}
        result = _parse_document("d1", doc, {}, transcript_data, {})
        assert len(result.transcript) == 1
        assert result.transcript[0].speaker == "Carol"

    def test_transcript_none(self):
        doc = {"created_at": 1700000000, "updated_at": 1700000000}
        result = _parse_document("d1", doc, {}, {}, {})
        assert result.transcript == []

    def test_non_dict_transcript_entries_skipped(self):
        transcript_data = {"d1": ["not-a-dict", {"source": "A", "text": "B"}]}
        doc = {"created_at": 1700000000, "updated_at": 1700000000}
        result = _parse_document("d1", doc, {}, transcript_data, {})
        assert len(result.transcript) == 1

    def test_panels_dict_of_dicts(self):
        panels = {
            "d1": {
                "p1": {"title": "Summary", "markdown": "Good meeting"},
                "p2": {"title": "Actions", "markdown": "Do stuff"},
            }
        }
        doc = {"created_at": 1700000000, "updated_at": 1700000000}
        result = _parse_document("d1", doc, {}, {}, panels)
        assert len(result.panels) == 2

    def test_panels_with_panels_key(self):
        panels = {
            "d1": {
                "panels": [
                    {"title": "Summary", "markdown": "Content"},
                ]
            }
        }
        doc = {"created_at": 1700000000, "updated_at": 1700000000}
        result = _parse_document("d1", doc, {}, {}, panels)
        assert len(result.panels) == 1

    def test_panels_as_list(self):
        panels = {"d1": [{"title": "Summary", "markdown": "Content"}]}
        doc = {"created_at": 1700000000, "updated_at": 1700000000}
        result = _parse_document("d1", doc, {}, {}, panels)
        assert len(result.panels) == 1

    def test_non_dict_panel_items_skipped(self):
        panels = {"d1": ["not-a-dict", {"title": "Good", "markdown": "Content"}]}
        doc = {"created_at": 1700000000, "updated_at": 1700000000}
        result = _parse_document("d1", doc, {}, {}, panels)
        assert len(result.panels) == 1

    def test_empty_panel_title_skipped(self):
        panels = {"d1": [{"title": "", "markdown": "Content"}]}
        doc = {"created_at": 1700000000, "updated_at": 1700000000}
        result = _parse_document("d1", doc, {}, {}, panels)
        assert len(result.panels) == 0

    def test_panel_content_prosemirror(self):
        panels = {
            "d1": [
                {
                    "title": "Summary",
                    "content": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "hello"}]}]},
                }
            ]
        }
        doc = {"created_at": 1700000000, "updated_at": 1700000000}
        result = _parse_document("d1", doc, {}, {}, panels)
        assert len(result.panels) == 1
        assert "hello" in result.panels[0].content_markdown

    def test_panel_content_markdown_field(self):
        panels = {"d1": [{"title": "S", "content": None, "markdown": "md content"}]}
        doc = {"created_at": 1700000000, "updated_at": 1700000000}
        result = _parse_document("d1", doc, {}, {}, panels)
        assert result.panels[0].content_markdown == "md content"

    def test_panel_content_response_field(self):
        panels = {"d1": [{"title": "S", "content": None, "response": "resp content"}]}
        doc = {"created_at": 1700000000, "updated_at": 1700000000}
        result = _parse_document("d1", doc, {}, {}, panels)
        assert result.panels[0].content_markdown == "resp content"

    def test_panel_content_raw_string(self):
        panels = {"d1": [{"title": "S", "content": "raw string"}]}
        doc = {"created_at": 1700000000, "updated_at": 1700000000}
        result = _parse_document("d1", doc, {}, {}, panels)
        assert result.panels[0].content_markdown == "raw string"

    def test_panel_empty_markdown_skipped(self):
        panels = {"d1": [{"title": "S", "content": None, "markdown": ""}]}
        doc = {"created_at": 1700000000, "updated_at": 1700000000}
        result = _parse_document("d1", doc, {}, {}, panels)
        assert len(result.panels) == 0

    def test_panel_data_non_dict_non_list(self):
        """When panel_data is a scalar (not dict/list), panels should be empty."""
        panels = {"d1": "not-a-dict-or-list"}
        doc = {"created_at": 1700000000, "updated_at": 1700000000}
        result = _parse_document("d1", doc, {}, {}, panels)
        assert result.panels == []

    def test_source_url_variant(self):
        doc = {"created_at": 1700000000, "updated_at": 1700000000, "source_url": "http://a"}
        result = _parse_document("d1", doc, {}, {}, {})
        assert result.source_url == "http://a"

    def test_sourceUrl_variant(self):
        doc = {"created_at": 1700000000, "updated_at": 1700000000, "sourceUrl": "http://b"}
        result = _parse_document("d1", doc, {}, {}, {})
        assert result.source_url == "http://b"

    def test_notes_markdown_variant(self):
        doc = {"created_at": 1700000000, "updated_at": 1700000000, "notes_markdown": "notes1"}
        result = _parse_document("d1", doc, {}, {}, {})
        assert result.notes_markdown == "notes1"

    def test_notesMarkdown_variant(self):
        doc = {"created_at": 1700000000, "updated_at": 1700000000, "notesMarkdown": "notes2"}
        result = _parse_document("d1", doc, {}, {}, {})
        assert result.notes_markdown == "notes2"

    def test_notes_prosemirror_via_notes(self):
        pm = {"type": "doc", "content": []}
        doc = {"created_at": 1700000000, "updated_at": 1700000000, "notes": pm}
        result = _parse_document("d1", doc, {}, {}, {})
        assert result.notes_prosemirror == pm

    def test_notes_prosemirror_via_notesProsemirror(self):
        pm = {"type": "doc", "content": []}
        doc = {"created_at": 1700000000, "updated_at": 1700000000, "notesProsemirror": pm}
        result = _parse_document("d1", doc, {}, {}, {})
        assert result.notes_prosemirror == pm

    def test_attendee_name_fallback_to_email(self):
        """When name is missing, falls back to email, then 'Unknown'."""
        doc = {"created_at": 1700000000, "updated_at": 1700000000}
        meta = {"d1": {"attendees": [{"email": "x@y.com"}]}}
        result = _parse_document("d1", doc, meta, {}, {})
        assert result.attendees[0].name == "x@y.com"

    def test_attendee_is_organizer_field(self):
        doc = {"created_at": 1700000000, "updated_at": 1700000000}
        meta = {"d1": {"attendees": [{"name": "A", "is_organizer": True}]}}
        result = _parse_document("d1", doc, meta, {}, {})
        assert result.attendees[0].is_organizer is True


class TestParseCache:
    def test_full_parse(self, tmp_path):
        cache_data = {
            "cache": json.dumps({
                "state": {
                    "documents": {
                        "d1": {"title": "Meet1", "created_at": 1700000000, "updated_at": 1700000000},
                        "d2": {"title": "Meet2", "created_at": 1700000000, "updated_at": 1700000000},
                    },
                    "meetingsMetadata": {},
                    "transcripts": {},
                    "documentPanels": {},
                }
            })
        }
        cache_file = tmp_path / "cache.json"
        cache_file.write_text(json.dumps(cache_data))
        results = parse_cache(cache_file)
        assert len(results) == 2

    def test_deleted_document_skipped(self, tmp_path):
        cache_data = {
            "cache": json.dumps({
                "state": {
                    "documents": {
                        "d1": {"title": "M", "created_at": 1700000000, "updated_at": 1700000000, "deleted_at": 1700000001},
                        "d2": {"title": "M2", "created_at": 1700000000, "updated_at": 1700000000},
                    },
                    "meetingsMetadata": {},
                    "transcripts": {},
                    "documentPanels": {},
                }
            })
        }
        cache_file = tmp_path / "cache.json"
        cache_file.write_text(json.dumps(cache_data))
        results = parse_cache(cache_file)
        assert len(results) == 1
        assert results[0].id == "d2"

    def test_double_encoded_cache(self, tmp_path):
        inner = json.dumps({
            "state": {
                "documents": {"d1": {"title": "T", "created_at": 1700000000, "updated_at": 1700000000}},
                "meetingsMetadata": {},
                "transcripts": {},
                "documentPanels": {},
            }
        })
        cache_file = tmp_path / "cache.json"
        cache_file.write_text(json.dumps({"cache": inner}))
        results = parse_cache(cache_file)
        assert len(results) == 1

    def test_already_decoded_cache(self, tmp_path):
        cache_data = {
            "cache": {
                "state": {
                    "documents": {"d1": {"title": "T", "created_at": 1700000000, "updated_at": 1700000000}},
                    "meetingsMetadata": {},
                    "transcripts": {},
                    "documentPanels": {},
                }
            }
        }
        cache_file = tmp_path / "cache.json"
        cache_file.write_text(json.dumps(cache_data))
        results = parse_cache(cache_file)
        assert len(results) == 1

    def test_empty_documents(self, tmp_path):
        cache_data = {"cache": json.dumps({"state": {"documents": {}}})}
        cache_file = tmp_path / "cache.json"
        cache_file.write_text(json.dumps(cache_data))
        results = parse_cache(cache_file)
        assert results == []

    def test_missing_state_key(self, tmp_path):
        cache_data = {"cache": json.dumps({})}
        cache_file = tmp_path / "cache.json"
        cache_file.write_text(json.dumps(cache_data))
        results = parse_cache(cache_file)
        assert results == []

    def test_one_doc_raises_exception(self, tmp_path):
        """When one doc fails to parse, it's logged and others still succeed."""
        inner = {
            "state": {
                "documents": {
                    "d1": {"title": "Bad"},  # missing timestamps will still work, but let's trigger an actual error
                    "d2": {"title": "Good", "created_at": 1700000000, "updated_at": 1700000000},
                },
                "meetingsMetadata": {},
                "transcripts": {},
                "documentPanels": {},
            }
        }
        cache_file = tmp_path / "cache.json"
        cache_file.write_text(json.dumps({"cache": json.dumps(inner)}))
        # Patch _parse_document to fail on d1 only
        with patch("grimoiresync.cache_parser._parse_document") as mock_pd:
            def side_effect(doc_id, *args):
                if doc_id == "d1":
                    raise RuntimeError("parse failed")
                return GranolaDocument(
                    id=doc_id, title="Good",
                    created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                )
            mock_pd.side_effect = side_effect
            results = parse_cache(cache_file)
        assert len(results) == 1
        assert results[0].title == "Good"

    def test_v4_chat_context_fallback(self, tmp_path):
        """v4: panels extracted from chatContext.activeEditorMarkdown when documentPanels is empty."""
        cache_data = {
            "cache": json.dumps({
                "state": {
                    "documents": {
                        "d1": {"title": "Meet1", "created_at": 1700000000, "updated_at": 1700000000},
                    },
                    "meetingsMetadata": {},
                    "transcripts": {},
                    "documentPanels": {},
                    "multiChatState": {
                        "chatContext": {
                            "meetingId": "d1",
                            "activeEditorMarkdown": "## Summary\n\nGood meeting.\n\n## Action Items\n\n- Do stuff",
                        }
                    },
                }
            })
        }
        cache_file = tmp_path / "cache.json"
        cache_file.write_text(json.dumps(cache_data))
        results = parse_cache(cache_file)
        assert len(results) == 1
        assert len(results[0].panels) == 2
        assert results[0].panels[0].title == "Summary"
        assert "Good meeting." in results[0].panels[0].content_markdown
        assert results[0].panels[1].title == "Action Items"


class TestParsePanelsFromMarkdown:
    def test_multiple_sections(self):
        md = "## Summary\n\nGood meeting.\n\n## Action Items\n\n- Do stuff\n- More stuff"
        panels = _parse_panels_from_markdown(md)
        assert len(panels) == 2
        assert panels[0].title == "Summary"
        assert "Good meeting." in panels[0].content_markdown
        assert panels[1].title == "Action Items"
        assert "- Do stuff" in panels[1].content_markdown

    def test_preamble_becomes_summary(self):
        md = "Some intro text\n\n## Details\n\nDetail content"
        panels = _parse_panels_from_markdown(md)
        assert len(panels) == 2
        assert panels[0].title == "Summary"
        assert "Some intro text" in panels[0].content_markdown
        assert panels[1].title == "Details"

    def test_empty_markdown(self):
        panels = _parse_panels_from_markdown("")
        assert panels == []

    def test_no_headers(self):
        md = "Just plain text with no headers"
        panels = _parse_panels_from_markdown(md)
        assert len(panels) == 1
        assert panels[0].title == "Summary"
        assert "Just plain text" in panels[0].content_markdown

    def test_header_with_empty_content_skipped(self):
        md = "## Empty Section\n\n## Has Content\n\nSome text"
        panels = _parse_panels_from_markdown(md)
        assert len(panels) == 1
        assert panels[0].title == "Has Content"


class TestV4ChatContextPanels:
    """Tests for v4 chatContext fallback in _parse_document."""

    def test_matching_meeting_id_gets_panels(self):
        doc = {"created_at": 1700000000, "updated_at": 1700000000}
        chat_context = {
            "meetingId": "d1",
            "activeEditorMarkdown": "## Summary\n\nContent here",
        }
        result = _parse_document("d1", doc, {}, {}, {}, chat_context)
        assert len(result.panels) == 1
        assert result.panels[0].title == "Summary"

    def test_non_matching_meeting_id_gets_no_panels(self):
        doc = {"created_at": 1700000000, "updated_at": 1700000000}
        chat_context = {
            "meetingId": "other-doc",
            "activeEditorMarkdown": "## Summary\n\nContent here",
        }
        result = _parse_document("d1", doc, {}, {}, {}, chat_context)
        assert result.panels == []

    def test_v3_panels_take_priority(self):
        doc = {"created_at": 1700000000, "updated_at": 1700000000}
        v3_panels = {"d1": [{"title": "V3 Panel", "markdown": "V3 content"}]}
        chat_context = {
            "meetingId": "d1",
            "activeEditorMarkdown": "## V4 Panel\n\nV4 content",
        }
        result = _parse_document("d1", doc, {}, {}, v3_panels, chat_context)
        assert len(result.panels) == 1
        assert result.panels[0].title == "V3 Panel"
        assert result.panels[0].content_markdown == "V3 content"

    def test_empty_active_editor_markdown(self):
        doc = {"created_at": 1700000000, "updated_at": 1700000000}
        chat_context = {
            "meetingId": "d1",
            "activeEditorMarkdown": "",
        }
        result = _parse_document("d1", doc, {}, {}, {}, chat_context)
        assert result.panels == []

    def test_none_chat_context(self):
        doc = {"created_at": 1700000000, "updated_at": 1700000000}
        result = _parse_document("d1", doc, {}, {}, {}, None)
        assert result.panels == []
