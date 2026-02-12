"""Tests for grimoiresync.prosemirror — pure transformation tests, no mocks needed."""

from __future__ import annotations

from grimoiresync.prosemirror import (
    _render_inline,
    _render_list,
    _render_text,
    prosemirror_to_markdown,
)


class TestProsemirrorToMarkdown:
    def test_none(self):
        assert prosemirror_to_markdown(None) == ""

    def test_empty_dict(self):
        assert prosemirror_to_markdown({}) == ""

    def test_non_dict(self):
        assert prosemirror_to_markdown("string") == ""

    def test_empty_content(self):
        assert prosemirror_to_markdown({"type": "doc", "content": []}) == ""


class TestNodeTypes:
    def test_paragraph(self):
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Hello world"}],
                }
            ],
        }
        assert prosemirror_to_markdown(doc) == "Hello world"

    def test_heading_levels(self):
        for level in range(1, 7):
            doc = {
                "type": "doc",
                "content": [
                    {
                        "type": "heading",
                        "attrs": {"level": level},
                        "content": [{"type": "text", "text": "Title"}],
                    }
                ],
            }
            expected_prefix = "#" * level
            assert prosemirror_to_markdown(doc) == f"{expected_prefix} Title"

    def test_heading_default_level(self):
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "heading",
                    "content": [{"type": "text", "text": "Title"}],
                }
            ],
        }
        assert prosemirror_to_markdown(doc) == "# Title"

    def test_bullet_list(self):
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "bulletList",
                    "content": [
                        {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Item 1"}]}]},
                        {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Item 2"}]}]},
                    ],
                }
            ],
        }
        result = prosemirror_to_markdown(doc)
        assert "- Item 1" in result
        assert "- Item 2" in result

    def test_ordered_list(self):
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "orderedList",
                    "content": [
                        {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "First"}]}]},
                        {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Second"}]}]},
                    ],
                }
            ],
        }
        result = prosemirror_to_markdown(doc)
        assert "1. First" in result
        assert "2. Second" in result

    def test_nested_lists(self):
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "bulletList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [
                                {"type": "paragraph", "content": [{"type": "text", "text": "Outer"}]},
                                {
                                    "type": "bulletList",
                                    "content": [
                                        {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Inner"}]}]},
                                    ],
                                },
                            ],
                        }
                    ],
                }
            ],
        }
        result = prosemirror_to_markdown(doc)
        assert "- Outer" in result
        assert "- Inner" in result

    def test_blockquote(self):
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "blockquote",
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "Quoted text"}]},
                    ],
                }
            ],
        }
        result = prosemirror_to_markdown(doc)
        assert "> Quoted text" in result

    def test_codeblock_with_language(self):
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "codeBlock",
                    "attrs": {"language": "python"},
                    "content": [{"type": "text", "text": "print('hi')"}],
                }
            ],
        }
        result = prosemirror_to_markdown(doc)
        assert "```python" in result
        assert "print('hi')" in result
        assert result.rstrip().endswith("```")

    def test_codeblock_without_language(self):
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "codeBlock",
                    "content": [{"type": "text", "text": "code"}],
                }
            ],
        }
        result = prosemirror_to_markdown(doc)
        assert "```\ncode\n```" in result

    def test_horizontal_rule(self):
        doc = {
            "type": "doc",
            "content": [{"type": "horizontalRule"}],
        }
        result = prosemirror_to_markdown(doc)
        assert "---" in result

    def test_hard_break(self):
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "before"},
                        {"type": "hardBreak"},
                        {"type": "text", "text": "after"},
                    ],
                }
            ],
        }
        result = prosemirror_to_markdown(doc)
        assert "before\nafter" in result

    def test_doc_node(self):
        doc = {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "Hello"}]},
            ],
        }
        assert prosemirror_to_markdown(doc) == "Hello"

    def test_listitem_renders_inline(self):
        # listItem on its own renders inline content
        from grimoiresync.prosemirror import _render_node

        result = _render_node(
            {
                "type": "listItem",
                "content": [{"type": "text", "text": "item"}],
            }
        )
        assert result == "item"

    def test_unknown_node_with_content(self):
        from grimoiresync.prosemirror import _render_node

        result = _render_node(
            {
                "type": "customWidget",
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "inside"}]},
                ],
            }
        )
        assert "inside" in result

    def test_unknown_node_without_content(self):
        from grimoiresync.prosemirror import _render_node

        result = _render_node({"type": "unknownEmpty"})
        assert result == ""

    def test_doc_node_nested(self):
        """A doc node appearing inside another node's content."""
        from grimoiresync.prosemirror import _render_node

        result = _render_node({
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "nested"}]},
            ],
        })
        assert "nested" in result

    def test_hard_break_as_top_level_node(self):
        """hardBreak rendered via _render_node (not _render_inline)."""
        from grimoiresync.prosemirror import _render_node

        result = _render_node({"type": "hardBreak"})
        assert result == "\n"

    def test_text_as_top_level_node(self):
        """text rendered via _render_node (not _render_inline)."""
        from grimoiresync.prosemirror import _render_node

        result = _render_node({"type": "text", "text": "hello", "marks": []})
        assert result == "hello"


