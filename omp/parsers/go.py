"""
Go parser for OMP (Open Memory Protocol).

Extracts function signatures, struct/interface definitions (as ClassDefinition),
import statements, and doc comments from Go source code using tree-sitter.
"""

from __future__ import annotations

import hashlib
from tree_sitter import Node
from typing import Optional

from omp.models import (
    ClassDefinition,
    FunctionSignature,
    ImportStatement,
    Parameter,
)


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------


def _node_text(node: Node) -> str:
    """Extract UTF-8 text from a node. Handles None text gracefully."""
    return node.text.decode("utf-8") if node.text else ""


def _ast_hash(node: Node) -> str:
    """Compute a short hash of the node's text for change detection."""
    return hashlib.sha256(node.text or b"").hexdigest()[:16]


def _find_child_by_type(node: Node, *types: str) -> Optional[Node]:
    """Return the first child whose type is in the given types."""
    for c in node.children:
        if c.type in types:
            return c
    return None


def _find_children_by_type(node: Node, *types: str) -> list[Node]:
    """Return all children whose type is in the given types."""
    return [c for c in node.children if c.type in types]


def _is_exported(name: str) -> bool:
    """Go convention: exported if name starts with uppercase letter."""
    return bool(name) and name[0].isupper()


# Go type node types (for parameter and return type extraction)
_GO_TYPE_NODES = frozenset({
    "type_identifier",
    "pointer_type",
    "slice_type",
    "map_type",
    "qualified_type",
    "interface_type",
    "struct_type",
    "array_type",
    "channel_type",
    "function_type",
})


def _extract_type_text(node: Node) -> str:
    """Recursively extract type string from a type node (handles pointer, etc.)."""
    return _node_text(node)


def _get_doc_comment(node: Node) -> Optional[str]:
    """Extract doc comment from the previous sibling if it's a comment."""
    prev = node.prev_named_sibling
    if prev and prev.type in ("comment", "line_comment", "block_comment"):
        text = _node_text(prev).strip()
        # Go convention: // Name does X or /* ... */
        if text.startswith("//"):
            return text[2:].strip()
        if text.startswith("/*") and text.endswith("*/"):
            return text[2:-2].strip()
    return None


# ---------------------------------------------------------------------------
# Parameter extraction (Go groups params: (a, b int, c string))
# ---------------------------------------------------------------------------


def _extract_go_parameters(parameter_list: Node) -> list[Parameter]:
    """Extract parameters from a Go parameter_list.

    Go groups parameters: (a, b int, c string) means a:int, b:int, c:string.
    Collect identifiers first, then the last type applies to all in that group.
    """
    params: list[Parameter] = []

    for child in parameter_list.children:
        if child.type != "parameter_declaration":
            continue

        identifiers: list[str] = []
        type_str: Optional[str] = None

        for grandchild in child.children:
            if grandchild.type == "identifier":
                identifiers.append(_node_text(grandchild))
            elif grandchild.type in _GO_TYPE_NODES:
                type_str = _extract_type_text(grandchild)

        if identifiers:
            for name in identifiers:
                params.append(Parameter(name=name, type=type_str))
        elif type_str:
            # Variadic or unnamed: (args ...int) or just (int) for return
            params.append(Parameter(name="", type=type_str))

    return params


# ---------------------------------------------------------------------------
# Function and method extraction
# ---------------------------------------------------------------------------


def _extract_go_return_type_text(node: Node, actual_params: Optional[Node]) -> Optional[str]:
    """Extract return type: first meaningful node after params, before block."""
    found_params = False
    for child in node.children:
        if child == actual_params:
            found_params = True
            continue
        if found_params and child.type == "block":
            break
        if found_params and child.type not in ("(", ")", ","):
            return _node_text(child)
    return None


def _build_go_raw_signature(
    name: str,
    params_text: str,
    return_type: Optional[str],
    receiver: Optional[str] = None,
) -> str:
    """Build raw signature: func Name(params) returnType or func (recv) Name(params) returnType."""
    if receiver:
        base = f"func ({receiver}) {name}{params_text}"
    else:
        base = f"func {name}{params_text}"
    if return_type:
        return f"{base} {return_type}"
    return base


