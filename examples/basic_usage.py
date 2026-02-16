#!/usr/bin/env python3
"""
OMP Basic Usage Example
=======================

Demonstrates the core OMP workflow:
1. Extract symbolic facts from source code
2. Check for staleness
3. Store results in SQLite
4. Build a Dual-Track memory with Observer integration
"""

from omp import (
    extract_from_source,
    diff_extractions,
    SQLiteStorage,
    SemanticObservation,
    build_observer_prompt,
    reconcile,
)
import json


def main():
    # ----------------------------------------------------------------
    # 1. Extract symbolic facts from Python source
    # ----------------------------------------------------------------
    python_code = '''
import jwt
from datetime import datetime

class AuthService:
    """Handles JWT-based authentication."""

    def __init__(self, secret: str):
        self.secret = secret

    async def validate_token(self, token: str) -> dict | None:
        """Validate a JWT and return the payload if valid."""
        try:
            return jwt.decode(token, self.secret, algorithms=["HS256"])
        except jwt.InvalidTokenError:
            return None

    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a password using bcrypt."""
        return "hashed"
'''

    result = extract_from_source(python_code, "python", file="src/auth/service.py")

    print("=" * 60)
    print("  1. SYMBOLIC EXTRACTION")
    print("=" * 60)
    print(f"  File: {result.file}")
    print(f"  Observation ID: {result.observation_id}")
    print(f"  Timestamp: {result.timestamp}")
    print(f"  File Hash: {result.file_hash}")
    print()
    print(f"  Imports ({len(result.imports)}):")
    for imp in result.imports:
        names = ", ".join(imp.names) if imp.names else imp.module
        print(f"    - {imp.module}: {names}")
    print()
    print(f"  Classes ({len(result.classes)}):")
    for cls in result.classes:
        print(f"    - {cls.name} ({cls.active_pointer})")
        for m in cls.methods:
            params = ", ".join(str(p) for p in m.parameters)
            ret = f" -> {m.return_type}" if m.return_type else ""
            prefix = "async " if m.is_async else ""
            print(f"        {prefix}{m.qualified_name}({params}){ret}")
            if m.docstring:
                print(f"          \"{m.docstring}\"")

    # ----------------------------------------------------------------
    # 2. Symbolic Layer output (for the Dual-Track schema)
    # ----------------------------------------------------------------
    print()
    print("=" * 60)
    print("  2. SYMBOLIC LAYER (Dual-Track Schema)")
    print("=" * 60)
    symbolic = result.to_symbolic_layer()
    print(json.dumps(symbolic, indent=2))

    # ----------------------------------------------------------------
    # 3. Staleness detection
    # ----------------------------------------------------------------
    print()
    print("=" * 60)
    print("  3. STALENESS DETECTION")
    print("=" * 60)

    # Simulate a code change: rename method + add new one
    modified_code = python_code.replace(
        "async def validate_token(self, token: str) -> dict | None:",
        "async def verify_token(self, token: str, strict: bool = False) -> dict | None:",
    ) + '''
    def revoke_token(self, token: str) -> bool:
        """Revoke an active token."""
        return True
'''

    modified_result = extract_from_source(modified_code, "python", file="src/auth/service.py")
    report = diff_extractions(result, modified_result)

    print(f"  Is stale: {report.is_stale}")
    print(f"  Added: {report.added_functions}")
    print(f"  Removed: {report.removed_functions}")
    print(f"  Changed: {report.changed_functions}")

    # ----------------------------------------------------------------
    # 4. SQLite storage
    # ----------------------------------------------------------------
    print()
    print("=" * 60)
    print("  4. SQLITE STORAGE")
    print("=" * 60)

    with SQLiteStorage(":memory:") as store:
        store.save(result)
        store.save(modified_result)  # Overwrites (same file)

        loaded = store.get_by_file("src/auth/service.py")
        print(f"  Stored files: {store.list_files()}")
        print(f"  Loaded: {loaded.observation_id} ({len(loaded.functions)} top-level fns)")
        print(f"  Classes: {[c.name for c in loaded.classes]}")

    # ----------------------------------------------------------------
    # 5. Observer integration (Semantic Track)
    # ----------------------------------------------------------------
    print()
    print("=" * 60)
    print("  5. OBSERVER / DUAL-TRACK RECONCILIATION")
    print("=" * 60)

    # Build the prompt you'd send to an LLM
    prompt = build_observer_prompt(
        user_message="Make validate_token stricter and add revocation",
        agent_response="Renamed to verify_token with strict param, added revoke_token method",
    )
    print(f"  Observer prompt ({len(prompt)} chars) ready for LLM...")

    # Simulate what the Observer LLM would return
    semantic = SemanticObservation(
        intent_summary="Hardening auth: stricter validation + token revocation",
        implicit_constraints=["Must maintain backward compat with existing JWT tokens"],
        user_preferences=["Prefers explicit boolean flags over config objects"],
        bias_warnings=["User may be over-engineering due to recent security incident"],
    )

    # Reconcile into the full Dual-Track Memory
    memory = reconcile(modified_result, semantic, original_snippet_ref="ctx_store_001")

    print()
    print("  Full Dual-Track Memory:")
    print(json.dumps(memory.to_dict(), indent=2))


if __name__ == "__main__":
    main()