class TestTextMarks:
    def test_bold(self):
        node = {"text": "bold", "marks": [{"type": "bold"}]}
        assert _render_text(node) == "**bold**"

    def test_strong(self):
        node = {"text": "strong", "marks": [{"type": "strong"}]}
        assert _render_text(node) == "**strong**"

    def test_italic(self):
        node = {"text": "italic", "marks": [{"type": "italic"}]}
        assert _render_text(node) == "*italic*"

    def test_em(self):
        node = {"text": "em", "marks": [{"type": "em"}]}
        assert _render_text(node) == "*em*"

    def test_code(self):
        node = {"text": "code", "marks": [{"type": "code"}]}
        assert _render_text(node) == "`code`"

    def test_strike(self):
        node = {"text": "strike", "marks": [{"type": "strike"}]}
        assert _render_text(node) == "~~strike~~"

    def test_strikethrough(self):
        node = {"text": "st", "marks": [{"type": "strikethrough"}]}
        assert _render_text(node) == "~~st~~"

    def test_link(self):
        node = {
            "text": "click",
            "marks": [{"type": "link", "attrs": {"href": "https://example.com"}}],
        }
        assert _render_text(node) == "[click](https://example.com)"

    def test_multiple_marks(self):
        node = {
            "text": "word",
            "marks": [{"type": "bold"}, {"type": "italic"}],
        }
        assert _render_text(node) == "***word***"

    def test_unknown_mark(self):
        node = {"text": "plain", "marks": [{"type": "superscript"}]}
        assert _render_text(node) == "plain"


class TestRenderInline:
    def test_text_nodes(self):
        nodes = [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]
        assert _render_inline(nodes) == "ab"

    def test_hard_break(self):
        nodes = [
            {"type": "text", "text": "before"},
            {"type": "hardBreak"},
            {"type": "text", "text": "after"},
        ]
        assert _render_inline(nodes) == "before\nafter"

    def test_nested_block(self):
        nodes = [
            {
                "type": "someWrapper",
                "content": [{"type": "text", "text": "inner"}],
            }
        ]
        assert _render_inline(nodes) == "inner"

    def test_non_text_no_content(self):
        nodes = [{"type": "image"}]
        assert _render_inline(nodes) == ""


class TestRenderList:
    def test_multiline_list_items(self):
        items = [
            {
                "type": "listItem",
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "Line 1"}]},
                    {"type": "paragraph", "content": [{"type": "text", "text": "Line 2"}]},
                ],
            }
        ]
        result = _render_list(items, ordered=False)
        lines = result.strip().split("\n")
        assert lines[0] == "- Line 1"
        assert lines[1].startswith("  ")  # continuation indent

    def test_ordered_list_numbering(self):
        items = [
            {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "A"}]}]},
            {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "B"}]}]},
        ]
        result = _render_list(items, ordered=True)
        assert "1. A" in result
        assert "2. B" in result