def _extract_go_function(
    node: Node,
) -> FunctionSignature:
    """Extract from function_declaration or method_declaration."""
    is_method = node.type == "method_declaration"

    param_lists = _find_children_by_type(node, "parameter_list")
    parent_class: Optional[str] = None
    receiver_list: Optional[Node] = None
    actual_params: Optional[Node] = None
    receiver_text: Optional[str] = None

    if is_method and len(param_lists) >= 2:
        receiver_list = param_lists[0]
        actual_params = param_lists[1]
        for decl in receiver_list.children:
            if decl.type == "parameter_declaration":
                recv_type = _find_child_by_type(
                    decl, "pointer_type", "type_identifier"
                )
                if recv_type:
                    parent_class = _node_text(recv_type).lstrip("*")
                    # Receiver text for raw_signature: "s *Server" not "(s *Server)"
                    receiver_text = _node_text(decl)
                    break
    elif param_lists:
        actual_params = param_lists[0]

    name_node = _find_child_by_type(
        node, "field_identifier" if is_method else "identifier"
    )
    name = _node_text(name_node) if name_node else "<anonymous>"

    parameters: list[Parameter] = []
    params_text = "()"
    if actual_params:
        params_text = _node_text(actual_params)
        for child in actual_params.children:
            if child.type == "parameter_declaration":
                parameters.extend(_extract_go_parameters(child))

    return_type = _extract_go_return_type_text(node, actual_params)
    docstring = _get_doc_comment(node)

    kind = "method" if is_method else "function"
    raw = _build_go_raw_signature(
        name, params_text, return_type,
        receiver=receiver_text,
    )

    return FunctionSignature(
        kind=kind,
        name=name,
        parameters=parameters,
        return_type=return_type,
        is_async=False,
        is_static=False,
        is_exported=_is_exported(name),
        decorators=[],
        docstring=docstring,
        parent_class=parent_class,
        file=None,
        line_start=node.start_point.row + 1,
        line_end=node.end_point.row + 1,
        raw_signature=raw,
        ast_hash=_ast_hash(node),
    )


# ---------------------------------------------------------------------------
# Import extraction
# ---------------------------------------------------------------------------


def _extract_import_spec(spec: Node, line: int) -> Optional[ImportStatement]:
    """Extract a single import_spec: path, optional alias, optional dot import.

    Go import_spec structure:
    - import "fmt" -> interpreted_string_literal only
    - import f "fmt" -> package_identifier (alias) + interpreted_string_literal
    - import . "fmt" -> dot + interpreted_string_literal
    """
    path_node = _find_child_by_type(spec, "interpreted_string_literal")
    if not path_node:
        return None

    path = _node_text(path_node).strip('"').strip("`")
    alias: Optional[str] = None
    is_wildcard = False

    dot_node = _find_child_by_type(spec, "dot")
    if dot_node:
        is_wildcard = True
    else:
        alias_node = _find_child_by_type(spec, "package_identifier")
        if alias_node:
            alias = _node_text(alias_node)

    return ImportStatement(
        module=path,
        names=[],
        alias=alias,
        is_wildcard=is_wildcard,
        line=line,
    )


def _extract_imports(node: Node) -> list[ImportStatement]:
    """Extract all ImportStatements from an import_declaration."""
    imports: list[ImportStatement] = []
    line = node.start_point.row + 1

    # Single: import "fmt"
    spec = _find_child_by_type(node, "import_spec")
    if spec:
        imp = _extract_import_spec(spec, line)
        if imp:
            imports.append(imp)
        return imports

    # Grouped: import ( "fmt" \n "os" )
    spec_list = _find_child_by_type(node, "import_spec_list")
    if spec_list:
        for child in spec_list.children:
            if child.type == "import_spec":
                imp = _extract_import_spec(child, child.start_point.row + 1)
                if imp:
                    imports.append(imp)

    return imports


