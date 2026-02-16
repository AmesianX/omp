"""
OMP Python Parser - Extracts function signatures, classes, and imports from Python source.

Uses tree-sitter to deterministically parse Python code and produce structured
data models for the OMP symbolic layer.
"""

from __future__ import annotations

import hashlib
from typing import Optional

from tree_sitter import Node

from omp.models import (
    ClassDefinition,
    FunctionSignature,
    ImportStatement,
    Parameter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _node_text(node: Node) -> str:
    """Extract UTF-8 text from a tree-sitter node."""
    return node.text.decode("utf-8") if node.text else ""


def _ast_hash(node: Node) -> str:
    """Compute a short SHA256 hash of the node's text for deduplication."""
    data = node.text if node.text else b""
    return hashlib.sha256(data).hexdigest()[:16]


def _find_child_by_type(node: Node, *types: str) -> Optional[Node]:
    """Return the first child whose type is in the given set."""
    for c in node.children:
        if c.type in types:
            return c
    return None


def _find_children_by_type(node: Node, *types: str) -> list[Node]:
    """Return all children whose type is in the given set."""
    return [c for c in node.children if c.type in types]


def _extract_docstring_from_block(block_node: Node) -> Optional[str]:
    """
    Extract docstring from a block node.

    The docstring is the first expression_statement child that contains a string node.
    """
    if not block_node:
        return None
    for child in block_node.children:
        if child.type == "expression_statement":
            string_node = _find_child_by_type(child, "string")
            if string_node:
                raw = _node_text(string_node)
                # Strip triple quotes and clean
                for q in ('"""', "'''", '"', "'"):
                    if raw.startswith(q) and raw.endswith(q):
                        return raw[len(q) : -len(q)].strip()
                return raw.strip()
            return None  # expression_statement without string is not a docstring
        if child.type not in ("pass_statement",):
            # First significant statement that isn't a docstring
            return None
    return None


def _get_module_name(node: Node) -> str:
    """Extract module path from dotted_name or relative_import node."""
    return _node_text(node).strip()


# ---------------------------------------------------------------------------
# Parameter extraction
# ---------------------------------------------------------------------------


def _extract_parameter(node: Node) -> Optional[Parameter]:
    """Extract a Parameter from a Python parameter node."""
    if node.type == "identifier":
        return Parameter(name=_node_text(node))

    if node.type == "typed_parameter":
        name_node = _find_child_by_type(node, "identifier")
        type_node = _find_child_by_type(node, "type")
        return Parameter(
            name=_node_text(name_node) if name_node else "?",
            type=_node_text(type_node) if type_node else None,
        )

    if node.type == "default_parameter":
        name_node = _find_child_by_type(node, "identifier")
        value_nodes = [c for c in node.children if c.type not in ("identifier", "=")]
        default_val = _node_text(value_nodes[0]) if value_nodes else None
        return Parameter(
            name=_node_text(name_node) if name_node else "?",
            default=default_val,
        )

    if node.type == "typed_default_parameter":
        name_node = _find_child_by_type(node, "identifier")
        type_node = _find_child_by_type(node, "type")
        default_val = None
        eq_seen = False
        for c in node.children:
            if c.type == "=":
                eq_seen = True
            elif eq_seen:
                default_val = _node_text(c)
                break
        return Parameter(
            name=_node_text(name_node) if name_node else "?",
            type=_node_text(type_node) if type_node else None,
            default=default_val,
        )

    if node.type == "list_splat_pattern":
        inner = _find_child_by_type(node, "identifier")
        name = "*" + (_node_text(inner) if inner else "")
        return Parameter(name=name)

    if node.type == "dictionary_splat_pattern":
        inner = _find_child_by_type(node, "identifier")
        name = "**" + (_node_text(inner) if inner else "")
        return Parameter(name=name)

    return None


# ---------------------------------------------------------------------------
# Decorator extraction
# ---------------------------------------------------------------------------


def _extract_decorators(decorated_def: Node) -> list[str]:
    """Extract decorator strings from a decorated_definition node."""
    decorators: list[str] = []
    for child in decorated_def.children:
        if child.type == "decorator":
            decorators.append(_node_text(child))
        elif child.type in ("function_definition", "class_definition"):
            break
    return decorators


def _has_static_method(decorators: list[str]) -> bool:
    """Check if decorators include @staticmethod."""
    return any("staticmethod" in d for d in decorators)


def _has_class_method(decorators: list[str]) -> bool:
    """Check if decorators include @classmethod."""
    return any("classmethod" in d for d in decorators)


# ---------------------------------------------------------------------------
# Function extraction
# ---------------------------------------------------------------------------


def _extract_function(
    node: Node,
    parent_class: Optional[str] = None,
    decorators: Optional[list[str]] = None,
) -> FunctionSignature:
    """Extract a FunctionSignature from a function_definition node."""
    decorators = decorators or []
    name_node = _find_child_by_type(node, "identifier")
    params_node = _find_child_by_type(node, "parameters")
    return_type_node = _find_child_by_type(node, "type")

    is_async = any(c.type == "async" for c in node.children)

    parameters: list[Parameter] = []
    params_text = "()"
    if params_node:
        params_text = _node_text(params_node)
        for child in params_node.children:
            param = _extract_parameter(child)
            if param:
                if parent_class and param.name in ("self", "cls"):
                    continue
                parameters.append(param)

    return_type = _node_text(return_type_node) if return_type_node else None
    name = _node_text(name_node) if name_node else "<anonymous>"

    kind = "method" if parent_class else "function"
    is_static = _has_static_method(decorators)

    # Build raw_signature: async def name(params) -> return_type
    raw_parts = []
    if is_async:
        raw_parts.append("async")
    raw_parts.append("def")
    raw_parts.append(f"{name}{params_text}")
    if return_type:
        raw_parts.append(f"-> {return_type}")
    raw_signature = " ".join(raw_parts)

    # Extract docstring from block
    block = _find_child_by_type(node, "block")
    docstring = _extract_docstring_from_block(block)

    return FunctionSignature(
        kind=kind,
        name=name,
        parameters=parameters,
        return_type=return_type,
        is_async=is_async,
        is_static=is_static,
        is_exported=False,
        decorators=decorators,
        docstring=docstring,
        parent_class=parent_class,
        file=None,
        line_start=node.start_point[0] + 1,
        line_end=node.end_point[0] + 1,
        raw_signature=raw_signature,
        ast_hash=_ast_hash(node),
    )


# ---------------------------------------------------------------------------
# Class extraction
# ---------------------------------------------------------------------------


def _extract_class(
    node: Node,
    decorators: Optional[list[str]] = None,
) -> ClassDefinition:
    """Extract a ClassDefinition from a class_definition node."""
    decorators = decorators or []
    name_node = _find_child_by_type(node, "identifier")
    name = _node_text(name_node) if name_node else "<anonymous>"

    # Base classes from argument_list
    bases: list[str] = []
    arg_list = _find_child_by_type(node, "argument_list")
    if arg_list:
        for c in arg_list.children:
            if c.type not in ("(", ")", ","):
                bases.append(_node_text(c))

    # Class docstring
    block = _find_child_by_type(node, "block")
    docstring = _extract_docstring_from_block(block)

    # Methods
    methods: list[FunctionSignature] = []
    if block:
        for child in block.children:
            if child.type == "function_definition":
                methods.append(_extract_function(child, parent_class=name))
            elif child.type == "decorated_definition":
                func = _find_child_by_type(child, "function_definition")
                if func:
                    method_decorators = _extract_decorators(child)
                    methods.append(
                        _extract_function(func, parent_class=name, decorators=method_decorators)
                    )

    return ClassDefinition(
        name=name,
        kind="class",
        methods=methods,
        bases=bases,
        docstring=docstring,
        file=None,
        line_start=node.start_point[0] + 1,
        line_end=node.end_point[0] + 1,
        ast_hash=_ast_hash(node),
    )


# ---------------------------------------------------------------------------
# Import extraction
# ---------------------------------------------------------------------------


def _extract_import_statement(node: Node) -> list[ImportStatement]:
    """
    Extract ImportStatement(s) from an import_statement node.

    Handles: import foo | import foo as f | import foo, bar | import foo as f, bar as b
    """
    result: list[ImportStatement] = []
    line = node.start_point[0] + 1

    # Skip the initial "import" token
    for child in node.children:
        if child.type == "dotted_name":
            result.append(
                ImportStatement(module=_get_module_name(child), names=[], line=line)
            )
        elif child.type == "aliased_import":
            module_node = _find_child_by_type(child, "dotted_name")
            alias_node = _find_child_by_type(child, "identifier")
            # For "foo as f", we need the last identifier (the alias)
            if alias_node:
                alias = _node_text(alias_node)
            else:
                alias = None
            # The dotted_name might be the first meaningful child
            if module_node:
                module = _get_module_name(module_node)
                result.append(
                    ImportStatement(module=module, names=[], alias=alias, line=line)
                )
            elif child.children:
                # aliased_import: dotted_name, as, identifier
                parts = [c for c in child.children if c.type in ("dotted_name", "identifier")]
                if len(parts) >= 2:
                    result.append(
                        ImportStatement(
                            module=_get_module_name(parts[0]),
                            names=[],
                            alias=_node_text(parts[-1]) if parts[-1].type == "identifier" else None,
                            line=line,
                        )
                    )

    return result


def _extract_import_from_statement(node: Node) -> list[ImportStatement]:
    """
    Extract ImportStatement(s) from an import_from_statement node.

    Handles: from foo import bar | from foo import bar, baz | from foo import *
    | from foo.bar import baz | from . import x | from ..parent import child
    """
    line = node.start_point[0] + 1

    # Module: first dotted_name or relative_import (comes before "import")
    module = ""
    found_from = False
    for child in node.children:
        if child.type == "from":
            found_from = True
            continue
        if found_from and child.type == "import":
            break
        if found_from and child.type in ("dotted_name", "relative_import"):
            module = _get_module_name(child)
            break

    # Wildcard: from foo import *
    if _find_child_by_type(node, "wildcard_import"):
        return [ImportStatement(module=module, names=[], is_wildcard=True, line=line)]

    # Names: after "import"
    names: list[str] = []
    found_import = False
    for child in node.children:
        if child.type == "import":
            found_import = True
            continue
        if not found_import:
            continue

        if child.type == "dotted_name":
            names.append(_get_module_name(child))
        elif child.type == "aliased_import":
            mod_node = _find_child_by_type(child, "dotted_name")
            if mod_node:
                names.append(_get_module_name(mod_node))

    return [ImportStatement(module=module, names=names, line=line)] if names or module else []


# ---------------------------------------------------------------------------
# Main extractor
# ---------------------------------------------------------------------------


def extract_python(root: Node) -> tuple[list[FunctionSignature], list[ClassDefinition], list[ImportStatement]]:
    """
    Extract function signatures, class definitions, and import statements from Python AST.

    Args:
        root: The root node of the tree-sitter parse tree (typically module).

    Returns:
        A 3-tuple of (functions, classes, imports).
    """
    functions: list[FunctionSignature] = []
    classes: list[ClassDefinition] = []
    imports: list[ImportStatement] = []

    for child in root.children:
        if child.type == "import_statement":
            imports.extend(_extract_import_statement(child))
        elif child.type == "import_from_statement":
            imports.extend(_extract_import_from_statement(child))
        elif child.type == "function_definition":
            functions.append(_extract_function(child))
        elif child.type == "decorated_definition":
            func = _find_child_by_type(child, "function_definition")
            cls = _find_child_by_type(child, "class_definition")
            decorators = _extract_decorators(child)
            if func:
                functions.append(_extract_function(func, decorators=decorators))
            if cls:
                classes.append(_extract_class(cls, decorators=decorators))
        elif child.type == "class_definition":
            classes.append(_extract_class(child))

    return functions, classes, imports
