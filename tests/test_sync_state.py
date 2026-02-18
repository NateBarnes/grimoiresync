"""Tests for grimoiresync.sync_state — SyncState persistence and sync tracking."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from grimoiresync.sync_state import SyncState


class TestSyncStateInit:
    def test_default_path(self):
        with patch.object(Path, "exists", return_value=False):
            s = SyncState()
        assert "sync_state.json" in str(s.path)

    def test_custom_path(self, tmp_path):
        p = tmp_path / "state.json"
        s = SyncState(state_path=p)
        assert s.path == p

    def test_valid_json_loaded(self, tmp_path):
        p = tmp_path / "state.json"
        data = {"doc1": {"updated_at": "2024-01-01T00:00:00", "filename": "f.md"}}
        p.write_text(json.dumps(data))
        s = SyncState(state_path=p)
        assert "doc1" in s._state

    def test_file_missing_empty_state(self, tmp_path):
        p = tmp_path / "nonexistent.json"
        s = SyncState(state_path=p)
        assert s._state == {}

    def test_corrupt_json_empty_state(self, tmp_path):
        p = tmp_path / "state.json"
        p.write_text("not json{{{")
        s = SyncState(state_path=p)
        assert s._state == {}

    def test_oserror_on_read_empty_state(self, tmp_path):
        p = tmp_path / "state.json"
        p.write_text("{}")
        p.chmod(0o000)
        try:
            s = SyncState(state_path=p)
            assert s._state == {}
        finally:
            p.chmod(0o644)


class TestNeedsSync:
    def test_new_doc_id(self, tmp_path):
        s = SyncState(state_path=tmp_path / "s.json")
        dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
        assert s.needs_sync("new-doc", dt) is True

    def test_matching_updated_at(self, tmp_path):
        p = tmp_path / "s.json"
        dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
        data = {"d1": {"updated_at": dt.isoformat()}}
        p.write_text(json.dumps(data))
        s = SyncState(state_path=p)
        assert s.needs_sync("d1", dt) is False

    def test_different_updated_at(self, tmp_path):
        p = tmp_path / "s.json"
        old = datetime(2024, 1, 1, tzinfo=timezone.utc)
        new = datetime(2024, 6, 1, tzinfo=timezone.utc)
        data = {"d1": {"updated_at": old.isoformat()}}
        p.write_text(json.dumps(data))
        s = SyncState(state_path=p)
        assert s.needs_sync("d1", new) is True

    def test_entry_missing_updated_at_key(self, tmp_path):
        p = tmp_path / "s.json"
        data = {"d1": {"filename": "f.md"}}  # no updated_at
        p.write_text(json.dumps(data))
        s = SyncState(state_path=p)
        dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
        assert s.needs_sync("d1", dt) is True


class TestRecordSync:
    def test_stores_entry_and_saves(self, tmp_path):
        p = tmp_path / "state.json"
        s = SyncState(state_path=p)
        dt = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

        with patch("grimoiresync.sync_state.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2024, 6, 15, 13, 0, 0, tzinfo=timezone.utc)
            # Keep isoformat working on the real datetime
            s.record_sync("d1", dt, "Meetings/note.md")

        assert p.exists()
        saved = json.loads(p.read_text())
        assert saved["d1"]["updated_at"] == dt.isoformat()
        assert saved["d1"]["filename"] == "Meetings/note.md"
        assert "synced_at" in saved["d1"]

    def test_save_creates_parent_dir(self, tmp_path):
        p = tmp_path / "sub" / "dir" / "state.json"
        s = SyncState(state_path=p)
        dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
        s.record_sync("d1", dt, "f.md")
        assert p.parent.exists()
        assert p.exists()


class TestClear:
    def test_clear_resets_state_and_saves(self, tmp_path):
        p = tmp_path / "state.json"
        data = {"d1": {"updated_at": "2024-01-01", "filename": "f.md"}}
        p.write_text(json.dumps(data))
        s = SyncState(state_path=p)
        assert s._state != {}

        s.clear()

        assert s._state == {}
        saved = json.loads(p.read_text())
        assert saved == {}

    def test_clear_makes_all_docs_need_sync(self, tmp_path):
        p = tmp_path / "state.json"
        dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
        data = {"d1": {"updated_at": dt.isoformat()}}
        p.write_text(json.dumps(data))
        s = SyncState(state_path=p)
        assert s.needs_sync("d1", dt) is False

        s.clear()

        assert s.needs_sync("d1", dt) is True


class TestGetPreviousFilename:
    def test_existing_entry(self, tmp_path):
        p = tmp_path / "s.json"
        data = {"d1": {"filename": "old.md"}}
        p.write_text(json.dumps(data))
        s = SyncState(state_path=p)
        assert s.get_previous_filename("d1") == "old.md"

    def test_no_entry(self, tmp_path):
        s = SyncState(state_path=tmp_path / "s.json")
        assert s.get_previous_filename("missing") is None

    def test_entry_without_filename_key(self, tmp_path):
        p = tmp_path / "s.json"
        data = {"d1": {"updated_at": "2024-01-01"}}
        p.write_text(json.dumps(data))
        s = SyncState(state_path=p)
        assert s.get_previous_filename("d1") is None
