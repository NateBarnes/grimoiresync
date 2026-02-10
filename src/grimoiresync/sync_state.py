"""Track sync state to avoid re-syncing unchanged documents."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_DEFAULT_STATE_DIR = Path.home() / ".local" / "share" / "grimoiresync"
_DEFAULT_STATE_PATH = _DEFAULT_STATE_DIR / "sync_state.json"


class SyncState:
    """Persistent state tracking which documents have been synced."""

    def __init__(self, state_path: Path | None = None):
        self.path = state_path or _DEFAULT_STATE_PATH
        self._state: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._state = json.loads(self.path.read_text(encoding="utf-8"))
                log.debug("Loaded sync state with %d entries", len(self._state))
            except (json.JSONDecodeError, OSError):
                log.warning("Failed to load sync state, starting fresh")
                self._state = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._state, indent=2, default=str),
            encoding="utf-8",
        )

    def needs_sync(self, doc_id: str, updated_at: datetime) -> bool:
        """Check if a document needs to be synced."""
        entry = self._state.get(doc_id)
        if entry is None:
            return True
        prev = entry.get("updated_at", "")
        return prev != updated_at.isoformat()

    def record_sync(self, doc_id: str, updated_at: datetime, filename: str) -> None:
        """Record that a document has been synced."""
        self._state[doc_id] = {
            "updated_at": updated_at.isoformat(),
            "filename": filename,
            "synced_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        self._save()

    def get_previous_filename(self, doc_id: str) -> str | None:
        """Get the filename from the last sync for rename detection."""
        entry = self._state.get(doc_id)
        if entry:
            return entry.get("filename")
        return None
