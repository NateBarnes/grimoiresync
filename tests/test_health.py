"""Tests for grimoiresync.health — detection rules and notifier dedupe."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from grimoiresync.config import Config
from grimoiresync.health import (
    Alert,
    HealthMonitor,
    SyncObservation,
    _applescript_escape,
    _extract_cache_version,
    _osascript_notify as _real_osascript_notify,
    get_monitor,
    reset_monitor,
)
from grimoiresync.models import DocumentPanel, GranolaDocument, TranscriptEntry
from grimoiresync.sync_state import SyncState


@pytest.fixture
def health_path(tmp_path: Path) -> Path:
    return tmp_path / "health_state.json"


@pytest.fixture
def recording_notifier():
    calls: list[Alert] = []

    def notify(alert: Alert) -> None:
        calls.append(alert)

    notify.calls = calls  # type: ignore[attr-defined]
    return notify


@pytest.fixture
def fake_clock():
    """Advanceable UTC clock for testing dedupe windows."""

    class Clock:
        def __init__(self) -> None:
            self.now = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)

        def __call__(self) -> datetime:
            return self.now

        def advance(self, **kw) -> None:
            self.now = self.now + timedelta(**kw)

    return Clock()


def _make_monitor(health_path, notifier, clock, sync_state=None) -> HealthMonitor:
    return HealthMonitor(
        state_path=health_path,
        sync_state=sync_state,
        notifier=notifier,
        clock=clock,
    )


def _make_doc(doc_id: str, *, panels=None, notes="", transcript=None) -> GranolaDocument:
    now = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)
    return GranolaDocument(
        id=doc_id,
        title=f"Doc {doc_id}",
        created_at=now,
        updated_at=now,
        notes_markdown=notes,
        panels=panels or [],
        transcript=transcript or [],
    )


def _cfg_with_cache(tmp_path: Path, cache_name: str = "cache-v6.json") -> Config:
    cache_dir = tmp_path / "Granola"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return Config(
        vault_path=tmp_path / "vault",
        granola_cache_path=cache_dir / cache_name,
    )


# ---- helpers ----------------------------------------------------------------


class TestExtractCacheVersion:
    def test_plain_json(self):
        assert _extract_cache_version("cache-v6.json") == 6

    def test_encrypted(self):
        assert _extract_cache_version("cache-v6.json.enc") == 6

    def test_double_digit(self):
        assert _extract_cache_version("cache-v12.json") == 12

    def test_non_matching(self):
        assert _extract_cache_version("supabase.json.enc") is None
        assert _extract_cache_version("cache-v6.txt") is None
        assert _extract_cache_version("granola.db") is None


class TestApplescriptEscape:
    def test_quotes_escaped(self):
        assert _applescript_escape('hello "world"') == 'hello \\"world\\"'

    def test_backslashes_escaped(self):
        assert _applescript_escape("path\\to\\thing") == "path\\\\to\\\\thing"


# ---- Rule 3: unknown cache version (startup) --------------------------------


class TestUnknownCacheVersion:
    def test_no_newer_versions_no_alert(self, tmp_path, health_path, recording_notifier, fake_clock):
        cfg = _cfg_with_cache(tmp_path)
        (cfg.granola_cache_path.parent / "cache-v6.json").touch()
        (cfg.granola_cache_path.parent / "cache-v6.json.enc").touch()
        (cfg.granola_cache_path.parent / "supabase.json.enc").touch()
        monitor = _make_monitor(health_path, recording_notifier, fake_clock)

        alerts = monitor.check_startup(cfg)

        assert alerts == []
        assert recording_notifier.calls == []

    def test_newer_version_fires(self, tmp_path, health_path, recording_notifier, fake_clock):
        cfg = _cfg_with_cache(tmp_path)
        (cfg.granola_cache_path.parent / "cache-v6.json").touch()
        (cfg.granola_cache_path.parent / "cache-v7.json").touch()
        monitor = _make_monitor(health_path, recording_notifier, fake_clock)

        alerts = monitor.check_startup(cfg)

        assert len(alerts) == 1
        assert alerts[0].rule == "unknown_cache_version"
        assert "cache-v7.json" in alerts[0].message
        assert len(recording_notifier.calls) == 1

    def test_encrypted_newer_version_fires(self, tmp_path, health_path, recording_notifier, fake_clock):
        cfg = _cfg_with_cache(tmp_path)
        (cfg.granola_cache_path.parent / "cache-v8.json.enc").touch()
        monitor = _make_monitor(health_path, recording_notifier, fake_clock)

        alerts = monitor.check_startup(cfg)

        assert len(alerts) == 1
        assert "cache-v8.json.enc" in alerts[0].message

    def test_missing_cache_dir_silent(self, tmp_path, health_path, recording_notifier, fake_clock):
        cfg = Config(
            vault_path=tmp_path / "vault",
            granola_cache_path=tmp_path / "nope" / "cache-v6.json",
        )
        monitor = _make_monitor(health_path, recording_notifier, fake_clock)

        alerts = monitor.check_startup(cfg)

        assert alerts == []


# ---- Rule 4: both fetch paths failed ----------------------------------------


class TestBothFetchPathsFailed:
    def test_fired_when_both_none(self, health_path, recording_notifier, fake_clock):
        monitor = _make_monitor(health_path, recording_notifier, fake_clock)
        obs = SyncObservation(documents=[], source=None, fetched_was_none=True)

        alerts = monitor.record_sync(obs)

        rule_names = {a.rule for a in alerts}
        assert "fetch_unavailable" in rule_names
        # zero_docs_regression must NOT also fire (would be redundant)
        assert "zero_docs_regression" not in rule_names

    def test_not_fired_when_fetched_ok(self, health_path, recording_notifier, fake_clock):
        monitor = _make_monitor(health_path, recording_notifier, fake_clock)
        obs = SyncObservation(documents=[_make_doc("d1")], source="API")

        alerts = monitor.record_sync(obs)

        assert all(a.rule != "fetch_unavailable" for a in alerts)


# ---- Rule 1: zero-docs regression -------------------------------------------


class TestZeroDocsRegression:
    def test_fires_when_state_has_history(self, tmp_path, health_path, recording_notifier, fake_clock):
        state = SyncState(state_path=tmp_path / "sync_state.json")
        state.record_sync(
            "prior-doc",
            datetime(2026, 5, 1, tzinfo=timezone.utc),
            "Meetings/old.md",
        )
        monitor = _make_monitor(health_path, recording_notifier, fake_clock, sync_state=state)
        obs = SyncObservation(documents=[], source="API")

        alerts = monitor.record_sync(obs)

        rules = {a.rule for a in alerts}
        assert "zero_docs_regression" in rules

    def test_does_not_fire_on_fresh_install(self, tmp_path, health_path, recording_notifier, fake_clock):
        state = SyncState(state_path=tmp_path / "sync_state.json")
        monitor = _make_monitor(health_path, recording_notifier, fake_clock, sync_state=state)
        obs = SyncObservation(documents=[], source="API")

        alerts = monitor.record_sync(obs)

        assert all(a.rule != "zero_docs_regression" for a in alerts)

    def test_does_not_fire_when_docs_present(self, tmp_path, health_path, recording_notifier, fake_clock):
        state = SyncState(state_path=tmp_path / "sync_state.json")
        state.record_sync(
            "prior-doc",
            datetime(2026, 5, 1, tzinfo=timezone.utc),
            "Meetings/old.md",
        )
        monitor = _make_monitor(health_path, recording_notifier, fake_clock, sync_state=state)
        obs = SyncObservation(documents=[_make_doc("d1")], source="API")

        alerts = monitor.record_sync(obs)

        assert all(a.rule != "zero_docs_regression" for a in alerts)


# ---- Rule 2: all-empty content ----------------------------------------------


class TestAllEmptyContent:
    def test_fires_when_all_three_docs_empty(self, health_path, recording_notifier, fake_clock):
        monitor = _make_monitor(health_path, recording_notifier, fake_clock)
        docs = [_make_doc(f"d{i}") for i in range(3)]
        obs = SyncObservation(documents=docs, source="API")

        alerts = monitor.record_sync(obs)

        rules = {a.rule for a in alerts}
        assert "all_empty_content" in rules

    def test_does_not_fire_if_one_doc_has_panels(self, health_path, recording_notifier, fake_clock):
        monitor = _make_monitor(health_path, recording_notifier, fake_clock)
        docs = [_make_doc(f"d{i}") for i in range(3)]
        docs[1].panels = [DocumentPanel(title="Summary", content_markdown="something")]
        obs = SyncObservation(documents=docs, source="API")

        alerts = monitor.record_sync(obs)

        assert all(a.rule != "all_empty_content" for a in alerts)

    def test_does_not_fire_if_doc_has_notes(self, health_path, recording_notifier, fake_clock):
        monitor = _make_monitor(health_path, recording_notifier, fake_clock)
        docs = [_make_doc(f"d{i}") for i in range(3)]
        docs[0].notes_markdown = "real notes"
        obs = SyncObservation(documents=docs, source="API")

        alerts = monitor.record_sync(obs)

        assert all(a.rule != "all_empty_content" for a in alerts)

    def test_does_not_fire_if_doc_has_transcript(self, health_path, recording_notifier, fake_clock):
        monitor = _make_monitor(health_path, recording_notifier, fake_clock)
        docs = [_make_doc(f"d{i}") for i in range(3)]
        docs[2].transcript = [TranscriptEntry(speaker="A", text="hi")]
        obs = SyncObservation(documents=docs, source="API")

        alerts = monitor.record_sync(obs)

        assert all(a.rule != "all_empty_content" for a in alerts)

    def test_does_not_fire_below_threshold(self, health_path, recording_notifier, fake_clock):
        monitor = _make_monitor(health_path, recording_notifier, fake_clock)
        docs = [_make_doc(f"d{i}") for i in range(2)]
        obs = SyncObservation(documents=docs, source="API")

        alerts = monitor.record_sync(obs)

        assert all(a.rule != "all_empty_content" for a in alerts)


# ---- Rule 5: decryption regression ------------------------------------------


class TestDecryptionRegression:
    def test_first_failure_does_not_alert(self, health_path, recording_notifier, fake_clock):
        monitor = _make_monitor(health_path, recording_notifier, fake_clock)

        alert = monitor.record_decryption(success=False)

        assert alert is None
        assert recording_notifier.calls == []

    def test_alert_on_transition_from_ok_to_fail(self, health_path, recording_notifier, fake_clock):
        monitor = _make_monitor(health_path, recording_notifier, fake_clock)
        monitor.record_decryption(success=True)

        alert = monitor.record_decryption(success=False)

        assert alert is not None
        assert alert.rule == "decryption_regression"
        assert len(recording_notifier.calls) == 1

    def test_success_does_not_alert(self, health_path, recording_notifier, fake_clock):
        monitor = _make_monitor(health_path, recording_notifier, fake_clock)

        alert = monitor.record_decryption(success=True)

        assert alert is None
        assert recording_notifier.calls == []

    def test_state_persists_across_monitors(self, health_path, recording_notifier, fake_clock):
        m1 = _make_monitor(health_path, recording_notifier, fake_clock)
        m1.record_decryption(success=True)

        m2 = _make_monitor(health_path, recording_notifier, fake_clock)
        alert = m2.record_decryption(success=False)

        assert alert is not None


# ---- Dedupe ------------------------------------------------------------------


class TestAlertDedupe:
    def test_per_process_dedupe(self, health_path, recording_notifier, fake_clock):
        monitor = _make_monitor(health_path, recording_notifier, fake_clock)
        docs = [_make_doc(f"d{i}") for i in range(3)]
        obs = SyncObservation(documents=docs, source="API")

        monitor.record_sync(obs)
        monitor.record_sync(obs)

        # all_empty_content should have fired exactly once
        rule_calls = [a for a in recording_notifier.calls if a.rule == "all_empty_content"]
        assert len(rule_calls) == 1

    def test_cooldown_dedupe_across_processes(self, health_path, recording_notifier, fake_clock):
        m1 = _make_monitor(health_path, recording_notifier, fake_clock)
        m1.record_sync(SyncObservation(documents=[], source=None, fetched_was_none=True))

        # Fresh monitor (simulates daemon restart) within cooldown — no re-fire.
        fake_clock.advance(hours=1)
        m2 = _make_monitor(health_path, recording_notifier, fake_clock)
        m2.record_sync(SyncObservation(documents=[], source=None, fetched_was_none=True))

        fetch_calls = [a for a in recording_notifier.calls if a.rule == "fetch_unavailable"]
        assert len(fetch_calls) == 1

    def test_cooldown_expires(self, health_path, recording_notifier, fake_clock):
        m1 = _make_monitor(health_path, recording_notifier, fake_clock)
        m1.record_sync(SyncObservation(documents=[], source=None, fetched_was_none=True))

        # Advance past the 6-hour cooldown, then re-fire from a fresh monitor.
        fake_clock.advance(hours=7)
        m2 = _make_monitor(health_path, recording_notifier, fake_clock)
        m2.record_sync(SyncObservation(documents=[], source=None, fetched_was_none=True))

        fetch_calls = [a for a in recording_notifier.calls if a.rule == "fetch_unavailable"]
        assert len(fetch_calls) == 2


# ---- Notifier integration ---------------------------------------------------


class TestNotifierInvocation:
    def test_osascript_invoked_on_darwin(self, health_path, fake_clock, monkeypatch):
        import grimoiresync.health as health_mod

        calls: list[list[str]] = []

        def fake_run(args, **kwargs):
            calls.append(args)
            return MagicMock(returncode=0)

        monkeypatch.setattr(health_mod.sys, "platform", "darwin")
        monkeypatch.setattr(health_mod.subprocess, "run", fake_run)

        monitor = HealthMonitor(
            state_path=health_path, clock=fake_clock, notifier=_real_osascript_notify
        )
        monitor.record_sync(SyncObservation(documents=[], source=None, fetched_was_none=True))

        assert calls, "osascript was not invoked"
        assert calls[0][0] == "osascript"
        assert "fetch_unavailable" in calls[0][-1]

    def test_noop_on_non_darwin(self, health_path, fake_clock, monkeypatch):
        import grimoiresync.health as health_mod

        calls: list[list[str]] = []

        def fake_run(args, **kwargs):
            calls.append(args)
            return MagicMock(returncode=0)

        monkeypatch.setattr(health_mod.sys, "platform", "linux")
        monkeypatch.setattr(health_mod.subprocess, "run", fake_run)

        monitor = HealthMonitor(
            state_path=health_path, clock=fake_clock, notifier=_real_osascript_notify
        )
        monitor.record_sync(SyncObservation(documents=[], source=None, fetched_was_none=True))

        assert calls == []


# ---- Singleton --------------------------------------------------------------


class TestSingleton:
    def test_get_monitor_returns_same_instance(self):
        reset_monitor()
        m1 = get_monitor()
        m2 = get_monitor()
        assert m1 is m2
        reset_monitor()

    def test_reset_clears_singleton(self):
        reset_monitor()
        m1 = get_monitor()
        reset_monitor()
        m2 = get_monitor()
        assert m1 is not m2
        reset_monitor()
