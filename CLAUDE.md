# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

GrimoireSync watches Granola's local cache/API and writes each meeting as an Obsidian-compatible markdown note, injecting `[[wikilinks]]` based on existing vault content. macOS-only (reads Keychain and Granola's app-support directory). Python 3.12+, packaged with hatchling, dependency-managed with `uv`.

## Commands

```bash
# install (editable, with test extras)
uv sync --extra test

# run the full test suite
uv run --extra test pytest

# run a single test file / test
uv run --extra test pytest tests/test_sync_engine.py
uv run --extra test pytest tests/test_sync_engine.py::test_specific_case -v

# run the CLI locally
uv run grimoiresync --once --dry-run
uv run grimoiresync --once -v
```

There is no configured linter/type-checker (no ruff/mypy config in `pyproject.toml`) and no CI workflow in this repo — `pytest` is the only automated check.

## Architecture

### Data flow

`cli.py` loads `Config` (from `~/.config/grimoiresync/config.yaml` by default) and either runs one `run_sync` pass (`--once`) or hands off to `watcher.watch`, which does an initial sync and then blocks on a `watchdog` observer.

`sync_engine.run_sync` is the orchestrator, and follows this pipeline per pass:

1. **Fetch** — `_fetch_via_api` (Granola's HTTP API, via `api_client.py`) is tried first; `_fetch_via_cache` (parsing Granola's local cache JSON directly, via `cache_parser.py`) is the fallback when the API is unavailable or returns nothing. Both paths funnel through `cache_parser._parse_document`, so the two sources produce identical `GranolaDocument` shapes.
2. **Diff** — `SyncState.needs_sync` compares each doc's `updated_at` against the persisted state (`~/.local/share/grimoiresync/sync_state.json`) to compute the set of docs that actually need re-syncing. AI panels are only fetched (`fetch_panels`) for docs that need syncing, not for the whole set — panel fetches are the expensive call.
3. **Render** — `note_writer.assemble_note` turns a `GranolaDocument` into markdown (attendees, AI panels or raw notes as fallback, optional transcript, trailing metadata table with `granola_id` for later lookup).
4. **Wikify** — if `auto_wikilinks` is on, `wikilinks.scan_vault_terms` scans the vault once per sync pass for existing note titles / `[[links]]`, then `inject_wikilinks` rewrites the rendered note, skipping frontmatter, code blocks, existing links, and bare URLs.
5. **Write** — `note_writer.write_note` decides the target path. Rename/move detection: if the doc's previously-recorded filename no longer matches the new title, `run_sync` looks for the old file (by stored relative path, then by scanning the vault for the doc's `granola_id` in the metadata table via `find_note_by_granola_id`) and removes/replaces it rather than duplicating the note.

### Granola's storage format has changed multiple times, and the codebase defends against that

- `granola_crypto.py` documents and implements the current (encrypted) storage scheme: Keychain-stored secret → PBKDF2 → AES-128-CBC-decrypt `storage.dek` → AES-256-GCM-decrypt `cache-v6.json.enc` / `supabase.json.enc`. `cache_parser.py` still supports the older plain-JSON, double-encoded cache format (`outer["cache"]` is itself a JSON string) as a fallback path — see `_fetch_via_cache`.
- `api_client.get_access_token` prefers the encrypted `supabase.json.enc` and falls back to the legacy plaintext `supabase.json`.
- AI panel content has been observed in at least three shapes (ProseMirror JSON, raw HTML, pre-rendered markdown) across Granola versions; `_parse_document` and `api_client.fetch_panels` both branch on the actual shape returned rather than assuming one.
- `health.py` exists specifically because Granola updates have silently broken sync before (cache path bumped, encryption introduced, panel format changed). It runs a small rule engine after every sync pass (`HealthMonitor.record_sync`) plus a startup check (`check_startup`) and fires a deduped macOS notification + `[HEALTH]` log line when something looks wrong (both fetch paths failed, docs count regressed to zero, all fetched docs have empty content, decryption started failing, or a doc has failed to write 3+ times in a row). When touching `cache_parser.py`, `api_client.py`, or `granola_crypto.py`, consider whether a new failure mode needs a corresponding rule here.
- `note_writer._write_with_edeadlk_recovery` works around macOS file-provider "dataless placeholder" files (e.g. iCloud-backed vaults) that raise `EDEADLK` on a truncating write; it materializes the file by reading it first, and unlinks the stub as a last resort before retrying the write.

### Other notable pieces

- `sync_state.py` is deliberately narrow (`needs_sync` / `record_sync` / `get_previous_filename` / `clear`) — `health.py` reaches into its private `_state` dict (`_state_has_history`) rather than the API growing a method for one caller.
- `health.get_monitor()` / `reset_monitor()` is a process-wide singleton because `granola_crypto.load_supabase_token` needs to report decryption outcomes without holding a reference to the watcher-owned `HealthMonitor` instance.
- `prosemirror.py` converts Granola's ProseMirror JSON (used for notes and sometimes panels) to markdown; `note_writer.py` has a separate `_HtmlToMarkdown` HTML-tag-walking converter for panel content delivered as HTML strings; `cache_parser.py` also has its own smaller `_html_to_markdown` for one specific API panel shape. These are intentionally separate small converters per format, not a shared abstraction.
- `SyncResult` (`sync_engine.py`) overloads `__eq__`/`__bool__`/`__int__` so that older call sites and tests written against a plain `int` return value (`assert run_sync(...) == N`) keep working even though the return value now also carries `documents`/`source`/`fetched_was_none` for `health.py` to consume.

## Testing conventions

- `tests/conftest.py` provides shared fixtures (`sample_document`, `minimal_document`, `sample_config`, etc.) and an autouse `_isolate_health_monitor` fixture that resets the `HealthMonitor` singleton and redirects its state file to `tmp_path` for every test — health-related side effects (macOS notifications, real `~/.local/share` writes) never leak into tests.
- Each `src/grimoiresync/<module>.py` has a corresponding `tests/test_<module>.py`.
