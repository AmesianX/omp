"""OMP Command-Line Interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from omp.core import extract_from_file, extract_project


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="omp",
        description="Open Memory Protocol - Deterministic code extraction",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="File or directory paths to extract from",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    parser.add_argument(
        "--symbolic",
        action="store_true",
        help="Output only the symbolic_layer (Dual-Track schema format)",
    )
    parser.add_argument(
        "--project",
        action="store_true",
        help="Treat path as a project directory and scan recursively",
    )
    parser.add_argument(
        "--exclude",
        nargs="*",
        default=None,
        help="Directories to exclude when scanning a project",
    )

    args = parser.parse_args()

    if not args.paths:
        parser.print_help()
        sys.exit(1)

    for target in args.paths:
        path = Path(target)

        if args.project or path.is_dir():
            exclude = set(args.exclude) if args.exclude else None
            result = extract_project(path, exclude_dirs=exclude)
            if args.json:
                print(json.dumps(result.to_dict(), indent=2))
            else:
                print(f"\nProject: {result.root}")
                print(f"Files: {len(result.files)}")
                print(f"Functions: {result.total_functions}")
                print(f"Classes: {result.total_classes}")
                print(f"Imports: {result.total_imports}")
                for fr in result.files:
                    _print_file_result(fr, args.symbolic)
        else:
            try:
                result = extract_from_file(path)
                if args.json:
                    print(json.dumps(result.to_dict(), indent=2))
                elif args.symbolic:
                    print(json.dumps(result.to_symbolic_layer(), indent=2))
                else:
                    _print_file_result(result)
            except (ValueError, FileNotFoundError) as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(1)


def _print_file_result(result, symbolic: bool = False) -> None:
    """Pretty-print an ExtractionResult."""
    if symbolic:
        print(json.dumps(result.to_symbolic_layer(), indent=2))
        return

    print(f"\n{'='*60}")
    print(f"  {result.file} [{result.language}]")
    print(f"  hash: {result.file_hash}  |  obs: {result.observation_id}")
    print(f"{'='*60}")

    if result.imports:
        print(f"\n  Imports ({len(result.imports)}):")
        for imp in result.imports:
            if imp.names:
                print(f"    from {imp.module} import {', '.join(imp.names)}")
            elif imp.is_wildcard:
                alias = f" as {imp.alias}" if imp.alias else ""
                print(f"    import * from {imp.module}{alias}")
            else:
                alias = f" as {imp.alias}" if imp.alias else ""
                print(f"    import {imp.module}{alias}")

    if result.functions:
        print(f"\n  Functions ({len(result.functions)}):")
        for fn in result.functions:
            _print_sig(fn)

    if result.classes:
        print(f"\n  Classes ({len(result.classes)}):")
        for cls in result.classes:
            bases = f"({', '.join(cls.bases)})" if cls.bases else ""
            print(f"    {cls.kind} {cls.name}{bases}  {cls.active_pointer}")
            for m in cls.methods:
                _print_sig(m, indent=6)


def _print_sig(fn, indent: int = 4) -> None:
    pad = " " * indent
    prefix = ""
    if fn.is_async:
        prefix += "async "
    if fn.is_exported:
        prefix += "export "
    if fn.is_static:
        prefix += "static "
    params = ", ".join(str(p) for p in fn.parameters)
    ret = f" -> {fn.return_type}" if fn.return_type else ""
    print(f"{pad}{prefix}{fn.kind} {fn.name}({params}){ret}  [{fn.ast_hash}]")


if __name__ == "__main__":
    main()
