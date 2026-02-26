"""Tests for grimoiresync.watcher — _CacheEventHandler and watch()."""

from __future__ import annotations

import signal
import threading
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from grimoiresync.config import Config
from grimoiresync.sync_state import SyncState
from grimoiresync.watcher import _CacheEventHandler, watch


@pytest.fixture
def watcher_config(tmp_path):
    cache_file = tmp_path / "cache" / "cache-v4.json"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_text("{}")
    return Config(
        vault_path=tmp_path / "vault",
        granola_cache_path=cache_file,
    )


@pytest.fixture
def mock_state():
    return MagicMock(spec=SyncState)


class TestCacheEventHandler:
    def test_on_modified_directory_ignored(self, watcher_config, mock_state):
        handler = _CacheEventHandler(watcher_config, mock_state)
        event = MagicMock()
        event.is_directory = True
        handler.on_modified(event)
        # No sync scheduled - check timer is still None
        assert handler._timer is None

    def test_on_modified_wrong_file_ignored(self, watcher_config, mock_state):
        handler = _CacheEventHandler(watcher_config, mock_state)
        event = MagicMock()
        event.is_directory = False
        event.src_path = "/some/other/file.txt"
        handler.on_modified(event)
        assert handler._timer is None

    def test_on_modified_correct_file_schedules_sync(self, watcher_config, mock_state):
        handler = _CacheEventHandler(watcher_config, mock_state)
        event = MagicMock()
        event.is_directory = False
        event.src_path = str(watcher_config.granola_cache_path)

        with patch("grimoiresync.watcher.threading.Timer") as MockTimer:
            mock_timer = MagicMock()
            MockTimer.return_value = mock_timer
            handler.on_modified(event)
            MockTimer.assert_called_once()
            mock_timer.start.assert_called_once()

    def test_schedule_sync_cancels_previous_timer(self, watcher_config, mock_state):
        handler = _CacheEventHandler(watcher_config, mock_state)
        event = MagicMock()
        event.is_directory = False
        event.src_path = str(watcher_config.granola_cache_path)

        with patch("grimoiresync.watcher.threading.Timer") as MockTimer:
            first_timer = MagicMock()
            second_timer = MagicMock()
            MockTimer.side_effect = [first_timer, second_timer]
            handler.on_modified(event)
            handler.on_modified(event)
            first_timer.cancel.assert_called_once()
            second_timer.start.assert_called_once()

    @patch("grimoiresync.watcher.run_sync")
    def test_do_sync_calls_run_sync(self, mock_run, watcher_config, mock_state):
        handler = _CacheEventHandler(watcher_config, mock_state, dry_run=True)
        handler._do_sync()
        mock_run.assert_called_once_with(watcher_config, mock_state, dry_run=True)

    @patch("grimoiresync.watcher.run_sync", side_effect=Exception("boom"))
    def test_do_sync_exception_logged(self, mock_run, watcher_config, mock_state):
        handler = _CacheEventHandler(watcher_config, mock_state)
        # Should not raise
        handler._do_sync()


class TestWatch:
    @patch("grimoiresync.watcher.run_sync")
    def test_cache_dir_not_exists(self, mock_run, mock_state, tmp_path):
        cfg = Config(
            vault_path=tmp_path / "vault",
            granola_cache_path=tmp_path / "nonexistent" / "cache.json",
        )
        with pytest.raises(SystemExit):
            watch(cfg, mock_state)

    @patch("grimoiresync.watcher.time.sleep")
    @patch("grimoiresync.watcher.signal.signal")
    @patch("grimoiresync.watcher.Observer")
    @patch("grimoiresync.watcher.run_sync")
    def test_initial_sync_called(self, mock_run, MockObserver, mock_signal, mock_sleep, watcher_config, mock_state):
        mock_sleep.side_effect = SystemExit  # break the loop immediately
        mock_obs = MagicMock()
        MockObserver.return_value = mock_obs
        with pytest.raises(SystemExit):
            watch(watcher_config, mock_state)
        mock_run.assert_called_once_with(watcher_config, mock_state, dry_run=False)

    @patch("grimoiresync.watcher.time.sleep")
    @patch("grimoiresync.watcher.signal.signal")
    @patch("grimoiresync.watcher.Observer")
    @patch("grimoiresync.watcher.run_sync")
    def test_observer_started_and_stopped(self, mock_run, MockObserver, mock_signal, mock_sleep, watcher_config, mock_state):
        mock_sleep.side_effect = SystemExit
        mock_obs = MagicMock()
        MockObserver.return_value = mock_obs
        with pytest.raises(SystemExit):
            watch(watcher_config, mock_state)
        mock_obs.start.assert_called_once()
        mock_obs.stop.assert_called_once()
        mock_obs.join.assert_called_once()

    @patch("grimoiresync.watcher.time.sleep")
    @patch("grimoiresync.watcher.signal.signal")
    @patch("grimoiresync.watcher.Observer")
    @patch("grimoiresync.watcher.run_sync")
    def test_signal_handlers_registered(self, mock_run, MockObserver, mock_signal, mock_sleep, watcher_config, mock_state):
        mock_sleep.side_effect = SystemExit
        mock_obs = MagicMock()
        MockObserver.return_value = mock_obs
        with pytest.raises(SystemExit):
            watch(watcher_config, mock_state)
        sig_calls = [c[0][0] for c in mock_signal.call_args_list]
        assert signal.SIGINT in sig_calls
        assert signal.SIGTERM in sig_calls

    @patch("grimoiresync.watcher.time.sleep")
    @patch("grimoiresync.watcher.signal.signal")
    @patch("grimoiresync.watcher.Observer")
    @patch("grimoiresync.watcher.run_sync")
    def test_shutdown_handler_sets_stop_event(self, mock_run, MockObserver, mock_signal, mock_sleep, watcher_config, mock_state):
        captured_handler = None

        def capture_signal(signum, handler):
            nonlocal captured_handler
            if signum == signal.SIGINT:
                captured_handler = handler

        mock_signal.side_effect = capture_signal
        mock_obs = MagicMock()
        MockObserver.return_value = mock_obs

        # Make sleep check stop_event so loop exits after signal
        call_count = 0
        def sleep_side_effect(_):
            nonlocal call_count
            call_count += 1
            if call_count == 1 and captured_handler:
                captured_handler(signal.SIGINT, None)
            elif call_count > 1:
                pass  # stop_event should be set, loop will exit

        mock_sleep.side_effect = sleep_side_effect
        watch(watcher_config, mock_state)
        mock_obs.stop.assert_called_once()

    @patch("grimoiresync.watcher.time.sleep")
    @patch("grimoiresync.watcher.signal.signal")
    @patch("grimoiresync.watcher.Observer")
    @patch("grimoiresync.watcher.run_sync")
    def test_dry_run_forwarded(self, mock_run, MockObserver, mock_signal, mock_sleep, watcher_config, mock_state):
        mock_sleep.side_effect = SystemExit
        mock_obs = MagicMock()
        MockObserver.return_value = mock_obs
        with pytest.raises(SystemExit):
            watch(watcher_config, mock_state, dry_run=True)
        mock_run.assert_called_once_with(watcher_config, mock_state, dry_run=True)
