"""
TypeScript/JavaScript parser for OMP.

Extracts function signatures, class definitions, interfaces, imports,
and JSDoc from TypeScript and JavaScript source code using tree-sitter.
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
    """Extract the source text for a node."""
    return node.text.decode("utf-8") if node.text else ""


def _ast_hash(node: Node) -> str:
    """Compute a short hash of the node's source for change detection."""
    text = node.text if node.text else b""
    return hashlib.sha256(text).hexdigest()[:16]


def _find_child_by_type(node: Node, *types: str) -> Optional[Node]:
    """Return the first child whose type is in types."""
    for c in node.children:
        if c.type in types:
            return c
    return None


def _find_children_by_type(node: Node, *types: str) -> list[Node]:
    """Return all children whose type is in types."""
    return [c for c in node.children if c.type in types]


def _prev_sibling(node: Node) -> Optional[Node]:
    """Return the previous sibling of a node, or None."""
    parent = node.parent
    if not parent:
        return None
    children = parent.children
    for i, c in enumerate(children):
        if c == node and i > 0:
            return children[i - 1]
    return None


def _doc_lookup_node(node: Node) -> Node:
    """
    Return the node to use for JSDoc lookup. When a declaration is inside
    export_statement, the comment is typically before the export, so we
    use the outermost wrapper.
    """
    while node.parent and node.parent.type == "export_statement":
        node = node.parent
    return node


def _extract_jsdoc(node: Node) -> Optional[str]:
    """
    If the node has a JSDoc comment (/** ... */) immediately before it,
    extract and clean it. Returns None if none found.
    """
    lookup = _doc_lookup_node(node)
    prev = _prev_sibling(lookup)
    if not prev:
        return None
    if prev.type not in ("comment", "block_comment"):
        return None
    text = _node_text(prev)
    if not text.strip().startswith("/**"):
        return None
    # Strip /** and */, and leading * on each line
    lines = []
    in_doc = False
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("/**"):
            in_doc = True
            stripped = stripped[3:].strip()
        if stripped.endswith("*/"):
            in_doc = False
            stripped = stripped[:-2].strip()
        if in_doc or (stripped and not stripped.startswith("*/")):
            if stripped.startswith("*"):
                stripped = stripped[1:].strip()
            if stripped:
                lines.append(stripped)
    return "\n".join(lines).strip() or None


# ---------------------------------------------------------------------------
# Parameter extraction
# ---------------------------------------------------------------------------


def _extract_parameter(node: Node) -> Optional[Parameter]:
    """
    Extract a single parameter from a formal_parameters child.
    Handles required_parameter, optional_parameter, rest_pattern, identifier.
    """
    if node.type == "required_parameter":
        name_node = _find_child_by_type(node, "identifier")
        annotation = _find_child_by_type(node, "type_annotation")
        type_str = None
        if annotation:
            type_str = _node_text(annotation).strip()
            if type_str.startswith(":"):
                type_str = type_str[1:].strip()
        return Parameter(
            name=_node_text(name_node) if name_node else "?",
            type=type_str,
        )

    if node.type == "optional_parameter":
        name_node = _find_child_by_type(node, "identifier")
        annotation = _find_child_by_type(node, "type_annotation")
        type_str = None
        if annotation:
            type_str = _node_text(annotation).strip()
            if type_str.startswith(":"):
                type_str = type_str[1:].strip()
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
            type=type_str,
            optional=True,
            default=default_val,
        )

    if node.type == "identifier":
        return Parameter(name=_node_text(node))

    if node.type == "rest_pattern":
        inner = _find_child_by_type(node, "identifier")
        return Parameter(name="..." + (_node_text(inner) if inner else ""))

    return None


# ---------------------------------------------------------------------------
# Function extraction
# ---------------------------------------------------------------------------


def _build_raw_signature(
    kind_prefix: str,
    name: str,
    params_text: str,
    return_type: Optional[str],
    is_async: bool,
) -> str:
    """Build a one-line raw signature string."""
    parts = []
    if is_async:
        parts.append("async")
    parts.append(kind_prefix)
    sig = f"{name}{params_text}"
    if return_type:
        sig += f": {return_type}"
    parts.append(sig)
    result = " ".join(parts)
    if kind_prefix == "const":
        result += " =>"
    return result


