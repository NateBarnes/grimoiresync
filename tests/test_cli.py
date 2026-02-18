"""Tests for grimoiresync.cli — main() argument parsing and dispatch."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from grimoiresync.cli import main


class TestCli:
    @patch("grimoiresync.cli.watch")
    @patch("grimoiresync.cli.SyncState")
    @patch("grimoiresync.cli.run_sync", return_value=3)
    @patch("grimoiresync.cli.load_config")
    def test_once_mode_prints_count(self, mock_load, mock_run, mock_state_cls, mock_watch, capsys):
        mock_load.return_value = MagicMock()
        main(["--once"])
        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["dry_run"] is False
        output = capsys.readouterr().out
        assert "3 note(s)" in output

    @patch("grimoiresync.cli.watch")
    @patch("grimoiresync.cli.SyncState")
    @patch("grimoiresync.cli.run_sync", return_value=0)
    @patch("grimoiresync.cli.load_config")
    def test_once_mode_up_to_date(self, mock_load, mock_run, mock_state_cls, mock_watch, capsys):
        mock_load.return_value = MagicMock()
        main(["--once"])
        output = capsys.readouterr().out
        assert "up to date" in output

    @patch("grimoiresync.cli.watch")
    @patch("grimoiresync.cli.SyncState")
    @patch("grimoiresync.cli.load_config")
    def test_daemon_mode(self, mock_load, mock_state_cls, mock_watch):
        mock_load.return_value = MagicMock()
        main([])
        mock_watch.assert_called_once()

    @patch("grimoiresync.cli.SyncState")
    @patch("grimoiresync.cli.run_sync", return_value=0)
    @patch("grimoiresync.cli.load_config")
    def test_verbose_sets_debug(self, mock_load, mock_run, mock_state_cls):
        mock_load.return_value = MagicMock()
        with patch("grimoiresync.cli.logging.basicConfig") as mock_bc:
            main(["--once", "--verbose"])
            mock_bc.assert_called_once()
            assert mock_bc.call_args.kwargs["level"] == logging.DEBUG

    @patch("grimoiresync.cli.SyncState")
    @patch("grimoiresync.cli.run_sync", return_value=0)
    @patch("grimoiresync.cli.load_config")
    def test_default_logging_info(self, mock_load, mock_run, mock_state_cls):
        mock_load.return_value = MagicMock()
        with patch("grimoiresync.cli.logging.basicConfig") as mock_bc:
            main(["--once"])
            assert mock_bc.call_args.kwargs["level"] == logging.INFO

    @patch("grimoiresync.cli.watch")
    @patch("grimoiresync.cli.SyncState")
    @patch("grimoiresync.cli.run_sync", return_value=0)
    @patch("grimoiresync.cli.load_config")
    def test_dry_run_forwarded(self, mock_load, mock_run, mock_state_cls, mock_watch):
        mock_load.return_value = MagicMock()
        main(["--once", "--dry-run"])
        assert mock_run.call_args.kwargs["dry_run"] is True

    @patch("grimoiresync.cli.watch")
    @patch("grimoiresync.cli.SyncState")
    @patch("grimoiresync.cli.run_sync", return_value=3)
    @patch("grimoiresync.cli.load_config")
    def test_force_calls_clear(self, mock_load, mock_run, mock_state_cls, mock_watch):
        mock_load.return_value = MagicMock()
        main(["--once", "--force"])
        mock_state_cls.return_value.clear.assert_called_once()

    @patch("grimoiresync.cli.watch")
    @patch("grimoiresync.cli.SyncState")
    @patch("grimoiresync.cli.run_sync", return_value=0)
    @patch("grimoiresync.cli.load_config")
    def test_no_force_does_not_clear(self, mock_load, mock_run, mock_state_cls, mock_watch):
        mock_load.return_value = MagicMock()
        main(["--once"])
        mock_state_cls.return_value.clear.assert_not_called()

    @patch("grimoiresync.cli.load_config")
    def test_config_path_forwarded(self, mock_load):
        mock_load.side_effect = FileNotFoundError("nope")
        with pytest.raises(SystemExit):
            main(["--config", "/custom/path.yaml", "--once"])
        mock_load.assert_called_once_with(Path("/custom/path.yaml"))

    @patch("grimoiresync.cli.load_config", side_effect=FileNotFoundError("not found"))
    def test_file_not_found_error(self, mock_load, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main(["--once"])
        assert exc_info.value.code == 1
        assert "not found" in capsys.readouterr().err

    @patch("grimoiresync.cli.load_config", side_effect=ValueError("bad config"))
    def test_value_error(self, mock_load, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main(["--once"])
        assert exc_info.value.code == 1
        assert "bad config" in capsys.readouterr().err


class TestMainModule:
    @patch("grimoiresync.cli.main")
    def test_dunder_main(self, mock_main):
        """__main__.py calls main() when executed."""
        import runpy
        runpy.run_module("grimoiresync", run_name="__main__", alter_sys=True)
        mock_main.assert_called_once()
