"""Generate Obsidian-compatible markdown files from Granola documents."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

from .models import GranolaDocument
from .prosemirror import prosemirror_to_markdown

log = logging.getLogger(__name__)

# Characters not allowed in filenames
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\s*[-–—]\s*")


def make_filename(doc: GranolaDocument) -> str:
    """Generate a filename like 'YYYY-MM-DD - Title.md'."""
    title = doc.title or "Untitled Meeting"
    title = _INVALID_FILENAME_CHARS.sub("", title).strip()

    # Don't double the date if the title already starts with one
    if _DATE_PREFIX_RE.match(title):
        return f"{title}.md"

    date_str = doc.created_at.strftime("%Y-%m-%d")
    return f"{date_str} - {title}.md"


def build_frontmatter(doc: GranolaDocument) -> str:
    """Build YAML frontmatter for the document."""
    fm: dict = {
        "title": doc.title,
        "date": doc.created_at.isoformat(),
        "attendees": [a.name for a in doc.attendees] or [],
        "granola_id": doc.id,
        "tags": ["meeting", "granola"],
        "aliases": [doc.title],
    }

    return "---\n" + yaml.dump(fm, default_flow_style=False, allow_unicode=True, sort_keys=False) + "---"


def build_body(
    doc: GranolaDocument,
    *,
    include_panels: bool = True,
    include_transcript: bool = False,
) -> str:
    """Build the main body of the markdown note."""
    sections: list[str] = []

    # Attendees section
    if doc.attendees:
        attendee_lines = [f"- {a.name}" for a in doc.attendees]
        sections.append("## Attendees\n\n" + "\n".join(attendee_lines))

    # Notes
    notes_md = doc.notes_markdown
    if not notes_md and doc.notes_prosemirror:
        notes_md = prosemirror_to_markdown(doc.notes_prosemirror)

    if notes_md:
        sections.append("## Notes\n\n" + notes_md.strip())

    # AI Panels
    if include_panels and doc.panels:
        for panel in doc.panels:
            sections.append(f"## {panel.title}\n\n{panel.content_markdown.strip()}")

    # Transcript
    if include_transcript and doc.transcript:
        lines: list[str] = []
        for entry in doc.transcript:
            lines.append(f"**{entry.speaker}**: {entry.text}")
        transcript_text = "\n\n".join(lines)
        sections.append(
            "<details>\n<summary>Transcript</summary>\n\n"
            + transcript_text
            + "\n\n</details>"
        )

    return "\n\n".join(sections)


def assemble_note(
    doc: GranolaDocument,
    *,
    include_panels: bool = True,
    include_transcript: bool = False,
) -> str:
    """Assemble the complete markdown note."""
    frontmatter = build_frontmatter(doc)
    body = build_body(doc, include_panels=include_panels, include_transcript=include_transcript)
    return frontmatter + "\n\n" + body + "\n"


def write_note(
    doc: GranolaDocument,
    notes_dir: Path,
    content: str,
    *,
    dry_run: bool = False,
) -> Path:
    """Write the note to disk. Returns the path written."""
    filename = make_filename(doc)
    filepath = notes_dir / filename

    if dry_run:
        log.info("[DRY RUN] Would write %s (%d chars)", filepath, len(content))
        return filepath

    notes_dir.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content, encoding="utf-8")
    log.info("Wrote %s (%d chars)", filepath, len(content))
    return filepath
