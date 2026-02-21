"""Tests for grimoiresync.note_writer — html_to_markdown, make_filename, build_*, write_note."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from grimoiresync.models import Attendee, DocumentPanel, GranolaDocument, TranscriptEntry
from grimoiresync.note_writer import (
    assemble_note,
    build_body,
    build_metadata_section,
    html_to_markdown,
    make_filename,
    write_note,
)


class TestHtmlToMarkdown:
    def test_no_html_passthrough(self):
        assert html_to_markdown("plain text") == "plain text"

    def test_headings(self):
        for i in range(1, 7):
            result = html_to_markdown(f"<h{i}>Title</h{i}>")
            assert f"{'#' * i} Title" in result

    def test_unordered_list(self):
        result = html_to_markdown("<ul><li>A</li><li>B</li></ul>")
        assert "- A" in result
        assert "- B" in result

    def test_ordered_list(self):
        result = html_to_markdown("<ol><li>First</li><li>Second</li></ol>")
        assert "1. First" in result
        assert "2. Second" in result

    def test_nested_list(self):
        result = html_to_markdown("<ul><li>Outer<ul><li>Inner</li></ul></li></ul>")
        assert "- Outer" in result
        assert "Inner" in result

    def test_links(self):
        result = html_to_markdown('<a href="https://example.com">Click</a>')
        assert "[Click](https://example.com)" in result

    def test_hr(self):
        result = html_to_markdown("<hr>")
        assert "---" in result

    def test_paragraphs(self):
        result = html_to_markdown("<p>One</p><p>Two</p>")
        assert "One" in result
        assert "Two" in result

    def test_entity_refs(self):
        result = html_to_markdown("<p>A &amp; B</p>")
        assert "A & B" in result

    def test_char_refs(self):
        result = html_to_markdown("<p>&#38;</p>")
        assert "&" in result

    def test_blank_line_collapsing(self):
        result = html_to_markdown("<p>A</p><p>B</p>")
        # Should not have excessive blank lines
        assert "\n\n\n" not in result

    def test_heading_blank_line_reinsertion(self):
        result = html_to_markdown("<p>Intro</p><h2>Section</h2>")
        # Should have blank line before heading
        assert "\n\n## Section" in result

    def test_ul_ol_endtag_pop_and_newline(self):
        # Outermost list close should add extra newline
        result = html_to_markdown("<ul><li>A</li></ul>rest")
        assert "rest" in result

    def test_orphan_li_no_parent_list(self):
        # <li> without <ul>/<ol> should not crash (list_stack empty branch)
        result = html_to_markdown("<li>orphan</li>")
        assert "orphan" in result

    def test_unrecognized_start_tag(self):
        # Unknown tags like <span> should pass through content
        result = html_to_markdown("<span>content</span>")
        assert "content" in result

    def test_endtag_ul_with_empty_stack(self):
        # Closing </ul> when stack is already empty
        result = html_to_markdown("</ul>text")
        assert "text" in result

    def test_handle_entityref_directly(self):
        """Directly test handle_entityref (not called with convert_charrefs=True)."""
        from grimoiresync.note_writer import _HtmlToMarkdown
        parser = _HtmlToMarkdown()
        parser.handle_entityref("amp")
        assert "&" in parser._parts

    def test_handle_charref_directly(self):
        """Directly test handle_charref (not called with convert_charrefs=True)."""
        from grimoiresync.note_writer import _HtmlToMarkdown
        parser = _HtmlToMarkdown()
        parser.handle_charref("38")
        assert "&" in parser._parts


class TestMakeFilename:
    def test_basic(self, fixed_now):
        doc = GranolaDocument(id="d", title="Title", created_at=fixed_now, updated_at=fixed_now)
        assert make_filename(doc) == "2024-06-15 - Title.md"

    def test_invalid_chars_stripped(self, fixed_now):
        doc = GranolaDocument(id="d", title='A<>:"/\\|?*B', created_at=fixed_now, updated_at=fixed_now)
        result = make_filename(doc)
        assert "<" not in result
        assert ">" not in result
        assert ":" not in result
        assert "AB" in result

    def test_title_has_date_prefix(self, fixed_now):
        doc = GranolaDocument(id="d", title="2024-06-15 - Already", created_at=fixed_now, updated_at=fixed_now)
        result = make_filename(doc)
        assert result == "2024-06-15 - Already.md"
        assert not result.startswith("2024-06-15 - 2024-06-15")

    def test_date_prefix_with_dash(self, fixed_now):
        doc = GranolaDocument(id="d", title="2024-06-15-Title", created_at=fixed_now, updated_at=fixed_now)
        assert make_filename(doc) == "2024-06-15-Title.md"

    def test_date_prefix_en_dash(self, fixed_now):
        doc = GranolaDocument(id="d", title="2024-06-15\u2013Title", created_at=fixed_now, updated_at=fixed_now)
        assert make_filename(doc) == "2024-06-15\u2013Title.md"

    def test_date_prefix_em_dash(self, fixed_now):
        doc = GranolaDocument(id="d", title="2024-06-15\u2014Title", created_at=fixed_now, updated_at=fixed_now)
        assert make_filename(doc) == "2024-06-15\u2014Title.md"

    def test_none_title(self, fixed_now):
        doc = GranolaDocument(id="d", title=None, created_at=fixed_now, updated_at=fixed_now)
        assert "Untitled Meeting" in make_filename(doc)

    def test_empty_title(self, fixed_now):
        doc = GranolaDocument(id="d", title="", created_at=fixed_now, updated_at=fixed_now)
        assert "Untitled Meeting" in make_filename(doc)


class TestBuildMetadataSection:
    def test_produces_details_block(self, sample_document):
        meta = build_metadata_section(sample_document)
        assert "<details>" in meta
        assert "<summary>Metadata</summary>" in meta
        assert "</details>" in meta
        assert "| granola_id | doc-123 |" in meta
        assert "| date |" in meta
        assert "| attendees | Alice, Bob |" in meta
        assert "| tags | meeting, granola |" in meta
        assert meta.startswith("---\n")

    def test_no_attendees(self, minimal_document):
        meta = build_metadata_section(minimal_document)
        assert "| attendees |  |" in meta


class TestBuildBody:
    def test_with_panels(self, sample_document):
        body = build_body(sample_document, include_panels=True)
        assert "## Summary" in body
        assert "## Action Items" in body

    def test_without_panels_has_notes_markdown(self, fixed_now):
        doc = GranolaDocument(
            id="d", title="T", created_at=fixed_now, updated_at=fixed_now,
            notes_markdown="My notes here",
        )
        body = build_body(doc, include_panels=False)
        assert "My notes here" in body

    def test_no_panels_no_markdown_has_prosemirror(self, fixed_now):
        pm = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "PM notes"}]}]}
        doc = GranolaDocument(
            id="d", title="T", created_at=fixed_now, updated_at=fixed_now,
            notes_prosemirror=pm,
        )
        body = build_body(doc, include_panels=False)
        assert "PM notes" in body

    def test_include_panels_true_but_empty_falls_back_to_notes(self, fixed_now):
        doc = GranolaDocument(
            id="d", title="T", created_at=fixed_now, updated_at=fixed_now,
            notes_markdown="fallback notes",
        )
        body = build_body(doc, include_panels=True)
        assert "fallback notes" in body

    def test_attendees_section_present(self, sample_document):
        body = build_body(sample_document)
        assert "## Attendees" in body
        assert "- Alice" in body
        assert "- Bob" in body

    def test_attendees_section_absent(self, minimal_document):
        body = build_body(minimal_document)
        assert "Attendees" not in body

    def test_transcript_included(self, fixed_now, sample_transcript):
        doc = GranolaDocument(
            id="d", title="T", created_at=fixed_now, updated_at=fixed_now,
            transcript=sample_transcript,
        )
        body = build_body(doc, include_transcript=True)
        assert "<details>" in body
        assert "**Alice**:" in body
        assert "**Bob**:" in body

    def test_transcript_excluded(self, fixed_now, sample_transcript):
        doc = GranolaDocument(
            id="d", title="T", created_at=fixed_now, updated_at=fixed_now,
            transcript=sample_transcript,
        )
        body = build_body(doc, include_transcript=False)
        assert "<details>" not in body

    def test_transcript_empty(self, fixed_now):
        doc = GranolaDocument(
            id="d", title="T", created_at=fixed_now, updated_at=fixed_now,
        )
        body = build_body(doc, include_transcript=True)
        assert "<details>" not in body

    def test_chat_transcript_line_stripped(self, fixed_now):
        """Chat transcript block (one preceding ---) is removed from panel content."""
        panel_content = (
            "Meeting went well.\n\n"
            "---\n\n"
            "Chat with meeting transcript: "
            "[https://notes.granola.ai/t/abc-123](https://notes.granola.ai/t/abc-123)"
        )
        doc = GranolaDocument(
            id="d", title="T", created_at=fixed_now, updated_at=fixed_now,
            panels=[DocumentPanel(title="Summary", content_markdown=panel_content)],
        )
        body = build_body(doc, include_panels=True)
        assert "Chat with meeting transcript" not in body
        assert "Meeting went well." in body

    def test_chat_transcript_with_trailing_hr_stripped(self, fixed_now):
        """Chat transcript block with trailing --- is also removed."""
        panel_content = (
            "Meeting went well.\n\n"
            "---\n\n"
            "Chat with meeting transcript: "
            "[https://notes.granola.ai/t/abc-123](https://notes.granola.ai/t/abc-123)\n\n"
            "---"
        )
        doc = GranolaDocument(
            id="d", title="T", created_at=fixed_now, updated_at=fixed_now,
            panels=[DocumentPanel(title="Summary", content_markdown=panel_content)],
        )
        body = build_body(doc, include_panels=True)
        assert "Chat with meeting transcript" not in body
        assert "Meeting went well." in body


class TestAssembleNote:
    def test_body_before_metadata(self, sample_document):
        note = assemble_note(sample_document)
        assert note.endswith("</details>\n")
        assert "<details>" in note
        # Body content appears before the metadata section
        body_pos = note.index("## Attendees")
        meta_pos = note.index("<details>")
        assert body_pos < meta_pos


class TestWriteNote:
    def test_normal_write(self, fixed_now, tmp_path):
        doc = GranolaDocument(
            id="d", title="Test", created_at=fixed_now, updated_at=fixed_now,
        )
        content = "test content"
        path = write_note(doc, tmp_path, content)
        assert path.exists()
        assert path.read_text(encoding="utf-8") == "test content"

    def test_dry_run_no_write(self, fixed_now, tmp_path):
        doc = GranolaDocument(
            id="d", title="Test", created_at=fixed_now, updated_at=fixed_now,
        )
        notes_dir = tmp_path / "subdir"
        path = write_note(doc, notes_dir, "content", dry_run=True)
        assert not notes_dir.exists()
        assert "Test" in str(path)

    def test_creates_directory(self, fixed_now, tmp_path):
        doc = GranolaDocument(
            id="d", title="Test", created_at=fixed_now, updated_at=fixed_now,
        )
        sub = tmp_path / "deep" / "nested"
        path = write_note(doc, sub, "content")
        assert sub.exists()
        assert path.exists()
