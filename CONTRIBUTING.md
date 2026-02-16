# Contributing to Open Memory Protocol (OMP)

Thank you for helping us solve context rot. OMP is built on the belief that AI memory should be verifiable, deterministic, and structured. By contributing, you are helping build the truth layer for the next generation of AI coding agents.

## Project Philosophy

- **Decouple Intent from Syntax.** We never ask an LLM to remember a function signature if a parser can find it.
- **Local-First.** Parsers and basic storage run on a developer's machine with zero network calls.
- **Stability over Speed.** A "Stale" memory is better than a "Hallucinated" one.

## Where Can You Help?

### 1. Adding Language Parsers (High Priority)

We currently support **Python, TypeScript/JavaScript, and Go**. We want parsers for Rust, Ruby, Java, C#, and more.

**How parsers work:**

Each language has a standalone module at `omp/parsers/<language>.py` that exports a single function:

```python
def extract_<language>(root: tree_sitter.Node) -> tuple[
    list[FunctionSignature],
    list[ClassDefinition],
    list[ImportStatement],
]:
```

The function receives a tree-sitter root node and returns three lists: function signatures, class definitions, and import statements. See `omp/parsers/python.py` as the reference implementation.

**To add a new language (e.g. Rust):**

1. Create `omp/parsers/rust.py` with an `extract_rust(root)` function.
2. Register the language in `omp/parsers/__init__.py`:
   - Add the `tree-sitter-rust` grammar to `_register_languages()`
   - Add `"rust": extract_rust` to the `EXTRACTORS` dict
   - Add the file extension mapping (e.g. `".rs"`)
3. Add tests in `tests/test_parsers.py` in a `TestRustParser` class.
4. Your parser **must** correctly populate `qualified_name` (via `parent_class` + `name`) and `ast_hash` (via the `ast_hash()` helper in `omp/parsers/base.py`).

Shared helpers like `node_text()`, `ast_hash()`, `find_child_by_type()`, and `extract_docstring()` are available in `omp/parsers/base.py`.

### 2. Storage Backends

The current `SQLiteStorage` uses JSON blobs. We need backends where cross-file queries (`find_by_dependency`, `find_by_qualified_name`, `list_stale`) are fast.

**To add a new backend (e.g. PostgreSQL):**

1. Create `omp/storage/postgres.py` implementing `BaseStorage`.
2. The abstract base in `omp/storage/base.py` defines all required methods. The `find_by_*` and `list_stale` methods have default O(N) implementations - your backend should override them with indexed queries.
3. Add tests in `tests/test_storage.py`.

### 3. Observer Prompts & Evaluations

Help us refine how the Semantic Track captures developer intent without introducing bias.

- The Observer prompt lives in `omp/observer.py` (`OBSERVER_SYSTEM_PROMPT`).
- Propose improvements by opening an issue with your prompt variant and example outputs.
- We don't have a formal benchmark suite yet - building one is a great first contribution (see [Open Issues](#open-issues) below).

## Development Setup

**Prerequisites:** Python 3.10+

```bash
# Clone the repo
git clone https://github.com/open-memory-protocol/omp.git
cd omp

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install in development mode with all language grammars
pip install -e ".[dev]"

# Run the test suite
pytest tests/ -v
```

All 53 tests should pass in under 1 second.

## Pull Request Guidelines

1. **Atomic PRs.** One PR per language parser or storage backend. Don't mix features.
2. **Tests required.** Every new parser needs tests covering: functions, classes/methods, imports, and edge cases (async, static, decorators/annotations). Every storage backend needs tests for save/retrieve, upsert, delete, and the `find_by_*` methods.
3. **No regression.** `pytest` must pass at 100% before merging.
4. **Document trade-offs.** If your parser handles a language-specific edge case (like C++ templates, Rust lifetimes, or Java generics), document the decision in your PR description.
5. **Update ARCHITECTURE.md** if your change alters hashing behavior, the `qualified_name` format, or the `BaseStorage` interface.

## Open Issues (Good First Contributions)

- **Rust parser** - `omp/parsers/rust.py` using `tree-sitter-rust`
- **Java parser** - `omp/parsers/java.py` using `tree-sitter-java`
- **Benchmark suite** - A `benchmarks/` folder with a test that verifies extraction accuracy over 50+ simulated agent turns
- **PostgreSQL storage** - `omp/storage/postgres.py` with indexed dependency and symbol lookups
- **`contract_hash`** - Hash only the function signature (name + params + return type), separate from the body-inclusive `ast_hash`

## Code of Conduct

We are building a technical protocol. Keep discussions focused on technical trade-offs, performance, and accuracy. Respect the Dual-Track separation - do not submit PRs that merge symbolic facts into semantic blobs.

## Communication

- **Issues:** Bug reports and feature proposals (RFCs).
- **Discussions:** "How-to" questions and architectural debates.
