"""Shared helpers for all tree-sitter language parsers."""

from __future__ import annotations

import hashlib
from typing import Optional

from tree_sitter import Node


def node_text(node: Node) -> str:
    """Extract UTF-8 text content from a tree-sitter node."""
    return node.text.decode("utf-8") if node.text else ""


def ast_hash(node: Node) -> str:
    """SHA-256 hash (truncated to 16 hex chars) of a node's raw bytes."""
    return hashlib.sha256(node.text).hexdigest()[:16]


def find_child_by_type(node: Node, *types: str) -> Optional[Node]:
    """Return the first child matching any of the given type names."""
    for c in node.children:
        if c.type in types:
            return c
    return None


def find_children_by_type(node: Node, *types: str) -> list[Node]:
    """Return all children matching any of the given type names."""
    return [c for c in node.children if c.type in types]


def extract_docstring(body_node: Node) -> Optional[str]:
    """Extract a docstring from the first statement in a block/body.
    
    Works for Python (triple-quoted strings) and can be adapted.
    Returns cleaned text without surrounding quotes.
    """
    if not body_node or body_node.child_count == 0:
        return None
    
    first = body_node.children[0]
    if first.type == "expression_statement" and first.child_count > 0:
        string_node = first.children[0]
        if string_node.type == "string":
            text = node_text(string_node)
            # Strip triple quotes
            for quote in ('"""', "'''", '"', "'"):
                if text.startswith(quote) and text.endswith(quote):
                    return text[len(quote):-len(quote)].strip()
            return text.strip()
    return None


def extract_jsdoc(node: Node) -> Optional[str]:
    """Extract JSDoc comment (/** ... */) from the sibling before a node."""
    prev = node.prev_sibling
    if prev and prev.type == "comment":
        text = node_text(prev)
        if text.startswith("/**"):
            # Clean JSDoc: strip /** */, leading * on each line
            lines = text.split("\n")
            cleaned = []
            for line in lines:
                line = line.strip()
                if line in ("/**", "*/"):
                    continue
                if line.startswith("* "):
                    line = line[2:]
                elif line.startswith("*"):
                    line = line[1:]
                cleaned.append(line)
            return "\n".join(cleaned).strip() or None
    return None


def extract_go_comment(node: Node) -> Optional[str]:
    """Extract Go-style doc comment (// ... lines) before a node."""
    comments = []
    prev = node.prev_sibling
    while prev and prev.type == "comment":
        text = node_text(prev)
        if text.startswith("//"):
            comments.insert(0, text[2:].strip())
        prev = prev.prev_sibling
    return "\n".join(comments).strip() if comments else None


def build_raw_signature(name: str, params_text: str, return_type: Optional[str],
                        is_async: bool, prefix: str = "") -> str:
    """Reconstruct a clean one-line signature string."""
    parts = []
    if is_async:
        parts.append("async")
    if prefix:
        parts.append(prefix)
    sig = f"{name}{params_text}"
    if return_type:
        sig += f" -> {return_type}" if not return_type.startswith(":") else f" {return_type}"
    parts.append(sig)
    return " ".join(parts)
