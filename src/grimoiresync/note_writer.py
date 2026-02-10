"""Generate Obsidian-compatible markdown files from Granola documents."""

from __future__ import annotations

import html as html_mod
import html.parser
import logging
import re
from pathlib import Path

import yaml

from .models import GranolaDocument
from .prosemirror import prosemirror_to_markdown

log = logging.getLogger(__name__)


class _HtmlToMarkdown(html.parser.HTMLParser):
    """Convert HTML to markdown by walking the tag structure."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._list_stack: list[tuple[str, int]] = []  # (tag, counter)
        self._href: str | None = None
        self._link_text: list[str] = []
        self._in_link = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        match tag:
            case "h1" | "h2" | "h3" | "h4" | "h5" | "h6":
                level = int(tag[1])
                self._parts.append(f"\n{'#' * level} ")
            case "ul":
                self._list_stack.append(("ul", 0))
            case "ol":
                self._list_stack.append(("ol", 0))
            case "li":
                if self._list_stack:
                    list_tag, counter = self._list_stack[-1]
                    counter += 1
                    self._list_stack[-1] = (list_tag, counter)
                    indent = "  " * (len(self._list_stack) - 1)
                    prefix = f"{counter}." if list_tag == "ol" else "-"
                    self._parts.append(f"\n{indent}{prefix} ")
            case "a":
                href = dict(attrs).get("href", "")
                self._href = href
                self._in_link = True
                self._link_text = []
            case "hr":
                self._parts.append("\n\n---\n")
            case "p":
                self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        match tag:
            case "h1" | "h2" | "h3" | "h4" | "h5" | "h6":
                self._parts.append("\n")
            case "ul" | "ol":
                if self._list_stack:
                    self._list_stack.pop()
                if not self._list_stack:
                    self._parts.append("\n")
            case "a":
                text = "".join(self._link_text)
                self._parts.append(f"[{text}]({self._href})")
                self._in_link = False
                self._href = None
            case "p":
                self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_link:
            self._link_text.append(data)
        else:
            self._parts.append(data)

    def handle_entityref(self, name: str) -> None:
        char = html_mod.unescape(f"&{name};")
        self.handle_data(char)

    def handle_charref(self, name: str) -> None:
        char = html_mod.unescape(f"&#{name};")
        self.handle_data(char)

    def get_markdown(self) -> str:
        text = "".join(self._parts)
        # Collapse all runs of blank lines to a single newline
        text = re.sub(r"\n{2,}", "\n", text)
        # Re-add a blank line before headings for readability
        text = re.sub(r"\n(#{1,6} )", r"\n\n\1", text)
        return text.strip()


def html_to_markdown(text: str) -> str:
    """Convert HTML tags found in Granola panel content to markdown."""
    # Quick check: if no HTML tags, return as-is
    if "<" not in text:
        return text

    parser = _HtmlToMarkdown()
    parser.feed(text)
    return parser.get_markdown()

# Characters not allowed in filenames
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[\s\-–—]")


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

    # AI Panels (preferred) or user notes (fallback)
    if include_panels and doc.panels:
        for panel in doc.panels:
            content = html_to_markdown(panel.content_markdown.strip())
            sections.append(f"## {panel.title}\n\n{content}")
    else:
        notes_md = doc.notes_markdown
        if not notes_md and doc.notes_prosemirror:
            notes_md = prosemirror_to_markdown(doc.notes_prosemirror)
        if notes_md:
            sections.append(notes_md.strip())

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
    body = build_body(doc, include_panels=include_panels, include_transcript=include_transcript)
    return body + "\n"


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
