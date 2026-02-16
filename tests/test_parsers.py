"""Tests for OMP language parsers (Python, TypeScript, Go)."""

from omp import extract_from_source


class TestPythonParser:
    def test_simple_function(self):
        result = extract_from_source("def greet(name: str) -> str: pass", "python")
        assert len(result.functions) == 1
        fn = result.functions[0]
        assert fn.name == "greet"
        assert fn.parameters[0].name == "name"
        assert fn.parameters[0].type == "str"
        assert fn.return_type == "str"

    def test_async_function(self):
        result = extract_from_source("async def fetch() -> dict: pass", "python")
        assert len(result.functions) == 1
        assert result.functions[0].is_async is True

    def test_default_params(self):
        result = extract_from_source(
            'def foo(x: int = 5, y: str = "hi"): pass', "python"
        )
        assert len(result.functions) == 1
        params = result.functions[0].parameters
        assert params[0].name == "x"
        assert params[0].default == "5"
        assert params[1].name == "y"
        assert params[1].default == '"hi"'

    def test_args_kwargs(self):
        result = extract_from_source("def foo(*args, **kwargs): pass", "python")
        assert len(result.functions) == 1
        params = result.functions[0].parameters
        assert params[0].name == "*args"
        assert params[1].name == "**kwargs"

    def test_class_methods(self):
        code = """
class Foo:
    def __init__(self, x: int):
        pass
    def regular(self, y: str):
        pass
    @staticmethod
    def static_meth(z: int):
        pass
"""
        result = extract_from_source(code.strip(), "python")
        assert len(result.classes) == 1
        cls = result.classes[0]
        methods = cls.methods
        assert len(methods) == 3
        init = next(m for m in methods if m.name == "__init__")
        assert init.parent_class == "Foo"
        assert init.parameters[0].name == "x"
        regular = next(m for m in methods if m.name == "regular")
        assert regular.parent_class == "Foo"
        assert regular.is_static is False
        static_m = next(m for m in methods if m.name == "static_meth")
        assert static_m.is_static is True

    def test_class_bases(self):
        result = extract_from_source("class Foo(Bar, Baz): pass", "python")
        assert len(result.classes) == 1
        assert result.classes[0].bases == ["Bar", "Baz"]

    def test_docstring(self):
        code = '''
def documented():
    """This is the docstring."""
    pass
'''
        result = extract_from_source(code.strip(), "python")
        assert len(result.functions) == 1
        assert result.functions[0].docstring == "This is the docstring."

    def test_decorators(self):
        code = """
@app.route("/")
def index():
    pass
"""
        result = extract_from_source(code.strip(), "python")
        assert len(result.functions) == 1
        decorators = result.functions[0].decorators
        assert len(decorators) >= 1
        assert any("app.route" in d or "route" in d for d in decorators)

    def test_import_simple(self):
        result = extract_from_source("import os", "python")
        assert len(result.imports) == 1
        assert result.imports[0].module == "os"

    def test_import_from(self):
        result = extract_from_source("from pathlib import Path", "python")
        assert len(result.imports) == 1
        assert result.imports[0].module == "pathlib"
        assert "Path" in result.imports[0].names

    def test_import_alias(self):
        result = extract_from_source("import numpy as np", "python")
        assert len(result.imports) == 1
        assert result.imports[0].alias == "np"

    def test_import_wildcard(self):
        result = extract_from_source("from os import *", "python")
        assert len(result.imports) == 1
        assert result.imports[0].is_wildcard is True

    def test_qualified_name(self):
        code = """
class MyClass:
    def my_method(self):
        pass
"""
        result = extract_from_source(code.strip(), "python")
        assert len(result.classes[0].methods) == 1
        assert result.classes[0].methods[0].qualified_name == "MyClass.my_method"

    def test_ast_hash_deterministic(self):
        code = "def foo(): pass"
        r1 = extract_from_source(code, "python")
        r2 = extract_from_source(code, "python")
        assert r1.functions[0].ast_hash == r2.functions[0].ast_hash

    def test_ast_hash_changes(self):
        r1 = extract_from_source("def foo(): pass", "python")
        r2 = extract_from_source("def foo(x: int): pass", "python")
        assert r1.functions[0].ast_hash != r2.functions[0].ast_hash


