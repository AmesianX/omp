"""
Open Memory Protocol (OMP)
==========================

The Deterministic Memory Layer for AI Coding Agents.

OMP decouples **Intent** (semantic, probabilistic) from **Syntax**
(symbolic, deterministic) to create a lossless Dual-Track memory system
that works with any LLM.

Quick start::

    from omp import extract_from_file, extract_from_source, extract_project

    # Single file
    result = extract_from_file("src/auth/provider.ts")

    # Source string
    result = extract_from_source("def hello(): pass", "python")

    # Entire project
    project = extract_project("./my-project")

    # Staleness detection
    from omp import check_staleness
    report = check_staleness(result)
    if report.is_stale:
        print(f"Changed: {report.changed_functions}")
"""

__version__ = "0.1.0"

# Core API
from omp.core import (
    extract_from_file,
    extract_from_source,
    extract_project,
    check_staleness,
    diff_extractions,
)

# Data models
from omp.models import (
    Parameter,
    ImportStatement,
    FunctionSignature,
    ClassDefinition,
    ExtractionResult,
    ProjectExtractionResult,
    StalenessReport,
)

# Observer (Semantic Track)
from omp.observer import (
    SemanticObservation,
    DualTrackMemory,
    build_observer_prompt,
    reconcile,
    OBSERVER_SYSTEM_PROMPT,
)

# Storage
from omp.storage import BaseStorage, SQLiteStorage

# Watcher
from omp.watcher import FileWatcher, WatchEvent

__all__ = [
    # Core
    "extract_from_file",
    "extract_from_source",
    "extract_project",
    "check_staleness",
    "diff_extractions",
    # Models
    "Parameter",
    "ImportStatement",
    "FunctionSignature",
    "ClassDefinition",
    "ExtractionResult",
    "ProjectExtractionResult",
    "StalenessReport",
    # Observer
    "SemanticObservation",
    "DualTrackMemory",
    "build_observer_prompt",
    "reconcile",
    "OBSERVER_SYSTEM_PROMPT",
    # Storage
    "BaseStorage",
    "SQLiteStorage",
    # Watcher
    "FileWatcher",
    "WatchEvent",
]
