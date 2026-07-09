"""Tests for grimoiresync.api_client — chunked panel fetching."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from grimoiresync import api_client
from grimoiresync.api_client import _PANEL_BATCH_SIZE, _extract_panels, fetch_panels


def _panel_doc(doc_id: str) -> dict:
    """A batch-response doc carrying a ProseMirror panel for `doc_id`."""
    return {
        "id": doc_id,
        "last_viewed_panel": {
            "title": "Summary",
            "content": {"type": "doc", "content": [{"type": "paragraph"}]},
        },
    }


class _FakePostJson:
    """Stand-in for _post_json: records each chunk's IDs and echoes panels back.

    `fail_chunks` is a set of 0-based chunk indices whose response is None.
    """

    def __init__(self, fail_chunks: set[int] | None = None):
        self.fail_chunks = fail_chunks or set()
        self.calls: list[list[str]] = []

    def __call__(self, url, token, body, *, timeout: int = 30):
        ids = body["document_ids"]
        idx = len(self.calls)
        self.calls.append(ids)
        if idx in self.fail_chunks:
            return None
        return {"docs": [_panel_doc(i) for i in ids]}


@pytest.fixture(autouse=True)
def _fake_token(monkeypatch):
    monkeypatch.setattr(api_client, "get_access_token", lambda: "test-token")


class TestFetchPanelsChunking:
    def test_empty_doc_ids_makes_no_calls(self):
        with patch.object(api_client, "_post_json") as post:
            assert fetch_panels([]) == {}
        post.assert_not_called()

    def test_no_token_skips(self, monkeypatch):
        monkeypatch.setattr(api_client, "get_access_token", lambda: None)
        with patch.object(api_client, "_post_json") as post:
            assert fetch_panels(["a", "b"]) == {}
        post.assert_not_called()

    def test_single_chunk_when_under_limit(self):
        ids = [f"d{i}" for i in range(_PANEL_BATCH_SIZE)]
        fake = _FakePostJson()
        with patch.object(api_client, "_post_json", fake):
            result = fetch_panels(ids)
        assert len(fake.calls) == 1
        assert set(result) == set(ids)

    def test_splits_into_chunks_each_within_limit(self):
        ids = [f"d{i}" for i in range(_PANEL_BATCH_SIZE * 2 + 3)]
        fake = _FakePostJson()
        with patch.object(api_client, "_post_json", fake):
            result = fetch_panels(ids)
        # 3 chunks: limit, limit, remainder
        assert len(fake.calls) == 3
        assert all(len(chunk) <= _PANEL_BATCH_SIZE for chunk in fake.calls)
        # Every ID appears in exactly one chunk, and all are merged into results
        assert [i for chunk in fake.calls for i in chunk] == ids
        assert set(result) == set(ids)

    def test_failed_chunk_drops_only_its_own_ids(self):
        ids = [f"d{i}" for i in range(_PANEL_BATCH_SIZE * 2)]
        fake = _FakePostJson(fail_chunks={0})  # first chunk 400s
        with patch.object(api_client, "_post_json", fake):
            result = fetch_panels(ids)
        first_chunk = set(ids[:_PANEL_BATCH_SIZE])
        second_chunk = set(ids[_PANEL_BATCH_SIZE:])
        assert set(result) == second_chunk
        assert not (set(result) & first_chunk)

    def test_list_shaped_response_is_parsed(self):
        # Some deployments return a bare list instead of {"docs": [...]}
        def post(url, token, body, *, timeout: int = 30):
            return [_panel_doc(i) for i in body["document_ids"]]

        with patch.object(api_client, "_post_json", post):
            result = fetch_panels(["x", "y"])
        assert set(result) == {"x", "y"}


class TestExtractPanels:
    def test_prosemirror_content_kept_as_content(self):
        results: dict[str, dict] = {}
        _extract_panels([_panel_doc("a")], results)
        assert results["a"]["content"]["type"] == "doc"
        assert results["a"]["title"] == "Summary"

    def test_string_content_treated_as_html(self):
        doc = {"id": "a", "last_viewed_panel": {"title": "T", "content": "<p>hi</p>"}}
        results: dict[str, dict] = {}
        _extract_panels([doc], results)
        assert results["a"] == {"title": "T", "html": "<p>hi</p>"}

    def test_notes_markdown_fallback(self):
        doc = {"id": "a", "notes_markdown": "# Notes"}
        results: dict[str, dict] = {}
        _extract_panels([doc], results)
        assert results["a"] == {"title": "Summary", "markdown": "# Notes"}

    def test_doc_without_panel_or_notes_omitted(self):
        results: dict[str, dict] = {}
        _extract_panels([{"id": "a"}, {"no_id": True}, "not-a-dict"], results)
        assert results == {}
