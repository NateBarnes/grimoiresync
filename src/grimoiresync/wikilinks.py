"""Wikilink engine: scan vault for terms and inject [[wikilinks]] into markdown."""

from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

# Patterns for protected zones that should not be wikified
_FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---", re.DOTALL)
_FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]+`")
_EXISTING_WIKILINK_RE = re.compile(r"\[\[[^\]]+\]\]")
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]+\)")
_BARE_URL_RE = re.compile(r"https?://\S+")


def scan_vault_terms(vault_path: Path, min_length: int = 3) -> dict[str, str]:
    """Scan the vault for wikilink targets and filenames.

    Returns a dict mapping lowercase term -> canonical form.
    """
    terms: dict[str, str] = {}

    for md_file in vault_path.rglob("*.md"):
        # Add filename stem as a term
        stem = md_file.stem
        if len(stem) >= min_length:
            terms.setdefault(stem.lower(), stem)

        # Scan file contents for existing [[wikilinks]]
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        for match in _EXISTING_WIKILINK_RE.finditer(content):
            raw = match.group(0)[2:-2]  # Strip [[ and ]]
            # Handle [[target|display]] - use target
            target = raw.split("|")[0].strip()
            if len(target) >= min_length:
                terms.setdefault(target.lower(), target)

    log.debug("Scanned vault: found %d unique terms", len(terms))
    return terms


def _build_protected_zones(text: str) -> list[tuple[int, int]]:
    """Find all regions of text that should not be modified."""
    zones: list[tuple[int, int]] = []

    for pattern in (
        _FRONTMATTER_RE,
        _FENCED_CODE_RE,
        _INLINE_CODE_RE,
        _EXISTING_WIKILINK_RE,
        _MARKDOWN_LINK_RE,
        _BARE_URL_RE,
    ):
        for m in pattern.finditer(text):
            zones.append((m.start(), m.end()))

    # Sort by start position
    zones.sort()
    return zones


def _in_protected_zone(pos: int, end: int, zones: list[tuple[int, int]]) -> bool:
    """Check if a position range overlaps with any protected zone."""
    for z_start, z_end in zones:
        if z_start >= end:
            break
        if pos < z_end and end > z_start:
            return True
    return False


def inject_wikilinks(
    text: str,
    terms: dict[str, str],
    min_length: int = 3,
) -> str:
    """Inject [[wikilinks]] into markdown text for known vault terms.

    Args:
        text: The markdown text to process.
        terms: Dict mapping lowercase term -> canonical form.
        min_length: Minimum term length to consider.
    """
    if not terms:
        return text

    # Filter and sort terms longest-first to prevent partial matches
    sorted_terms = sorted(
        ((k, v) for k, v in terms.items() if len(k) >= min_length),
        key=lambda kv: len(kv[0]),
        reverse=True,
    )

    if not sorted_terms:
        return text

    # Build alternation regex with word boundaries
    alternatives = "|".join(re.escape(canonical) for _, canonical in sorted_terms)
    pattern = re.compile(rf"\b({alternatives})\b", re.IGNORECASE)

    # Build protected zones
    zones = _build_protected_zones(text)

    # Track which terms we've already linked (only link first occurrence)
    linked: set[str] = set()

    def replacer(m: re.Match) -> str:
        matched_text = m.group(0)
        key = matched_text.lower()

        # Skip if already linked
        if key in linked:
            return matched_text

        # Skip if in protected zone
        if _in_protected_zone(m.start(), m.end(), zones):
            return matched_text

        canonical = terms.get(key, matched_text)
        linked.add(key)
        return f"[[{canonical}]]"

    return pattern.sub(replacer, text)
