"""Tests for grimoiresync.sync_engine — find_note_by_granola_id, run_sync."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from grimoiresync.config import Config
from grimoiresync.models import GranolaDocument
from grimoiresync.sync_engine import find_note_by_granola_id, run_sync


class TestFindNoteByGranolaId:
    def test_found_in_first_file(self, tmp_path):
        f = tmp_path / "note.md"
        f.write_text("Body\n\n| granola_id | abc123 |\n")
        result = find_note_by_granola_id(tmp_path, "abc123")
        assert result == f

    def test_found_in_second_file(self, tmp_path):
        (tmp_path / "a.md").write_text("Body\n\n| granola_id | other |\n")
        b = tmp_path / "b.md"
        b.write_text("Body\n\n| granola_id | target |\n")
        result = find_note_by_granola_id(tmp_path, "target")
        assert result == b

    def test_not_found(self, tmp_path):
        (tmp_path / "note.md").write_text("Body\n\n| granola_id | other |\n")
        result = find_note_by_granola_id(tmp_path, "missing")
        assert result is None

    def test_no_md_files(self, tmp_path):
        result = find_note_by_granola_id(tmp_path, "any")
        assert result is None

    def test_oserror_on_open_skipped(self, tmp_path):
        f = tmp_path / "note.md"
        f.write_text("Body\n\n| granola_id | target |\n")
        f.chmod(0o000)
        try:
            result = find_note_by_granola_id(tmp_path, "target")
            assert result is None
        finally:
            f.chmod(0o644)

    def test_granola_id_at_end_of_large_file(self, tmp_path):
        f = tmp_path / "note.md"
        # granola_id well past 1024 bytes — should still be found
        f.write_text("x" * 2000 + "\n| granola_id | target |\n")
        result = find_note_by_granola_id(tmp_path, "target")
        assert result == f


@pytest.fixture
def fixed_dt():
    return datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def make_doc(fixed_dt):
    def _make(doc_id="d1", title="Test Meeting", **kwargs):
        return GranolaDocument(
            id=doc_id,
            title=title,
            created_at=fixed_dt,
            updated_at=fixed_dt,
            **kwargs,
        )
    return _make


class TestRunSync:
    @patch("grimoiresync.sync_engine.parse_cache")
    def test_cache_not_found(self, mock_parse):
        cfg = Config(vault_path=Path("/vault"))
        cfg_cache = MagicMock()
        cfg_cache.exists.return_value = False
        cfg = Config(vault_path=Path("/vault"), granola_cache_path=cfg_cache)
        state = MagicMock()
        assert run_sync(cfg, state) == 0
        mock_parse.assert_not_called()

    @patch("grimoiresync.sync_engine.parse_cache", return_value=[])
    def test_no_documents(self, mock_parse):
        cfg = Config(vault_path=Path("/vault"))
        cfg = Config(vault_path=Path("/vault"), granola_cache_path=MagicMock(exists=MagicMock(return_value=True)))
        state = MagicMock()
        assert run_sync(cfg, state) == 0

    @patch("grimoiresync.sync_engine.write_note")
    @patch("grimoiresync.sync_engine.assemble_note", return_value="content")
    @patch("grimoiresync.sync_engine.make_filename", return_value="2024-06-15 - Test.md")
    @patch("grimoiresync.sync_engine.parse_cache")
    def test_all_up_to_date(self, mock_parse, mock_mkfn, mock_assemble, mock_write, make_doc):
        doc = make_doc()
        mock_parse.return_value = [doc]
        cfg = Config(vault_path=Path("/vault"), granola_cache_path=MagicMock(exists=MagicMock(return_value=True)))
        state = MagicMock()
        state.needs_sync.return_value = False
        assert run_sync(cfg, state) == 0
        mock_write.assert_not_called()

    @patch("grimoiresync.sync_engine.write_note")
    @patch("grimoiresync.sync_engine.assemble_note", return_value="content")
    @patch("grimoiresync.sync_engine.make_filename", return_value="2024-06-15 - Test.md")
    @patch("grimoiresync.sync_engine.parse_cache")
    def test_new_note_no_old_path(self, mock_parse, mock_mkfn, mock_assemble, mock_write, make_doc):
        doc = make_doc()
        mock_parse.return_value = [doc]
        cfg = Config(vault_path=Path("/vault"), granola_cache_path=MagicMock(exists=MagicMock(return_value=True)), auto_wikilinks=False)
        state = MagicMock()
        state.needs_sync.return_value = True
        state.get_previous_filename.return_value = None
        expected_path = Path("/vault/Meetings/2024-06-15 - Test.md")
        mock_write.return_value = expected_path

        with patch.object(Path, "exists", return_value=False):
            result = run_sync(cfg, state)

        assert result == 1
        mock_write.assert_called_once()
        state.record_sync.assert_called_once()

    @patch("grimoiresync.sync_engine.write_note")
    @patch("grimoiresync.sync_engine.assemble_note", return_value="content")
    @patch("grimoiresync.sync_engine.make_filename", return_value="2024-06-15 - Test.md")
    @patch("grimoiresync.sync_engine.parse_cache")
    def test_expected_path_exists(self, mock_parse, mock_mkfn, mock_assemble, mock_write, make_doc, tmp_path):
        doc = make_doc()
        mock_parse.return_value = [doc]
        vault = tmp_path / "vault"
        notes_dir = vault / "Meetings"
        notes_dir.mkdir(parents=True)
        expected = notes_dir / "2024-06-15 - Test.md"
        expected.write_text("old")
        cfg = Config(vault_path=vault, granola_cache_path=MagicMock(exists=MagicMock(return_value=True)), auto_wikilinks=False)
        state = MagicMock()
        state.needs_sync.return_value = True
        state.get_previous_filename.return_value = None
        mock_write.return_value = expected
        result = run_sync(cfg, state)
        assert result == 1
        # Should write to notes_dir since expected_path exists
        assert mock_write.call_args[0][1] == notes_dir

    @patch("grimoiresync.sync_engine.write_note")
    @patch("grimoiresync.sync_engine.assemble_note", return_value="content")
    @patch("grimoiresync.sync_engine.make_filename", return_value="2024-06-15 - Test.md")
    @patch("grimoiresync.sync_engine.parse_cache")
    def test_old_abs_exists_same_filename(self, mock_parse, mock_mkfn, mock_assemble, mock_write, make_doc, tmp_path):
        doc = make_doc()
        mock_parse.return_value = [doc]
        vault = tmp_path / "vault"
        notes_dir = vault / "Meetings"
        notes_dir.mkdir(parents=True)
        old_file = notes_dir / "2024-06-15 - Test.md"
        old_file.write_text("old content")
        cfg = Config(vault_path=vault, granola_cache_path=MagicMock(exists=MagicMock(return_value=True)), auto_wikilinks=False)
        state = MagicMock()
        state.needs_sync.return_value = True
        state.get_previous_filename.return_value = "2024-06-15 - Test.md"
        mock_write.return_value = old_file
        result = run_sync(cfg, state)
        assert result == 1
        assert mock_write.call_args[0][1] == notes_dir

    @patch("grimoiresync.sync_engine.write_note")
    @patch("grimoiresync.sync_engine.assemble_note", return_value="content")
    @patch("grimoiresync.sync_engine.make_filename", return_value="2024-06-15 - New Name.md")
    @patch("grimoiresync.sync_engine.parse_cache")
    def test_old_abs_exists_different_filename(self, mock_parse, mock_mkfn, mock_assemble, mock_write, make_doc, tmp_path):
        doc = make_doc()
        mock_parse.return_value = [doc]
        vault = tmp_path / "vault"
        notes_dir = vault / "Meetings"
        notes_dir.mkdir(parents=True)
        old_file = notes_dir / "2024-06-15 - Old Name.md"
        old_file.write_text("old")
        cfg = Config(vault_path=vault, granola_cache_path=MagicMock(exists=MagicMock(return_value=True)), auto_wikilinks=False)
        state = MagicMock()
        state.needs_sync.return_value = True
        state.get_previous_filename.return_value = "2024-06-15 - Old Name.md"
        mock_write.return_value = notes_dir / "2024-06-15 - New Name.md"
        result = run_sync(cfg, state)
        assert result == 1
        assert not old_file.exists()  # unlinked

    @patch("grimoiresync.sync_engine.write_note")
    @patch("grimoiresync.sync_engine.assemble_note", return_value="content")
    @patch("grimoiresync.sync_engine.make_filename", return_value="2024-06-15 - New Name.md")
    @patch("grimoiresync.sync_engine.parse_cache")
    def test_old_abs_exists_different_filename_dry_run(self, mock_parse, mock_mkfn, mock_assemble, mock_write, make_doc, tmp_path):
        doc = make_doc()
        mock_parse.return_value = [doc]
        vault = tmp_path / "vault"
        notes_dir = vault / "Meetings"
        notes_dir.mkdir(parents=True)
        old_file = notes_dir / "2024-06-15 - Old Name.md"
        old_file.write_text("old")
        cfg = Config(vault_path=vault, granola_cache_path=MagicMock(exists=MagicMock(return_value=True)), auto_wikilinks=False)
        state = MagicMock()
        state.needs_sync.return_value = True
        state.get_previous_filename.return_value = "2024-06-15 - Old Name.md"
        mock_write.return_value = notes_dir / "2024-06-15 - New Name.md"
        result = run_sync(cfg, state, dry_run=True)
        assert result == 1
        assert old_file.exists()  # NOT unlinked in dry_run
        state.record_sync.assert_not_called()

    @patch("grimoiresync.sync_engine.write_note")
    @patch("grimoiresync.sync_engine.assemble_note", return_value="content")
    @patch("grimoiresync.sync_engine.make_filename", return_value="2024-06-15 - Test.md")
    @patch("grimoiresync.sync_engine.parse_cache")
    def test_old_stored_path_with_slash(self, mock_parse, mock_mkfn, mock_assemble, mock_write, make_doc, tmp_path):
        doc = make_doc()
        mock_parse.return_value = [doc]
        vault = tmp_path / "vault"
        sub = vault / "Sub" / "Dir"
        sub.mkdir(parents=True)
        old_file = sub / "2024-06-15 - Test.md"
        old_file.write_text("old")
        cfg = Config(vault_path=vault, granola_cache_path=MagicMock(exists=MagicMock(return_value=True)), auto_wikilinks=False)
        state = MagicMock()
        state.needs_sync.return_value = True
        state.get_previous_filename.return_value = "Sub/Dir/2024-06-15 - Test.md"
        mock_write.return_value = old_file
        result = run_sync(cfg, state)
        assert result == 1
        assert mock_write.call_args[0][1] == sub

    @patch("grimoiresync.sync_engine.write_note")
    @patch("grimoiresync.sync_engine.assemble_note", return_value="content")
    @patch("grimoiresync.sync_engine.make_filename", return_value="2024-06-15 - Test.md")
    @patch("grimoiresync.sync_engine.parse_cache")
    def test_old_stored_path_with_backslash(self, mock_parse, mock_mkfn, mock_assemble, mock_write, make_doc, tmp_path):
        doc = make_doc()
        mock_parse.return_value = [doc]
        vault = tmp_path / "vault"
        sub = vault / "Sub" / "Dir"
        sub.mkdir(parents=True)
        old_file = sub / "2024-06-15 - Test.md"
        old_file.write_text("old")
        cfg = Config(vault_path=vault, granola_cache_path=MagicMock(exists=MagicMock(return_value=True)), auto_wikilinks=False)
        state = MagicMock()
        state.needs_sync.return_value = True
        state.get_previous_filename.return_value = "Sub\\Dir\\2024-06-15 - Test.md"
        mock_write.return_value = old_file
        result = run_sync(cfg, state)
        assert result == 1

    @patch("grimoiresync.sync_engine.write_note")
    @patch("grimoiresync.sync_engine.assemble_note", return_value="content")
    @patch("grimoiresync.sync_engine.make_filename", return_value="2024-06-15 - Test.md")
    @patch("grimoiresync.sync_engine.parse_cache")
    def test_old_stored_path_bare_filename(self, mock_parse, mock_mkfn, mock_assemble, mock_write, make_doc, tmp_path):
        doc = make_doc()
        mock_parse.return_value = [doc]
        vault = tmp_path / "vault"
        notes_dir = vault / "Meetings"
        notes_dir.mkdir(parents=True)
        old_file = notes_dir / "2024-06-15 - Test.md"
        old_file.write_text("old")
        cfg = Config(vault_path=vault, granola_cache_path=MagicMock(exists=MagicMock(return_value=True)), auto_wikilinks=False)
        state = MagicMock()
        state.needs_sync.return_value = True
        state.get_previous_filename.return_value = "2024-06-15 - Test.md"
        mock_write.return_value = old_file
        result = run_sync(cfg, state)
        assert result == 1

    @patch("grimoiresync.sync_engine.find_note_by_granola_id")
    @patch("grimoiresync.sync_engine.write_note")
    @patch("grimoiresync.sync_engine.assemble_note", return_value="content")
    @patch("grimoiresync.sync_engine.make_filename", return_value="2024-06-15 - Test.md")
    @patch("grimoiresync.sync_engine.parse_cache")
    def test_vault_search_finds_moved_note(self, mock_parse, mock_mkfn, mock_assemble, mock_write, mock_find, make_doc, tmp_path):
        doc = make_doc()
        mock_parse.return_value = [doc]
        vault = tmp_path / "vault"
        moved_dir = vault / "Archive"
        moved_dir.mkdir(parents=True)
        found_file = moved_dir / "2024-06-15 - Test.md"
        found_file.write_text("old")
        mock_find.return_value = found_file
        cfg = Config(vault_path=vault, granola_cache_path=MagicMock(exists=MagicMock(return_value=True)), auto_wikilinks=False)
        state = MagicMock()
        state.needs_sync.return_value = True
        state.get_previous_filename.return_value = "OldDir/old.md"

        # expected_path doesn't exist, old_abs doesn't exist -> vault search
        with patch.object(Path, "exists", return_value=False):
            mock_write.return_value = found_file
            result = run_sync(cfg, state)

        assert result == 1
        assert mock_write.call_args[0][1] == moved_dir

    @patch("grimoiresync.sync_engine.find_note_by_granola_id")
    @patch("grimoiresync.sync_engine.write_note")
    @patch("grimoiresync.sync_engine.assemble_note", return_value="content")
    @patch("grimoiresync.sync_engine.make_filename", return_value="2024-06-15 - New.md")
    @patch("grimoiresync.sync_engine.parse_cache")
    def test_vault_search_finds_moved_note_different_name(self, mock_parse, mock_mkfn, mock_assemble, mock_write, mock_find, make_doc, tmp_path):
        doc = make_doc()
        mock_parse.return_value = [doc]
        vault = tmp_path / "vault"
        moved_dir = vault / "Archive"
        moved_dir.mkdir(parents=True)
        found_file = moved_dir / "2024-06-15 - Old.md"
        found_file.write_text("old")
        mock_find.return_value = found_file
        cfg = Config(vault_path=vault, granola_cache_path=MagicMock(exists=MagicMock(return_value=True)), auto_wikilinks=False)
        state = MagicMock()
        state.needs_sync.return_value = True
        state.get_previous_filename.return_value = "OldDir/old.md"

        with patch.object(Path, "exists", return_value=False):
            mock_write.return_value = moved_dir / "2024-06-15 - New.md"
            result = run_sync(cfg, state)

        assert result == 1
        assert not found_file.exists()  # unlinked

    @patch("grimoiresync.sync_engine.find_note_by_granola_id")
    @patch("grimoiresync.sync_engine.write_note")
    @patch("grimoiresync.sync_engine.assemble_note", return_value="content")
    @patch("grimoiresync.sync_engine.make_filename", return_value="2024-06-15 - New.md")
    @patch("grimoiresync.sync_engine.parse_cache")
    def test_vault_search_moved_note_dry_run(self, mock_parse, mock_mkfn, mock_assemble, mock_write, mock_find, make_doc, tmp_path):
        doc = make_doc()
        mock_parse.return_value = [doc]
        vault = tmp_path / "vault"
        moved_dir = vault / "Archive"
        moved_dir.mkdir(parents=True)
        found_file = moved_dir / "2024-06-15 - Old.md"
        found_file.write_text("old")
        mock_find.return_value = found_file
        cfg = Config(vault_path=vault, granola_cache_path=MagicMock(exists=MagicMock(return_value=True)), auto_wikilinks=False)
        state = MagicMock()
        state.needs_sync.return_value = True
        state.get_previous_filename.return_value = "OldDir/old.md"

        with patch.object(Path, "exists", return_value=False):
            mock_write.return_value = moved_dir / "2024-06-15 - New.md"
            result = run_sync(cfg, state, dry_run=True)

        assert result == 1
        assert found_file.exists()  # NOT unlinked
        state.record_sync.assert_not_called()

    @patch("grimoiresync.sync_engine.find_note_by_granola_id", return_value=None)
    @patch("grimoiresync.sync_engine.write_note")
    @patch("grimoiresync.sync_engine.assemble_note", return_value="content")
    @patch("grimoiresync.sync_engine.make_filename", return_value="2024-06-15 - Test.md")
    @patch("grimoiresync.sync_engine.parse_cache")
    def test_vault_search_finds_nothing(self, mock_parse, mock_mkfn, mock_assemble, mock_write, mock_find, make_doc, tmp_path):
        doc = make_doc()
        mock_parse.return_value = [doc]
        vault = tmp_path / "vault"
        vault.mkdir()
        notes_dir = vault / "Meetings"
        cfg = Config(vault_path=vault, granola_cache_path=MagicMock(exists=MagicMock(return_value=True)), auto_wikilinks=False)
        state = MagicMock()
        state.needs_sync.return_value = True
        state.get_previous_filename.return_value = "OldDir/old.md"

        with patch.object(Path, "exists", return_value=False):
            mock_write.return_value = notes_dir / "2024-06-15 - Test.md"
            result = run_sync(cfg, state)

        assert result == 1
        assert mock_write.call_args[0][1] == notes_dir

    @patch("grimoiresync.sync_engine.inject_wikilinks", return_value="wikified content")
    @patch("grimoiresync.sync_engine.scan_vault_terms", return_value={"alice": "Alice"})
    @patch("grimoiresync.sync_engine.write_note")
    @patch("grimoiresync.sync_engine.assemble_note", return_value="content about Alice")
    @patch("grimoiresync.sync_engine.make_filename", return_value="2024-06-15 - Test.md")
    @patch("grimoiresync.sync_engine.parse_cache")
    def test_wikilinks_enabled(self, mock_parse, mock_mkfn, mock_assemble, mock_write, mock_scan, mock_inject, make_doc, tmp_path):
        doc = make_doc()
        mock_parse.return_value = [doc]
        vault = tmp_path / "vault"
        vault.mkdir()
        cfg = Config(vault_path=vault, granola_cache_path=MagicMock(exists=MagicMock(return_value=True)), auto_wikilinks=True)
        state = MagicMock()
        state.needs_sync.return_value = True
        state.get_previous_filename.return_value = None
        mock_write.return_value = vault / "Meetings" / "2024-06-15 - Test.md"

        with patch.object(Path, "exists", return_value=False):
            run_sync(cfg, state)

        mock_scan.assert_called_once()
        mock_inject.assert_called_once()

    @patch("grimoiresync.sync_engine.scan_vault_terms")
    @patch("grimoiresync.sync_engine.write_note")
    @patch("grimoiresync.sync_engine.assemble_note", return_value="content")
    @patch("grimoiresync.sync_engine.make_filename", return_value="2024-06-15 - Test.md")
    @patch("grimoiresync.sync_engine.parse_cache")
    def test_wikilinks_disabled(self, mock_parse, mock_mkfn, mock_assemble, mock_write, mock_scan, make_doc, tmp_path):
        doc = make_doc()
        mock_parse.return_value = [doc]
        vault = tmp_path / "vault"
        vault.mkdir()
        cfg = Config(vault_path=vault, granola_cache_path=MagicMock(exists=MagicMock(return_value=True)), auto_wikilinks=False)
        state = MagicMock()
        state.needs_sync.return_value = True
        state.get_previous_filename.return_value = None
        mock_write.return_value = vault / "Meetings" / "2024-06-15 - Test.md"

        with patch.object(Path, "exists", return_value=False):
            run_sync(cfg, state)

        mock_scan.assert_not_called()

    @patch("grimoiresync.sync_engine.inject_wikilinks")
    @patch("grimoiresync.sync_engine.scan_vault_terms", return_value={})
    @patch("grimoiresync.sync_engine.write_note")
    @patch("grimoiresync.sync_engine.assemble_note", return_value="content")
    @patch("grimoiresync.sync_engine.make_filename", return_value="2024-06-15 - Test.md")
    @patch("grimoiresync.sync_engine.parse_cache")
    def test_wikilinks_enabled_no_terms(self, mock_parse, mock_mkfn, mock_assemble, mock_write, mock_scan, mock_inject, make_doc, tmp_path):
        doc = make_doc()
        mock_parse.return_value = [doc]
        vault = tmp_path / "vault"
        vault.mkdir()
        cfg = Config(vault_path=vault, granola_cache_path=MagicMock(exists=MagicMock(return_value=True)), auto_wikilinks=True)
        state = MagicMock()
        state.needs_sync.return_value = True
        state.get_previous_filename.return_value = None
        mock_write.return_value = vault / "Meetings" / "2024-06-15 - Test.md"

        with patch.object(Path, "exists", return_value=False):
            run_sync(cfg, state)

        mock_inject.assert_not_called()

    @patch("grimoiresync.sync_engine.write_note")
    @patch("grimoiresync.sync_engine.assemble_note", return_value="content")
    @patch("grimoiresync.sync_engine.make_filename", return_value="2024-06-15 - Test.md")
    @patch("grimoiresync.sync_engine.parse_cache")
    def test_record_sync_with_vault_relative_path(self, mock_parse, mock_mkfn, mock_assemble, mock_write, make_doc, tmp_path):
        doc = make_doc()
        mock_parse.return_value = [doc]
        vault = tmp_path / "vault"
        notes_dir = vault / "Meetings"
        notes_dir.mkdir(parents=True)
        expected = notes_dir / "2024-06-15 - Test.md"
        expected.write_text("old")
        cfg = Config(vault_path=vault, granola_cache_path=MagicMock(exists=MagicMock(return_value=True)), auto_wikilinks=False)
        state = MagicMock()
        state.needs_sync.return_value = True
        state.get_previous_filename.return_value = None
        mock_write.return_value = expected
        run_sync(cfg, state)
        # record_sync should receive vault-relative path
        rel_path = state.record_sync.call_args[0][2]
        assert rel_path == "Meetings/2024-06-15 - Test.md"

    @patch("grimoiresync.sync_engine.write_note", side_effect=Exception("write failed"))
    @patch("grimoiresync.sync_engine.assemble_note", return_value="content")
    @patch("grimoiresync.sync_engine.make_filename", return_value="2024-06-15 - Test.md")
    @patch("grimoiresync.sync_engine.parse_cache")
    def test_exception_during_doc_processing(self, mock_parse, mock_mkfn, mock_assemble, mock_write, make_doc, tmp_path):
        doc1 = make_doc(doc_id="d1")
        doc2 = make_doc(doc_id="d2")
        mock_parse.return_value = [doc1, doc2]
        vault = tmp_path / "vault"
        vault.mkdir()
        cfg = Config(vault_path=vault, granola_cache_path=MagicMock(exists=MagicMock(return_value=True)), auto_wikilinks=False)
        state = MagicMock()
        state.needs_sync.return_value = True
        state.get_previous_filename.return_value = None

        with patch.object(Path, "exists", return_value=False):
            result = run_sync(cfg, state)

        # Both fail, so 0 written
        assert result == 0

    @patch("grimoiresync.sync_engine.write_note")
    @patch("grimoiresync.sync_engine.assemble_note", return_value="content")
    @patch("grimoiresync.sync_engine.make_filename", return_value="2024-06-15 - Test.md")
    @patch("grimoiresync.sync_engine.parse_cache")
    def test_multiple_docs_mixed(self, mock_parse, mock_mkfn, mock_assemble, mock_write, make_doc, tmp_path):
        doc1 = make_doc(doc_id="d1")
        doc2 = make_doc(doc_id="d2")
        doc3 = make_doc(doc_id="d3")
        mock_parse.return_value = [doc1, doc2, doc3]
        vault = tmp_path / "vault"
        vault.mkdir()
        cfg = Config(vault_path=vault, granola_cache_path=MagicMock(exists=MagicMock(return_value=True)), auto_wikilinks=False)
        state = MagicMock()
        state.needs_sync.side_effect = lambda doc_id, _: doc_id != "d2"
        state.get_previous_filename.return_value = None
        mock_write.return_value = vault / "Meetings" / "2024-06-15 - Test.md"

        with patch.object(Path, "exists", return_value=False):
            result = run_sync(cfg, state)

        assert result == 2  # d1 and d3, not d2
