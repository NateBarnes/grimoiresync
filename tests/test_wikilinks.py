"""Tests for grimoiresync.wikilinks — scan_vault_terms, inject_wikilinks."""

from __future__ import annotations

from pathlib import Path

import pytest

from grimoiresync.wikilinks import (
    _build_protected_zones,
    _in_protected_zone,
    inject_wikilinks,
    scan_vault_terms,
)


class TestScanVaultTerms:
    def test_filename_stems(self, tmp_path):
        (tmp_path / "Meeting Notes.md").write_text("content")
        (tmp_path / "Short.md").write_text("content")
        terms = scan_vault_terms(tmp_path, min_length=3)
        assert "meeting notes" in terms
        assert "short" in terms

    def test_min_length_filter(self, tmp_path):
        (tmp_path / "AB.md").write_text("content")
        (tmp_path / "ABC.md").write_text("content")
        terms = scan_vault_terms(tmp_path, min_length=3)
        assert "ab" not in terms
        assert "abc" in terms

    def test_existing_wikilinks_scanned(self, tmp_path):
        (tmp_path / "note.md").write_text("See [[Project Alpha]] for details")
        terms = scan_vault_terms(tmp_path, min_length=3)
        assert "project alpha" in terms

    def test_wikilink_with_alias(self, tmp_path):
        (tmp_path / "note.md").write_text("See [[Target|Display]] here")
        terms = scan_vault_terms(tmp_path, min_length=3)
        assert "target" in terms

    def test_oserror_on_read_skipped(self, tmp_path):
        (tmp_path / "good.md").write_text("content")
        bad = tmp_path / "bad.md"
        bad.write_text("content")
        bad.chmod(0o000)
        try:
            terms = scan_vault_terms(tmp_path, min_length=3)
            assert "good" in terms
        finally:
            bad.chmod(0o644)

    def test_setdefault_preserves_first(self, tmp_path):
        (tmp_path / "Alpha.md").write_text("[[alpha]]")
        terms = scan_vault_terms(tmp_path, min_length=3)
        # The stem "Alpha" should be preserved (added first by rglob)
        assert terms["alpha"] == "Alpha"

    def test_short_wikilink_target_filtered(self, tmp_path):
        """Wikilink targets shorter than min_length are excluded."""
        (tmp_path / "note.md").write_text("See [[AB]] for details")
        terms = scan_vault_terms(tmp_path, min_length=3)
        assert "ab" not in terms


class TestBuildProtectedZones:
    def test_frontmatter(self):
        text = "---\ntitle: foo\n---\nBody"
        zones = _build_protected_zones(text)
        assert any(s == 0 for s, _ in zones)

    def test_fenced_code(self):
        text = "Before\n```\ncode\n```\nAfter"
        zones = _build_protected_zones(text)
        assert len(zones) > 0

    def test_inline_code(self):
        text = "Use `code` here"
        zones = _build_protected_zones(text)
        assert len(zones) > 0

    def test_existing_wikilinks(self):
        text = "See [[Link]] here"
        zones = _build_protected_zones(text)
        assert len(zones) > 0

    def test_markdown_links(self):
        text = "Click [here](https://example.com)"
        zones = _build_protected_zones(text)
        assert len(zones) > 0

    def test_bare_urls(self):
        text = "Visit https://example.com today"
        zones = _build_protected_zones(text)
        assert len(zones) > 0


class TestInProtectedZone:
    def test_in_zone(self):
        zones = [(5, 10), (20, 30)]
        assert _in_protected_zone(7, 9, zones) is True

    def test_not_in_zone(self):
        zones = [(5, 10), (20, 30)]
        assert _in_protected_zone(11, 15, zones) is False

    def test_overlapping_zone(self):
        zones = [(5, 10)]
        assert _in_protected_zone(8, 12, zones) is True

    def test_early_break(self):
        zones = [(5, 10), (20, 30)]
        assert _in_protected_zone(0, 3, zones) is False


class TestInjectWikilinks:
    def test_empty_terms(self):
        assert inject_wikilinks("Hello world", {}) == "Hello world"

    def test_basic_injection(self):
        terms = {"alice": "Alice"}
        result = inject_wikilinks("Talked to Alice today", terms)
        assert "[[Alice]]" in result

    def test_first_occurrence_only(self):
        terms = {"alice": "Alice"}
        result = inject_wikilinks("Alice met Alice", terms)
        assert result.count("[[Alice]]") == 1

    def test_protected_frontmatter(self):
        text = "---\ntitle: Alice\n---\nAlice was here"
        terms = {"alice": "Alice"}
        result = inject_wikilinks(text, terms)
        # Should not wikify in frontmatter, but should wikify in body
        assert "---\ntitle: Alice\n---" in result
        assert "[[Alice]] was here" in result

    def test_protected_code_block(self):
        text = "Before\n```\nAlice\n```\nAlice after"
        terms = {"alice": "Alice"}
        result = inject_wikilinks(text, terms)
        assert "```\nAlice\n```" in result

    def test_protected_inline_code(self):
        text = "`Alice` and Alice"
        terms = {"alice": "Alice"}
        result = inject_wikilinks(text, terms)
        assert "`Alice`" in result

    def test_protected_existing_wikilink(self):
        text = "[[Alice]] and Alice"
        terms = {"alice": "Alice"}
        result = inject_wikilinks(text, terms)
        # Both the existing wikilink and the first-occurrence linking are complex;
        # the key guarantee is no double-wrapping
        assert "[[[[" not in result

    def test_protected_markdown_link(self):
        text = "[Alice](https://alice.com) and Alice"
        terms = {"alice": "Alice"}
        result = inject_wikilinks(text, terms)
        assert "[Alice](https://alice.com)" in result

    def test_protected_url(self):
        text = "Visit https://alice.com then Alice"
        terms = {"alice": "Alice"}
        result = inject_wikilinks(text, terms)
        assert "https://alice.com" in result

    def test_word_boundary(self):
        terms = {"ice": "Ice"}
        result = inject_wikilinks("Alice likes ice cream", terms, min_length=3)
        # "ice" in "Alice" should not be matched due to word boundary
        assert result.count("[[Ice]]") == 1

    def test_longest_first_matching(self):
        terms = {"project": "Project", "project alpha": "Project Alpha"}
        result = inject_wikilinks("See Project Alpha here", terms)
        assert "[[Project Alpha]]" in result

    def test_min_length_filter(self):
        terms = {"ab": "AB", "abc": "ABC"}
        result = inject_wikilinks("AB and ABC here", terms, min_length=3)
        assert "[[ABC]]" in result
        # "AB" is too short
        assert "[[AB]]" not in result

    def test_all_terms_too_short(self):
        terms = {"ab": "AB"}
        result = inject_wikilinks("AB here", terms, min_length=3)
        assert result == "AB here"

    def test_case_insensitive(self):
        terms = {"alice": "Alice"}
        result = inject_wikilinks("ALICE was here", terms)
        assert "[[Alice]]" in result
