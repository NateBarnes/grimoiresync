"""Watchdog-based daemon that monitors the Granola cache file."""

from __future__ import annotations

import logging
import signal
import threading
import time

from watchdog.events import FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .config import Config
from .sync_engine import run_sync
from .sync_state import SyncState

log = logging.getLogger(__name__)

_DEBOUNCE_SECONDS = 2.0


class _CacheEventHandler(FileSystemEventHandler):
    """Watches for modifications to the Granola cache file."""

    def __init__(self, config: Config, state: SyncState, *, dry_run: bool = False):
        super().__init__()
        self._config = config
        self._state = state
        self._dry_run = dry_run
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def on_modified(self, event: FileModifiedEvent) -> None:  # type: ignore[override]
        if event.is_directory:
            return
        # Only react to the cache file itself
        if not str(event.src_path).endswith(self._config.granola_cache_path.name):
            return

        log.debug("Cache file modified, scheduling sync in %.1fs", _DEBOUNCE_SECONDS)
        self._schedule_sync()

    def _schedule_sync(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(_DEBOUNCE_SECONDS, self._do_sync)
            self._timer.daemon = True
            self._timer.start()

    def _do_sync(self) -> None:
        try:
            run_sync(self._config, self._state, dry_run=self._dry_run)
        except Exception:
            log.error("Sync failed", exc_info=True)


def watch(config: Config, state: SyncState, *, dry_run: bool = False) -> None:
    """Start watching the Granola cache file. Blocks until interrupted."""
    cache_dir = config.granola_cache_path.parent

    if not cache_dir.exists():
        log.error("Cache directory does not exist: %s", cache_dir)
        raise SystemExit(1)

    # Initial sync on startup
    log.info("Running initial sync...")
    run_sync(config, state, dry_run=dry_run)

    handler = _CacheEventHandler(config, state, dry_run=dry_run)
    observer = Observer()
    observer.schedule(handler, str(cache_dir), recursive=False)

    stop_event = threading.Event()

    def _shutdown(signum: int, frame: object) -> None:
        sig_name = signal.Signals(signum).name
        log.info("Received %s, shutting down...", sig_name)
        stop_event.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    observer.start()
    log.info("Watching %s for changes (Ctrl+C to stop)", config.granola_cache_path)

    try:
        while not stop_event.is_set():
            time.sleep(1)
    finally:
        observer.stop()
        observer.join()
        log.info("Watcher stopped")
