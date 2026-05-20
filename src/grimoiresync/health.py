"""Detect and flag silent grimoiresync failures.

Granola updates have repeatedly broken grimoiresync silently (cache path version
bumps, encryption changes, panel format shifts). This module runs a small set of
detection rules on startup and after each sync, and surfaces failures via macOS
notifications + a loud `[HEALTH]` log line — so a regression is noticeable
within one sync cycle instead of days later.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import Config
from .models import GranolaDocument
from .sync_state import SyncState

log = logging.getLogger(__name__)

_DEFAULT_HEALTH_DIR = Path.home() / ".local" / "share" / "grimoiresync"
_DEFAULT_HEALTH_PATH = _DEFAULT_HEALTH_DIR / "health_state.json"

# Re-fire the same alert at most once per this window (across processes).
_ALERT_COOLDOWN = timedelta(hours=6)

# All-empty-content rule requires at least this many fetched docs before it
# fires, so a single legitimate empty meeting doesn't trip the alarm.
_EMPTY_CONTENT_MIN_DOCS = 3

_CACHE_VERSION_RE = re.compile(r"^cache-v(\d+)\.json(\.enc)?$")


@dataclass
class Alert:
    rule: str
    message: str


@dataclass
class SyncObservation:
    """What HealthMonitor needs to know about one sync pass to evaluate rules."""

    documents: list[GranolaDocument] = field(default_factory=list)
    source: str | None = None  # "API", "cache", or None when both failed
    fetched_was_none: bool = False  # both API and cache returned None


class HealthMonitor:
    """Runs detection rules and surfaces alerts via macOS notification + log.

    State (alert dedupe + decryption history) is persisted to
    ~/.local/share/grimoiresync/health_state.json so deduplication survives
    process restarts within the cooldown window.
    """

    def __init__(
        self,
        state_path: Path | None = None,
        *,
        sync_state: SyncState | None = None,
        notifier=None,
        clock=None,
    ):
        self.path = state_path or _DEFAULT_HEALTH_PATH
        self._sync_state = sync_state
        self._notifier = notifier or _osascript_notify
        self._clock = clock or (lambda: datetime.now(tz=timezone.utc))
        self._state: dict = {"alerted": {}, "last_decryption_ok": None}
        self._load()
        # Per-process dedupe: rules fire at most once per process even if the
        # persisted cooldown has expired between syncs.
        self._fired_this_process: set[str] = set()

    # ---- persistence ---------------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._state.update(data)
                self._state.setdefault("alerted", {})
        except (json.JSONDecodeError, OSError):
            log.warning("health_state.json unreadable, starting fresh")

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._state, indent=2), encoding="utf-8")
        except OSError:
            log.warning("Failed to write health_state.json", exc_info=True)

    # ---- public API ----------------------------------------------------------

    def attach_sync_state(self, sync_state: SyncState) -> None:
        """Late-bind a SyncState so rule 1 (zero-docs regression) can run.

        Used when the singleton was instantiated before the watcher had a
        SyncState in hand (e.g. crypto called get_monitor() during a prior sync).
        """
        self._sync_state = sync_state

    def check_startup(self, config: Config) -> list[Alert]:
        """Run startup-only rules. Currently: unknown cache version scan."""
        alerts: list[Alert] = []
        a = self._check_unknown_cache_version(config)
        if a:
            alerts.append(a)
        for alert in alerts:
            self._emit(alert)
        return alerts

    def record_sync(self, observation: SyncObservation) -> list[Alert]:
        """Run post-sync rules against a SyncObservation."""
        alerts: list[Alert] = []
        for check in (
            self._check_both_fetch_paths_failed,
            self._check_zero_docs_regression,
            self._check_all_empty_content,
        ):
            a = check(observation)
            if a:
                alerts.append(a)
        for alert in alerts:
            self._emit(alert)
        return alerts

    def record_decryption(self, success: bool, what: str = "supabase token") -> Alert | None:
        """Rule 5: decryption regression.

        Track the most recent decryption outcome. Only alert on the transition
        from "previously worked" → "now fails" — first-time failures (e.g. fresh
        install before Keychain access is granted) are not flagged here.
        """
        if success:
            self._state["last_decryption_ok"] = self._now_iso()
            self._save()
            return None

        if not self._state.get("last_decryption_ok"):
            return None

        alert = Alert(
            rule="decryption_regression",
            message=(
                f"Granola {what} decryption was working but now fails — "
                "Granola may have changed its encryption scheme."
            ),
        )
        if self._emit(alert):
            return alert
        return None

    # ---- rules ---------------------------------------------------------------

    def _check_unknown_cache_version(self, config: Config) -> Alert | None:
        cache_dir = config.granola_cache_path.parent
        if not cache_dir.exists():
            return None

        configured_version = _extract_cache_version(config.granola_cache_path.name)
        if configured_version is None:
            return None

        newer: list[str] = []
        for entry in cache_dir.iterdir():
            version = _extract_cache_version(entry.name)
            if version is not None and version > configured_version:
                newer.append(entry.name)

        if not newer:
            return None

        return Alert(
            rule="unknown_cache_version",
            message=(
                f"Granola wrote newer cache file(s) {sorted(set(newer))} but "
                f"grimoiresync is configured for cache-v{configured_version}. "
                "Update granola_cache_path or the parser."
            ),
        )

    def _check_both_fetch_paths_failed(self, obs: SyncObservation) -> Alert | None:
        if not obs.fetched_was_none:
            return None
        return Alert(
            rule="fetch_unavailable",
            message=(
                "Neither the Granola API nor the local cache returned any data. "
                "Granola may not be running, or its storage format has changed."
            ),
        )

    def _check_zero_docs_regression(self, obs: SyncObservation) -> Alert | None:
        if obs.fetched_was_none:
            # already covered by _check_both_fetch_paths_failed; don't double-fire
            return None
        if len(obs.documents) > 0:
            return None
        if self._sync_state is None or not _state_has_history(self._sync_state):
            return None
        return Alert(
            rule="zero_docs_regression",
            message=(
                "Granola returned 0 documents but grimoiresync has synced notes "
                "before — Granola's storage path or format likely changed."
            ),
        )

    def _check_all_empty_content(self, obs: SyncObservation) -> Alert | None:
        if len(obs.documents) < _EMPTY_CONTENT_MIN_DOCS:
            return None
        if any(_doc_has_content(d) for d in obs.documents):
            return None
        return Alert(
            rule="all_empty_content",
            message=(
                f"All {len(obs.documents)} fetched Granola documents have empty "
                "panels, notes, and transcript — panel/note format may have "
                "changed."
            ),
        )

    # ---- emission ------------------------------------------------------------

    def _emit(self, alert: Alert) -> bool:
        """Fire the alert if not deduped. Returns True if it actually fired."""
        if alert.rule in self._fired_this_process:
            return False
        last_iso = self._state["alerted"].get(alert.rule)
        if last_iso and _parse_iso(last_iso) is not None:
            elapsed = self._clock() - _parse_iso(last_iso)
            if elapsed < _ALERT_COOLDOWN:
                # Still log so the failure is visible to anyone tailing logs,
                # but don't re-spam notifications.
                log.error("[HEALTH] %s (suppressed notify): %s", alert.rule, alert.message)
                self._fired_this_process.add(alert.rule)
                return False

        log.error("[HEALTH] %s: %s", alert.rule, alert.message)
        self._notifier(alert)
        self._fired_this_process.add(alert.rule)
        self._state["alerted"][alert.rule] = self._now_iso()
        self._save()
        return True

    def _now_iso(self) -> str:
        return self._clock().isoformat()


# ---- helpers (module-level so they're trivially testable) --------------------


def _extract_cache_version(name: str) -> int | None:
    m = _CACHE_VERSION_RE.match(name)
    return int(m.group(1)) if m else None


def _state_has_history(state: SyncState) -> bool:
    # SyncState exposes only `needs_sync` / `record_sync` publicly. Reach into
    # `_state` to ask "have we ever synced anything?" — this is the cleanest
    # signal without expanding the SyncState API for one caller.
    return bool(getattr(state, "_state", None))


def _doc_has_content(doc: GranolaDocument) -> bool:
    if doc.panels:
        return True
    if doc.notes_markdown and doc.notes_markdown.strip():
        return True
    if doc.transcript:
        return True
    return False


def _parse_iso(s: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _osascript_notify(alert: Alert) -> None:
    """Fire a macOS Notification Center popup. No-op on non-macOS hosts."""
    if sys.platform != "darwin":
        return
    msg = _applescript_escape(alert.message)
    rule = _applescript_escape(alert.rule)
    script = (
        f'display notification "{msg}" '
        f'with title "grimoiresync" subtitle "{rule}"'
    )
    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=False,
            timeout=5,
            capture_output=True,
        )
    except (OSError, subprocess.SubprocessError):
        # Notification is best-effort — never propagate.
        log.debug("osascript notification failed", exc_info=True)


def _applescript_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


# ---- process-wide singleton --------------------------------------------------
#
# Crypto code (granola_crypto.load_supabase_token) needs to report decryption
# outcomes without holding a reference to the watcher-owned monitor. Expose a
# lazily-initialized singleton so any module can reach the same instance.

_monitor: HealthMonitor | None = None


def get_monitor() -> HealthMonitor:
    global _monitor
    if _monitor is None:
        _monitor = HealthMonitor()
    return _monitor


def reset_monitor() -> None:
    """Test helper: clear the singleton so each test gets a fresh monitor."""
    global _monitor
    _monitor = None
