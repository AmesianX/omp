"""
OMP Data Models - The Symbolic Layer schema.

These dataclasses define the exact shape of every fact that the deterministic
parser produces.  An LLM Observer is *forbidden* from rewriting any field in
the symbolic layer; it may only populate the semantic layer (see observer.py).
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Atomic building blocks
# ---------------------------------------------------------------------------


@dataclass
class Parameter:
    """A single function/method parameter."""

    name: str
    type: Optional[str] = None
    default: Optional[str] = None
    optional: bool = False

    def __str__(self) -> str:
        parts = [self.name]
        if self.type:
            parts.append(f": {self.type}")
        if self.optional and not self.default:
            parts[-1] += "?"
        if self.default:
            parts.append(f" = {self.default}")
        return "".join(parts)


@dataclass
class ImportStatement:
    """A single import / require / use statement."""

    module: str                      # e.g. "jsonwebtoken", "os.path"
    names: list[str] = field(default_factory=list)  # e.g. ["sign", "verify"]
    alias: Optional[str] = None      # e.g. "import jwt as jw" -> alias="jw"
    is_wildcard: bool = False         # e.g. "from x import *"
    line: int = 0


# ---------------------------------------------------------------------------
# Core signature types
# ---------------------------------------------------------------------------


@dataclass
class FunctionSignature:
    """A deterministic, parser-extracted function signature."""

    kind: str  # "function" | "method" | "arrow_function" | "interface_method"
    name: str
    parameters: list[Parameter] = field(default_factory=list)
    return_type: Optional[str] = None
    is_async: bool = False
    is_static: bool = False
    is_exported: bool = False
    decorators: list[str] = field(default_factory=list)
    docstring: Optional[str] = None
    parent_class: Optional[str] = None
    file: Optional[str] = None
    line_start: int = 0
    line_end: int = 0
    raw_signature: str = ""
    ast_hash: str = ""

    # -- Derived helpers --

    @property
    def qualified_name(self) -> str:
        """Fully-qualified ``Class.method`` identifier for cross-file lookups."""
        if self.parent_class:
            return f"{self.parent_class}.{self.name}"
        return self.name

    @property
    def active_pointer(self) -> str:
        """Linkage pointer in ``file#L<start>-L<end>`` format."""
        if self.file:
            return f"{self.file}#L{self.line_start}-L{self.line_end}"
        return f"#L{self.line_start}-L{self.line_end}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["qualified_name"] = self.qualified_name
        d["active_pointer"] = self.active_pointer
        return d


@dataclass
class ClassDefinition:
    """A class / struct / interface extracted from source."""

    name: str
    kind: str = "class"  # "class" | "interface" | "struct" | "type_alias"
    methods: list[FunctionSignature] = field(default_factory=list)
    bases: list[str] = field(default_factory=list)
    docstring: Optional[str] = None
    file: Optional[str] = None
    line_start: int = 0
    line_end: int = 0
    ast_hash: str = ""

    @property
    def active_pointer(self) -> str:
        if self.file:
            return f"{self.file}#L{self.line_start}-L{self.line_end}"
        return f"#L{self.line_start}-L{self.line_end}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["active_pointer"] = self.active_pointer
        return d


# ---------------------------------------------------------------------------
# Extraction result - the full "observation" envelope
# ---------------------------------------------------------------------------


def _make_observation_id() -> str:
    return f"obs_{uuid.uuid4().hex[:12]}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ExtractionResult:
    """Complete output of a single parse run.

    Maps to the ``symbolic_layer`` of the Dual-Track Memory schema
    defined in the OMP spec (fixme.md §Dual-Track Memory Schema).
    """

    file: str
    language: str
    functions: list[FunctionSignature] = field(default_factory=list)
    classes: list[ClassDefinition] = field(default_factory=list)
    imports: list[ImportStatement] = field(default_factory=list)
    file_hash: str = ""
    observation_id: str = field(default_factory=_make_observation_id)
    timestamp: str = field(default_factory=_now_iso)

    # -- Staleness helpers --

    @property
    def all_dependencies(self) -> list[str]:
        """Flat list of every imported module name."""
        return [imp.module for imp in self.imports]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["all_dependencies"] = self.all_dependencies
        return d

    def to_symbolic_layer(self) -> dict:
        """Produce the ``symbolic_layer`` block for the Dual-Track schema."""
        facts = []
        for fn in self.functions:
            facts.append({
                "type": "function_signature",
                "identifier": fn.qualified_name,
                "file": fn.file or self.file,
                "raw_contract": fn.raw_signature,
                "dependencies": self.all_dependencies,
                "ast_hash": fn.ast_hash,
                "active_pointer": fn.active_pointer,
            })
        for cls in self.classes:
            for m in cls.methods:
                facts.append({
                    "type": "function_signature",
                    "identifier": m.qualified_name,
                    "file": m.file or self.file,
                    "raw_contract": m.raw_signature,
                    "dependencies": self.all_dependencies,
                    "ast_hash": m.ast_hash,
                    "active_pointer": m.active_pointer,
                })
        return {
            "source": "PARSER",
            "veracity": "DETERMINISTIC",
            "facts": facts,
        }


# ---------------------------------------------------------------------------
# Project-level result
# ---------------------------------------------------------------------------


@dataclass
class ProjectExtractionResult:
    """Aggregated result from scanning an entire project directory."""

    root: str
    files: list[ExtractionResult] = field(default_factory=list)
    observation_id: str = field(default_factory=_make_observation_id)
    timestamp: str = field(default_factory=_now_iso)

    @property
    def total_functions(self) -> int:
        return sum(len(f.functions) for f in self.files)

    @property
    def total_classes(self) -> int:
        return sum(len(f.classes) for f in self.files)

    @property
    def total_imports(self) -> int:
        return sum(len(f.imports) for f in self.files)

    def to_dict(self) -> dict:
        return {
            "root": self.root,
            "observation_id": self.observation_id,
            "timestamp": self.timestamp,
            "total_functions": self.total_functions,
            "total_classes": self.total_classes,
            "total_imports": self.total_imports,
            "files": [f.to_dict() for f in self.files],
        }


# ---------------------------------------------------------------------------
# Staleness check result
# ---------------------------------------------------------------------------


@dataclass
class StalenessReport:
    """Result of comparing a stored ExtractionResult against the current file."""

    file: str
    is_stale: bool
    stored_file_hash: str
    current_file_hash: str
    changed_functions: list[str] = field(default_factory=list)
    removed_functions: list[str] = field(default_factory=list)
    added_functions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
