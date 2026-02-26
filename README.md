# GrimoireSync

Sync [Granola](https://www.granola.ai/) meeting notes to [Obsidian](https://obsidian.md/) with automatic `[[wikilinks]]`.

GrimoireSync watches Granola's local cache file for changes and writes each meeting as a clean Obsidian-compatible markdown note, complete with attendees, AI-generated panels, and optional transcripts. It scans your vault for existing note titles and wikilinks, then injects `[[wikilinks]]` into the synced notes so they integrate into your knowledge graph automatically.

## Features

- **Live sync** -- watches the Granola cache file and syncs on change (with debounce)
- **Auto-wikilinks** -- scans your vault for note titles and existing `[[links]]`, then injects them into synced notes
- **AI panels** -- includes Granola's AI-generated summaries (action items, key decisions, etc.)
- **Transcripts** -- optionally includes the full transcript in a collapsible `<details>` block
- **Rename detection** -- if a meeting title changes in Granola, the old file is removed and replaced
- **Incremental sync** -- tracks what's already been synced and only writes changed notes
- **Dry run mode** -- preview what would be written without touching your vault

## Requirements

- Python 3.12+
- macOS (reads Granola's cache from `~/Library/Application Support/Granola/cache-v4.json`)
- A Granola account with local cache enabled
- An Obsidian vault

## Installation

```bash
git clone https://github.com/NateBarnes/grimoiresync.git
cd grimoiresync
pip install -e .
```

## Configuration

Create a config file at `~/.config/grimoiresync/config.yaml`:

```yaml
# Required: path to your Obsidian vault
vault_path: ~/Documents/ObsidianVault

# Subfolder within the vault for meeting notes (default: "Meetings")
notes_subfolder: Meetings

# Include AI-generated summary panels (default: true)
include_panels: true

# Include raw transcript in a collapsible section (default: false)
include_transcript: false

# Auto-generate [[wikilinks]] based on existing vault content (default: true)
auto_wikilinks: true

# Minimum term length for wikilink injection (default: 3)
min_wikilink_length: 3
```

An example config is included in `config.example.yaml`.

## Usage

Start the watcher daemon:

```bash
grimoiresync
```

This runs an initial sync, then watches the Granola cache file for changes. Press `Ctrl+C` to stop.

Run a one-shot sync:

```bash
grimoiresync --once
```

Preview without writing files:

```bash
grimoiresync --dry-run --once
```

Force a full re-sync (clears sync state and re-syncs all notes):

```bash
grimoiresync --once --force
```

### Options

| Flag | Description |
|------|-------------|
| `--once` | Run a single sync pass and exit |
| `--dry-run` | Show what would be written without writing files |
| `--force`, `-f` | Clear sync state and re-sync all notes from scratch |
| `--config`, `-c` | Path to config YAML (default: `~/.config/grimoiresync/config.yaml`) |
| `--verbose`, `-v` | Enable debug logging |

## How it works

1. **Parse** -- Reads Granola's double-encoded JSON cache and extracts meeting documents, attendees, AI panels, and transcripts
2. **Convert** -- Transforms ProseMirror JSON and HTML content into clean markdown
3. **Wikify** -- Scans your vault for note titles and existing wikilinks, then injects `[[wikilinks]]` into the note body (respecting code blocks, URLs, and existing links)
4. **Write** -- Saves each meeting as `YYYY-MM-DD - Title.md` in your configured vault subfolder
5. **Watch** -- Monitors the cache file for changes and re-syncs with a 2-second debounce