def _extract_function_declaration(
    node: Node,
    is_exported: bool = False,
) -> FunctionSignature:
    """Extract from function_declaration."""
    name_node = _find_child_by_type(node, "identifier")
    params_node = _find_child_by_type(node, "formal_parameters")
    annotation = _find_child_by_type(node, "type_annotation")

    is_async = any(c.type == "async" for c in node.children)

    name = _node_text(name_node) if name_node else "<anonymous>"
    params_text = _node_text(params_node) if params_node else "()"
    return_type = None
    if annotation:
        return_type = _node_text(annotation).strip()
        if return_type.startswith(":"):
            return_type = return_type[1:].strip()

    parameters: list[Parameter] = []
    if params_node:
        for child in params_node.children:
            param = _extract_parameter(child)
            if param and param.name not in ("(", ")", ","):
                parameters.append(param)

    docstring = _extract_jsdoc(node)
    raw = _build_raw_signature("function", name, params_text, return_type, is_async)

    return FunctionSignature(
        kind="function",
        name=name,
        parameters=parameters,
        return_type=return_type,
        is_async=is_async,
        is_static=False,
        is_exported=is_exported,
        decorators=[],
        docstring=docstring,
        parent_class=None,
        line_start=node.start_point.row + 1,
        line_end=node.end_point.row + 1,
        raw_signature=raw,
        ast_hash=_ast_hash(node),
    )


def _extract_method_definition(
    node: Node,
    parent_class: str,
    is_exported: bool = False,
) -> FunctionSignature:
    """Extract from method_definition inside class_body."""
    name_node = _find_child_by_type(node, "identifier", "property_identifier")
    params_node = _find_child_by_type(node, "formal_parameters")
    annotation = _find_child_by_type(node, "type_annotation")

    is_async = any(c.type == "async" for c in node.children)
    is_static = any(c.type == "static" for c in node.children)

    name = _node_text(name_node) if name_node else "<anonymous>"
    params_text = _node_text(params_node) if params_node else "()"
    return_type = None
    if annotation:
        return_type = _node_text(annotation).strip()
        if return_type.startswith(":"):
            return_type = return_type[1:].strip()

    parameters: list[Parameter] = []
    if params_node:
        for child in params_node.children:
            param = _extract_parameter(child)
            if param and param.name not in ("(", ")", ","):
                parameters.append(param)

    docstring = _extract_jsdoc(node)
    raw = _build_raw_signature("", name, params_text, return_type, is_async)
    if is_static:
        raw = "static " + raw
    raw = raw.strip()

    return FunctionSignature(
        kind="method",
        name=name,
        parameters=parameters,
        return_type=return_type,
        is_async=is_async,
        is_static=is_static,
        is_exported=is_exported,
        decorators=[],
        docstring=docstring,
        parent_class=parent_class,
        line_start=node.start_point.row + 1,
        line_end=node.end_point.row + 1,
        raw_signature=raw,
        ast_hash=_ast_hash(node),
    )


def _extract_arrow_function(
    node: Node,
    var_name: str,
    is_exported: bool = False,
) -> Optional[FunctionSignature]:
    """
    Extract arrow function from variable_declarator.
    Structure: variable_declarator -> identifier, arrow_function
    """
    arrow = _find_child_by_type(node, "arrow_function")
    if not arrow:
        return None

    params_node = _find_child_by_type(arrow, "formal_parameters")
    annotation = _find_child_by_type(arrow, "type_annotation")
    is_async = any(c.type == "async" for c in arrow.children)

    params_text = _node_text(params_node) if params_node else "()"
    return_type = None
    if annotation:
        return_type = _node_text(annotation).strip()
        if return_type.startswith(":"):
            return_type = return_type[1:].strip()

    parameters: list[Parameter] = []
    if params_node:
        for child in params_node.children:
            param = _extract_parameter(child)
            if param and param.name not in ("(", ")", ","):
                parameters.append(param)

    docstring = _extract_jsdoc(node)
    raw = _build_raw_signature("const", var_name, params_text, return_type, is_async)

    return FunctionSignature(
        kind="arrow_function",
        name=var_name,
        parameters=parameters,
        return_type=return_type,
        is_async=is_async,
        is_static=False,
        is_exported=is_exported,
        decorators=[],
        docstring=docstring,
        parent_class=None,
        line_start=node.start_point.row + 1,
        line_end=node.end_point.row + 1,
        raw_signature=raw,
        ast_hash=_ast_hash(node),
    )


# ---------------------------------------------------------------------------
# Class extraction
# ---------------------------------------------------------------------------


def _extract_class_heritage(class_node: Node) -> list[str]:
    """
    Extract base types from class_heritage (extends / implements).
    Looks for extends_clause children with type_identifier or identifier.
    """
    bases: list[str] = []
    heritage = _find_child_by_type(class_node, "class_heritage")
    if heritage:
        for c in heritage.children:
            if c.type == "extends_clause":
                for sub in c.children:
                    if sub.type in ("type_identifier", "identifier"):
                        bases.append(_node_text(sub))
    return bases


