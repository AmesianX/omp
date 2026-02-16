"""
OMP File Watcher - Monitors source files for changes and triggers re-extraction.

Detects when files have been modified outside of the agent's control
(e.g., manual IDE edits, git pulls) and marks affected memories as stale.
Uses simple polling with file modification times - no external dependencies.
"""

from __future__ import annotations

import hashlib
import time
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from omp.models import ExtractionResult, StalenessReport
from omp.parsers import EXTENSION_MAP


@dataclass
class FileState:
    """Tracked state of a single file."""
    path: str
    mtime: float
    file_hash: str


@dataclass
class WatchEvent:
    """Emitted when a watched file changes."""
    path: str
    event_type: str  # "modified" | "created" | "deleted"
    old_hash: Optional[str] = None
    new_hash: Optional[str] = None


class FileWatcher:
    """Polls a directory for source file changes.

    Usage:
        watcher = FileWatcher("/path/to/project")
        watcher.on_change(my_callback)
        watcher.start(interval=2.0)  # Poll every 2 seconds
        # ... later ...
        watcher.stop()

    Or use as a one-shot:
        events = watcher.check_once()
    """

    def __init__(
        self,
        root_dir: str | Path,
        exclude_dirs: Optional[set[str]] = None,
    ):
        self.root = Path(root_dir).resolve()
        self.exclude_dirs = exclude_dirs or {
            "node_modules", ".git", "__pycache__", ".venv",
            "venv", "dist", "build", ".next", ".tox", "vendor",
        }
        self._state: dict[str, FileState] = {}
        self._callbacks: list[Callable[[WatchEvent], None]] = []
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        # Initialize state
        self._scan_initial()

    def _scan_initial(self) -> None:
        """Build initial snapshot of all tracked files."""
        for path in self._iter_files():
            key = str(path)
            stat = path.stat()
            self._state[key] = FileState(
                path=key,
                mtime=stat.st_mtime,
                file_hash=self._hash_file(path),
            )

    def _iter_files(self):
        """Yield all source files under root that have supported extensions."""
        supported = set(EXTENSION_MAP.keys())
        for path in self.root.rglob("*"):
            if path.is_file() and path.suffix in supported:
                # Check exclusion
                parts = path.relative_to(self.root).parts
                if not any(part in self.exclude_dirs for part in parts):
                    yield path

    @staticmethod
    def _hash_file(path: Path) -> str:
        """SHA-256 hash of file contents (truncated to 16 hex chars)."""
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]

    def on_change(self, callback: Callable[[WatchEvent], None]) -> None:
        """Register a callback for file change events."""
        self._callbacks.append(callback)

    def check_once(self) -> list[WatchEvent]:
        """Perform a single scan and return any change events."""
        events: list[WatchEvent] = []
        current_files: set[str] = set()

        for path in self._iter_files():
            key = str(path)
            current_files.add(key)

            try:
                stat = path.stat()
            except OSError:
                continue

            if key not in self._state:
                # New file
                file_hash = self._hash_file(path)
                self._state[key] = FileState(path=key, mtime=stat.st_mtime, file_hash=file_hash)
                event = WatchEvent(path=key, event_type="created", new_hash=file_hash)
                events.append(event)

            elif stat.st_mtime != self._state[key].mtime:
                # Potentially modified - verify with hash
                new_hash = self._hash_file(path)
                old_hash = self._state[key].file_hash
                if new_hash != old_hash:
                    event = WatchEvent(
                        path=key, event_type="modified",
                        old_hash=old_hash, new_hash=new_hash,
                    )
                    events.append(event)
                self._state[key] = FileState(path=key, mtime=stat.st_mtime, file_hash=new_hash)

        # Check for deletions
        for key in list(self._state.keys()):
            if key not in current_files:
                event = WatchEvent(
                    path=key, event_type="deleted",
                    old_hash=self._state[key].file_hash,
                )
                events.append(event)
                del self._state[key]

        # Fire callbacks
        for event in events:
            for cb in self._callbacks:
                cb(event)

        return events

    def start(self, interval: float = 2.0) -> None:
        """Start polling in a background thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop, args=(interval,), daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the background polling thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None

    def _poll_loop(self, interval: float) -> None:
        """Internal polling loop."""
        while not self._stop_event.is_set():
            self.check_once()
            self._stop_event.wait(interval)

    @property
    def tracked_files(self) -> list[str]:
        """Return list of all currently tracked file paths."""
        return sorted(self._state.keys())

    @property
    def file_count(self) -> int:
        return len(self._state)
