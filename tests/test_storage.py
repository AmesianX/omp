"""Tests for OMP SQLite storage backend."""

import pytest
from omp import SQLiteStorage, extract_from_source


class TestSQLiteStorage:
    def test_save_and_retrieve(self):
        r = extract_from_source(
            "def foo(x: int) -> str: pass", "python", file="test.py"
        )
        with SQLiteStorage(":memory:") as store:
            store.save(r)
            loaded = store.get_by_file("test.py")
            assert loaded is not None
            assert loaded.language == "python"
            assert len(loaded.functions) == 1
            assert loaded.functions[0].name == "foo"
            assert loaded.functions[0].parameters[0].name == "x"
            assert loaded.functions[0].parameters[0].type == "int"

    def test_get_by_id(self):
        r = extract_from_source("def bar(): pass", "python", file="bar.py")
        obs_id = r.observation_id
        with SQLiteStorage(":memory:") as store:
            store.save(r)
            loaded = store.get_by_id(obs_id)
            assert loaded is not None
            assert loaded.observation_id == obs_id

    def test_list_files(self):
        r1 = extract_from_source("def a(): pass", "python", file="a.py")
        r2 = extract_from_source("def b(): pass", "python", file="b.py")
        with SQLiteStorage(":memory:") as store:
            store.save(r1)
            store.save(r2)
            files = store.list_files()
            assert "a.py" in files
            assert "b.py" in files

    def test_delete(self):
        r = extract_from_source("def x(): pass", "python", file="x.py")
        with SQLiteStorage(":memory:") as store:
            store.save(r)
            store.delete_by_file("x.py")
            loaded = store.get_by_file("x.py")
            assert loaded is None

    def test_clear(self):
        r1 = extract_from_source("def a(): pass", "python", file="a.py")
        r2 = extract_from_source("def b(): pass", "python", file="b.py")
        with SQLiteStorage(":memory:") as store:
            store.save(r1)
            store.save(r2)
            store.clear()
            files = store.list_files()
            assert files == []

    def test_upsert(self):
        r1 = extract_from_source("def v1(): pass", "python", file="same.py")
        r2 = extract_from_source("def v2(): pass", "python", file="same.py")
        with SQLiteStorage(":memory:") as store:
            store.save(r1)
            store.save(r2)
            loaded = store.get_by_file("same.py")
            assert loaded is not None
            assert loaded.functions[0].name == "v2"

    def test_context_manager(self):
        with SQLiteStorage(":memory:") as store:
            r = extract_from_source("def foo(): pass", "python", file="f.py")
            store.save(r)
            assert store.get_by_file("f.py") is not None