def _extract_class_declaration(
    node: Node,
    is_exported: bool = False,
) -> ClassDefinition:
    """Extract from class_declaration."""
    name_node = _find_child_by_type(node, "type_identifier", "identifier")
    name = _node_text(name_node) if name_node else "<anonymous>"
    bases = _extract_class_heritage(node)

    docstring = _extract_jsdoc(node)
    methods: list[FunctionSignature] = []
    body = _find_child_by_type(node, "class_body")
    if body:
        for child in body.children:
            if child.type == "method_definition":
                methods.append(
                    _extract_method_definition(child, parent_class=name, is_exported=is_exported)
                )

    return ClassDefinition(
        name=name,
        kind="class",
        methods=methods,
        bases=bases,
        docstring=docstring,
        line_start=node.start_point.row + 1,
        line_end=node.end_point.row + 1,
        ast_hash=_ast_hash(node),
    )


# ---------------------------------------------------------------------------
# Interface extraction
# ---------------------------------------------------------------------------


def _extract_interface_methods(node: Node) -> list[FunctionSignature]:
    """
    Extract method_signature and property_signature from interface_body.
    Each becomes a FunctionSignature with kind="interface_method".
    """
    name_node = _find_child_by_type(node, "type_identifier", "identifier")
    iface_name = _node_text(name_node) if name_node else "<anonymous>"
    methods: list[FunctionSignature] = []

    body = _find_child_by_type(node, "interface_body", "object_type")
    if not body:
        return methods

    for child in body.children:
        if child.type == "method_signature":
            sig_name_node = _find_child_by_type(child, "property_identifier", "identifier")
            params_node = _find_child_by_type(child, "formal_parameters")
            annotation = _find_child_by_type(child, "type_annotation")

            sig_name = _node_text(sig_name_node) if sig_name_node else "?"
            params_text = _node_text(params_node) if params_node else "()"
            return_type = None
            if annotation:
                return_type = _node_text(annotation).strip()
                if return_type.startswith(":"):
                    return_type = return_type[1:].strip()

            parameters: list[Parameter] = []
            if params_node:
                for p in params_node.children:
                    param = _extract_parameter(p)
                    if param and param.name not in ("(", ")", ","):
                        parameters.append(param)

            raw = _build_raw_signature("", sig_name, params_text, return_type, False).strip()
            methods.append(
                FunctionSignature(
                    kind="interface_method",
                    name=sig_name,
                    parameters=parameters,
                    return_type=return_type,
                    is_async=False,
                    is_static=False,
                    is_exported=False,
                    decorators=[],
                    docstring=None,
                    parent_class=iface_name,
                    line_start=child.start_point.row + 1,
                    line_end=child.end_point.row + 1,
                    raw_signature=raw,
                    ast_hash=_ast_hash(child),
                )
            )
        elif child.type == "property_signature":
            prop_name_node = _find_child_by_type(child, "property_identifier", "identifier")
            annotation = _find_child_by_type(child, "type_annotation")

            sig_name = _node_text(prop_name_node) if prop_name_node else "?"
            return_type = None
            if annotation:
                return_type = _node_text(annotation).strip()
                if return_type.startswith(":"):
                    return_type = return_type[1:].strip()

            raw = f"{sig_name}: {return_type}" if return_type else sig_name
            methods.append(
                FunctionSignature(
                    kind="interface_method",
                    name=sig_name,
                    parameters=[],
                    return_type=return_type,
                    is_async=False,
                    is_static=False,
                    is_exported=False,
                    decorators=[],
                    docstring=None,
                    parent_class=iface_name,
                    line_start=child.start_point.row + 1,
                    line_end=child.end_point.row + 1,
                    raw_signature=raw,
                    ast_hash=_ast_hash(child),
                )
            )

    return methods


# ---------------------------------------------------------------------------
# Import extraction
# ---------------------------------------------------------------------------


def _strip_quotes(s: str) -> str:
    """Remove surrounding quotes from a string literal."""
    if len(s) >= 2 and s[0] in ("'", '"', "`") and s[-1] == s[0]:
        return s[1:-1]
    return s


