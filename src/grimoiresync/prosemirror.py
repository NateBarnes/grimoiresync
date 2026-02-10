"""Fallback converter: ProseMirror JSON -> Markdown.

Used only when a document lacks a pre-rendered notes_markdown field.
Handles the common node types found in Granola's ProseMirror schema.
"""

from __future__ import annotations


def prosemirror_to_markdown(doc: dict) -> str:
    """Convert a ProseMirror document JSON to markdown."""
    if not doc or not isinstance(doc, dict):
        return ""
    content = doc.get("content", [])
    return _render_nodes(content).strip()


def _render_nodes(nodes: list[dict]) -> str:
    parts: list[str] = []
    for node in nodes:
        parts.append(_render_node(node))
    return "".join(parts)


def _render_node(node: dict) -> str:
    node_type = node.get("type", "")
    content = node.get("content", [])
    attrs = node.get("attrs", {})

    match node_type:
        case "doc":
            return _render_nodes(content)

        case "paragraph":
            text = _render_inline(content)
            return f"{text}\n\n"

        case "heading":
            level = attrs.get("level", 1)
            text = _render_inline(content)
            prefix = "#" * level
            return f"{prefix} {text}\n\n"

        case "bulletList":
            return _render_list(content, ordered=False)

        case "orderedList":
            return _render_list(content, ordered=True)

        case "listItem":
            return _render_inline(content)

        case "blockquote":
            inner = _render_nodes(content).strip()
            lines = inner.split("\n")
            quoted = "\n".join(f"> {line}" for line in lines)
            return f"{quoted}\n\n"

        case "codeBlock":
            lang = attrs.get("language", "")
            text = _render_inline(content)
            return f"```{lang}\n{text}\n```\n\n"

        case "horizontalRule":
            return "---\n\n"

        case "hardBreak":
            return "\n"

        case "text":
            return _render_text(node)

        case _:
            # Unknown node - try to render children
            if content:
                return _render_nodes(content)
            return ""


def _render_inline(nodes: list[dict]) -> str:
    parts: list[str] = []
    for node in nodes:
        node_type = node.get("type", "")
        if node_type == "text":
            parts.append(_render_text(node))
        elif node_type == "hardBreak":
            parts.append("\n")
        else:
            # Nested block-level inside inline context
            content = node.get("content", [])
            if content:
                parts.append(_render_inline(content))
    return "".join(parts)


def _render_text(node: dict) -> str:
    text = node.get("text", "")
    marks = node.get("marks", [])

    for mark in marks:
        mark_type = mark.get("type", "")
        match mark_type:
            case "bold" | "strong":
                text = f"**{text}**"
            case "italic" | "em":
                text = f"*{text}*"
            case "code":
                text = f"`{text}`"
            case "strike" | "strikethrough":
                text = f"~~{text}~~"
            case "link":
                href = mark.get("attrs", {}).get("href", "")
                text = f"[{text}]({href})"

    return text


def _render_list(items: list[dict], ordered: bool) -> str:
    lines: list[str] = []
    for i, item in enumerate(items):
        content = item.get("content", [])
        text = _render_nodes(content).strip()
        # Handle multi-line list items
        item_lines = text.split("\n")
        prefix = f"{i + 1}. " if ordered else "- "
        indent = " " * len(prefix)
        for j, line in enumerate(item_lines):
            if j == 0:
                lines.append(f"{prefix}{line}")
            else:
                lines.append(f"{indent}{line}")
    return "\n".join(lines) + "\n\n"