class TestTypeScriptParser:
    def test_function_declaration(self):
        result = extract_from_source(
            "function add(x: number, y: number): number { return x + y; }",
            "typescript",
        )
        assert len(result.functions) == 1
        fn = result.functions[0]
        assert fn.name == "add"
        assert len(fn.parameters) == 2
        assert fn.return_type is not None and "number" in fn.return_type

    def test_async_function(self):
        result = extract_from_source(
            "async function fetch(): Promise<void> { }", "typescript"
        )
        assert len(result.functions) == 1
        assert result.functions[0].is_async is True

    def test_arrow_function(self):
        result = extract_from_source(
            "const foo = (x: string): number => x.length;", "typescript"
        )
        assert len(result.functions) == 1
        fn = result.functions[0]
        assert fn.name == "foo"
        assert fn.kind == "arrow_function"
        assert len(fn.parameters) == 1
        assert fn.parameters[0].type is not None and "string" in fn.parameters[0].type

    def test_exported_function(self):
        result = extract_from_source(
            "export function pub() { }", "typescript"
        )
        assert len(result.functions) == 1
        assert result.functions[0].is_exported is True

    def test_class_with_methods(self):
        code = """
class Service {
    async run(): Promise<void> { }
    static create(): Service { return new Service(); }
}
"""
        result = extract_from_source(code.strip(), "typescript")
        assert len(result.classes) == 1
        methods = result.classes[0].methods
        async_m = next(m for m in methods if m.name == "run")
        assert async_m.is_async is True
        static_m = next(m for m in methods if m.name == "create")
        assert static_m.is_static is True

    def test_interface_methods(self):
        code = """
interface Reader {
    read(): string;
    count: number;
}
"""
        result = extract_from_source(code.strip(), "typescript")
        iface_methods = [f for f in result.functions if f.kind == "interface_method"]
        assert len(iface_methods) >= 1
        read_m = next((m for m in iface_methods if m.name == "read"), None)
        assert read_m is not None
        assert read_m.kind == "interface_method"

    def test_optional_params(self):
        result = extract_from_source(
            "function opt(x?: string): void { }", "typescript"
        )
        assert len(result.functions) == 1
        assert result.functions[0].parameters[0].optional is True

    def test_import_named(self):
        result = extract_from_source('import { a, b } from "module";', "typescript")
        assert len(result.imports) == 1
        assert result.imports[0].module == "module"
        assert "a" in result.imports[0].names
        assert "b" in result.imports[0].names

    def test_import_default(self):
        result = extract_from_source('import foo from "module";', "typescript")
        assert len(result.imports) == 1
        assert result.imports[0].module == "module"
        assert "foo" in result.imports[0].names

    def test_import_wildcard(self):
        result = extract_from_source('import * as ns from "module";', "typescript")
        assert len(result.imports) == 1
        assert result.imports[0].is_wildcard is True
        assert result.imports[0].alias == "ns"


class TestGoParser:
    def test_simple_function(self):
        result = extract_from_source(
            "func Add(a int, b int) int { return a + b }", "go"
        )
        assert len(result.functions) == 1
        fn = result.functions[0]
        assert fn.name == "Add"
        assert fn.return_type == "int"
        if fn.parameters:
            assert fn.parameters[0].name == "a"
            assert fn.parameters[0].type == "int"

    def test_method(self):
        code = """
package main

import "net/http"

func (s *Server) Handle(w http.ResponseWriter) {
}
"""
        result = extract_from_source(code.strip(), "go")
        method = next(
            (f for f in result.functions if f.kind == "method" and f.name == "Handle"),
            None,
        )
        assert method is not None
        assert method.parent_class == "Server"

    def test_exported_detection(self):
        r_exported = extract_from_source("func Public() {}", "go")
        r_private = extract_from_source("func private() {}", "go")
        assert r_exported.functions[0].is_exported is True
        assert r_private.functions[0].is_exported is False

    def test_imports(self):
        code = """
package main

import (
    "fmt"
    "os"
)
"""
        result = extract_from_source(code.strip(), "go")
        modules = [imp.module for imp in result.imports]
        assert "fmt" in modules
        assert "os" in modules

    def test_struct(self):
        code = """
package main

type Server struct {
}
"""
        result = extract_from_source(code.strip(), "go")
        assert len(result.classes) == 1
        assert result.classes[0].kind == "struct"
        assert result.classes[0].name == "Server"

    def test_interface(self):
        code = """
package main

type Reader interface {
    Read()
}
"""
        result = extract_from_source(code.strip(), "go")
        assert len(result.classes) == 1
        assert result.classes[0].kind == "interface"
        assert result.classes[0].name == "Reader"
        assert len(result.classes[0].methods) >= 1
        read_m = next(m for m in result.classes[0].methods if m.name == "Read")
        assert read_m.kind == "interface_method"