# ---------------------------------------------------------------------------
# Struct and interface extraction (as ClassDefinition)
# ---------------------------------------------------------------------------


def _extract_interface_methods(
    interface_node: Node,
    interface_name: str,
) -> list[FunctionSignature]:
    """Extract method_elem children from an interface_type as FunctionSignatures.

    Go interface: type Reader interface { Read(p []byte) (n int, err error) }
    method_elem has: field_identifier, parameter_list (params), parameter_list (return)
    """
    methods: list[FunctionSignature] = []
    for child in interface_node.children:
        if child.type != "method_elem":
            continue
        name_node = _find_child_by_type(child, "field_identifier")
        name = _node_text(name_node) if name_node else "<anonymous>"
        param_lists = _find_children_by_type(child, "parameter_list")
        params_node = param_lists[0] if param_lists else None
        return_type_node = param_lists[1] if len(param_lists) >= 2 else None
        parameters: list[Parameter] = []
        params_text = "()"
        if params_node:
            params_text = _node_text(params_node)
            for pchild in params_node.children:
                if pchild.type == "parameter_declaration":
                    parameters.extend(_extract_go_parameters(pchild))
        return_type = _node_text(return_type_node) if return_type_node else None
        raw = _build_go_raw_signature(name, params_text, return_type)
        methods.append(FunctionSignature(
            kind="interface_method",
            name=name,
            parameters=parameters,
            return_type=return_type,
            is_async=False,
            is_static=False,
            is_exported=_is_exported(name),
            decorators=[],
            docstring=None,
            parent_class=interface_name,
            file=None,
            line_start=child.start_point.row + 1,
            line_end=child.end_point.row + 1,
            raw_signature=raw,
            ast_hash=_ast_hash(child),
        ))
    return methods


def _extract_type_declaration(node: Node) -> Optional[ClassDefinition]:
    """Extract type_declaration with struct_type or interface_type as ClassDefinition."""
    type_spec = _find_child_by_type(node, "type_spec")
    if not type_spec:
        return None

    name_node = _find_child_by_type(type_spec, "type_identifier")
    name = _node_text(name_node) if name_node else "<anonymous>"

    struct_node = _find_child_by_type(type_spec, "struct_type")
    if struct_node:
        return ClassDefinition(
            name=name,
            kind="struct",
            methods=[],  # Struct fields not extracted as methods
            bases=[],
            docstring=_get_doc_comment(node),
            file=None,
            line_start=node.start_point.row + 1,
            line_end=node.end_point.row + 1,
            ast_hash=_ast_hash(node),
        )

    interface_node = _find_child_by_type(type_spec, "interface_type")
    if interface_node:
        methods = _extract_interface_methods(interface_node, name)
        return ClassDefinition(
            name=name,
            kind="interface",
            methods=methods,
            bases=[],
            docstring=_get_doc_comment(node),
            file=None,
            line_start=node.start_point.row + 1,
            line_end=node.end_point.row + 1,
            ast_hash=_ast_hash(node),
        )

    return None


# ---------------------------------------------------------------------------
# Main export
# ---------------------------------------------------------------------------


def extract_go(
    root: Node,
) -> tuple[list[FunctionSignature], list[ClassDefinition], list[ImportStatement]]:
    """Extract functions, structs/interfaces, and imports from Go source AST.

    Args:
        root: The root node of a tree-sitter parse tree for Go source.

    Returns:
        A tuple of (functions, classes, imports) where:
        - functions: top-level func declarations and methods
        - classes: struct and interface type definitions
        - imports: all import statements
    """
    functions: list[FunctionSignature] = []
    classes: list[ClassDefinition] = []
    imports: list[ImportStatement] = []

    for child in root.children:
        if child.type in ("function_declaration", "method_declaration"):
            functions.append(_extract_go_function(child))
        elif child.type == "import_declaration":
            imports.extend(_extract_imports(child))
        elif child.type == "type_declaration":
            cls = _extract_type_declaration(child)
            if cls:
                classes.append(cls)

    return functions, classes, imports