def _extract_import_statement(node: Node) -> Optional[ImportStatement]:
    """
    Extract ImportStatement from import_statement.
    Structure: import [import_clause] from string
    - import { foo, bar } from "module" -> names=["foo", "bar"]
    - import foo from "module" -> names=["foo"]
    - import * as ns from "module" -> is_wildcard=True, alias="ns"
    - import "module" -> names=[]
    """
    if node.type != "import_statement":
        return None

    module_str = ""
    import_clause = _find_child_by_type(node, "import_clause")
    string_node = _find_child_by_type(node, "string")

    if string_node:
        module_str = _strip_quotes(_node_text(string_node))

    line = node.start_point.row + 1

    if not import_clause:
        return ImportStatement(module=module_str, names=[], line=line)

    # Check for namespace import first: namespace_import (* as ns)
    ns_import = _find_child_by_type(import_clause, "namespace_import")
    if ns_import:
        alias_node = _find_child_by_type(ns_import, "identifier")
        return ImportStatement(
            module=module_str,
            is_wildcard=True,
            alias=_node_text(alias_node) if alias_node else None,
            line=line,
        )

    # Collect default import and/or named imports (order: default first, then named)
    names: list[str] = []
    seen_named = False
    for c in import_clause.children:
        if c.type == "named_imports":
            seen_named = True
            for spec in _find_children_by_type(c, "import_specifier"):
                name_node = _find_child_by_type(spec, "identifier")
                if name_node:
                    names.append(_node_text(name_node))
        elif c.type == "identifier" and not seen_named:
            # Default import (before named_imports)
            names.append(_node_text(c))

    return ImportStatement(module=module_str, names=names, line=line)


def _extract_require(node: Node) -> Optional[ImportStatement]:
    """
    Extract ImportStatement from require() call.
    Structure: variable_declarator -> identifier = call_expression(require, string)
    """
    if node.type != "variable_declarator":
        return None

    call = _find_child_by_type(node, "call_expression")
    if not call:
        return None

    func_node = _find_child_by_type(call, "identifier")
    if not func_node or _node_text(func_node) != "require":
        return None

    args = _find_child_by_type(call, "arguments")
    if not args:
        return None

    string_node = _find_child_by_type(args, "string")
    if not string_node:
        return None

    module_str = _strip_quotes(_node_text(string_node))
    line = node.start_point.row + 1

    return ImportStatement(module=module_str, names=[], line=line)


# ---------------------------------------------------------------------------
# Main walker and public API
# ---------------------------------------------------------------------------


def _walk(
    node: Node,
    functions: list[FunctionSignature],
    classes: list[ClassDefinition],
    imports: list[ImportStatement],
    exported: bool = False,
) -> None:
    """Recursively walk the AST and collect functions, classes, imports."""
    for child in node.children:
        is_exported = exported or child.type == "export_statement"

        if child.type == "import_statement":
            imp = _extract_import_statement(child)
            if imp:
                imports.append(imp)

        elif child.type == "function_declaration":
            functions.append(_extract_function_declaration(child, is_exported=is_exported))

        elif child.type == "class_declaration":
            classes.append(_extract_class_declaration(child, is_exported=is_exported))

        elif child.type == "interface_declaration":
            functions.extend(_extract_interface_methods(child))

        elif child.type in ("lexical_declaration", "variable_declaration"):
            for decl in child.children:
                if decl.type == "variable_declarator":
                    # Arrow function
                    var_name_node = _find_child_by_type(decl, "identifier")
                    if var_name_node:
                        arrow_sig = _extract_arrow_function(
                            decl,
                            _node_text(var_name_node),
                            is_exported=is_exported,
                        )
                        if arrow_sig:
                            functions.append(arrow_sig)
                    # require()
                    req_imp = _extract_require(decl)
                    if req_imp:
                        imports.append(req_imp)

        elif child.type == "export_statement":
            _walk(child, functions, classes, imports, exported=True)

        else:
            _walk(child, functions, classes, imports, exported)


def extract_typescript(
    root: Node,
) -> tuple[list[FunctionSignature], list[ClassDefinition], list[ImportStatement]]:
    """
    Extract function signatures, class definitions, and imports from
    TypeScript (or TSX) source code AST.

    Args:
        root: The root node from a tree-sitter parse (typically program).

    Returns:
        A 3-tuple of (functions, classes, imports).
    """
    functions: list[FunctionSignature] = []
    classes: list[ClassDefinition] = []
    imports: list[ImportStatement] = []

    _walk(root, functions, classes, imports)

    return functions, classes, imports


def extract_javascript(
    root: Node,
) -> tuple[list[FunctionSignature], list[ClassDefinition], list[ImportStatement]]:
    """
    Extract function signatures, class definitions, and imports from
    JavaScript source code AST. Alias for extract_typescript since
    JS uses the same grammar structure.
    """
    return extract_typescript(root)
