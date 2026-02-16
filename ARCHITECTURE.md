# Architecture - Open Memory Protocol (OMP)

This document outlines the core architectural decisions and specifications for the Open Memory Protocol. These choices prioritize determinism, cross-session integrity, and interoperability between the symbolic and semantic memory tracks.

## 1. Storage Interface & Schema Evolution

**Status:** Forward-Compatible (v0.1.0)

The current `SQLiteStorage` backend stores extraction data as JSON blobs in a single `data` column. This is sufficient for single-project, single-user workflows but has known performance limitations for cross-file queries (see [Known Limitations](#4-known-limitations--trade-offs)).

### Design Choice

The `BaseStorage` abstract class includes three relational query methods with default implementations that scan all files in memory:

- `find_by_dependency(module)` - Locates all extractions that import a specific module.
- `find_by_qualified_name(name)` - Looks up extractions containing a specific function or method.
- `list_stale(current_hashes)` - Returns file paths where the stored `file_hash` doesn't match the provided current hash.

These defaults work by iterating over `list_files()` / `get_by_file()`. High-performance backends (e.g. PostgreSQL with indexed columns) should override them with native queries. This design prevents breaking changes for third-party storage implementations as the protocol matures.

### Current Schema (SQLite v0.1)

```sql
CREATE TABLE extractions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_id    TEXT UNIQUE,
    file              TEXT UNIQUE,    -- one extraction per file (upsert)
    language          TEXT,
    file_hash         TEXT,
    timestamp         TEXT,
    data              TEXT            -- full ExtractionResult as JSON
);
```

## 2. Hashing Semantics

**Status:** Intentional Sensitivity (Fail-Safe)

OMP uses SHA-256 hashes to detect when stored memories have drifted from the actual source code.

### Current Implementation

| Hash | Scope | Input | Purpose |
|------|-------|-------|---------|
| `file_hash` | Per file | Raw file bytes | Detect *any* file change |
| `ast_hash` | Per function/class | Raw bytes of the specific AST node | Detect changes to a specific symbol |

Both are truncated to 16 hex characters (64 bits) for storage efficiency.

### Why Full-Node Hashing (Not Signature-Only)

In v0.1, the `ast_hash` covers the entire AST node - including the function body, comments, and internal logic. This means renaming a local variable inside a function will change the hash, even though the *signature* didn't change.

This is intentional. For a memory system, it is better to over-report staleness ("this function changed - re-verify") than to silently serve an outdated understanding of the function's internal behavior. The cost of a false positive (unnecessary re-parse) is negligible. The cost of a false negative (hallucinated logic) breaks trust.

### Future: Contract Hash

A future iteration will introduce a `contract_hash` that hashes only the name, parameters, and return type. This will allow consumers to distinguish between:

- **Contract change** - The API surface changed. Downstream callers may break.
- **Implementation change** - The internals changed, but the contract is stable.

## 3. The Qualified Name (QN) Format

**Status:** v0.1 - Class-Level Hierarchy

To ensure consistent indexing across storage backends, OMP uses a standardized `qualified_name` format as the primary lookup key.

### Current Format (v0.1)

```
[ParentClass].[symbol_name]
```

Examples from the actual codebase:

| Code | `qualified_name` |
|------|------------------|
| `def greet(name: str)` | `greet` |
| `class AuthService` > `def validate_token(...)` | `AuthService.validate_token` |
| `func (s *Server) Handle(...)` (Go) | `Server.Handle` |
| `interface UserRepo` > `findById(...)` (TS) | `UserRepo.findById` |

The `active_pointer` property provides the file-anchored location in `file#L<start>-L<end>` format (e.g. `src/auth/provider.ts#L42-L58`).

### Future: File-Qualified Names

A future version will prepend the file path for cross-file uniqueness:

```
[file_path]::[class_hierarchy].[symbol_name]
```

For example: `src/auth/provider.ts::AuthService.validateToken`

**Rules for this future format:**
1. Use `::` to separate the file system context from code symbols. Use `.` for class nesting.
2. In languages with overloading (TypeScript, Go), append a parameter-type hash if signatures collide (e.g. `Method.0`, `Method.1`).
3. The `qualified_name` is the primary key linking Semantic Track intent to Symbolic Track facts. Changing this format in a custom parser will decouple stored memory from the code.

## 4. Known Limitations & Trade-offs

| Limitation | Impact | Mitigation Path |
|------------|--------|-----------------|
| **Hash truncation** | 64-bit hash has collision probability ~1 in 2^32 at ~65k symbols. | Sufficient for single projects. Postgres backend can store full 256-bit hashes. |
| **JSON blob storage** | Cross-file queries (`find_by_dependency`, etc.) scan all files in memory - O(N). | Override in relational backends with indexed columns. |
| **Body-sensitive hashing** | Comment-only changes trigger staleness. | Acceptable false-positive rate. `contract_hash` planned for v0.2. |
| **No nested class QN** | `qualified_name` doesn't handle `Outer.Inner.method`. | Rare in practice. Will extend in v0.2 with `::` format. |
| **No cross-file dependency graph** | Imports are extracted per-file but not resolved into a project-wide graph. | Planned for v0.2 with `extract_project()` + storage integration. |
