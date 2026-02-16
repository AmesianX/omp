"""Tests for OMP core extraction and staleness functionality."""

import pytest
from omp import extract_from_source, diff_extractions


class TestExtraction:
    def test_extract_from_source(self):
        result = extract_from_source("def foo(): pass", "python")
        assert result.language == "python"
        assert len(result.functions) == 1
        assert result.functions[0].name == "foo"
        assert result.file_hash

    def test_extract_from_source_bytes(self):
        result = extract_from_source(b"def bar(): pass", "python")
        assert result.language == "python"
        assert len(result.functions) == 1
        assert result.functions[0].name == "bar"

    def test_unsupported_language(self):
        with pytest.raises(ValueError, match="Unsupported language"):
            extract_from_source("x", "unsupported_lang")


class TestStaleness:
    def test_not_stale(self):
        code = "def foo(): pass"
        r1 = extract_from_source(code, "python")
        r2 = extract_from_source(code, "python")
        report = diff_extractions(r1, r2)
        assert not report.is_stale

    def test_stale_different_code(self):
        r1 = extract_from_source("def foo(): pass", "python")
        r2 = extract_from_source("def bar(): pass", "python")
        report = diff_extractions(r1, r2)
        assert report.is_stale
        assert "foo" in report.removed_functions
        assert "bar" in report.added_functions

    def test_added_function(self):
        r1 = extract_from_source("def foo(): pass", "python")
        r2 = extract_from_source("def foo(): pass\ndef bar(): pass", "python")
        report = diff_extractions(r1, r2)
        assert report.is_stale
        assert "bar" in report.added_functions

    def test_removed_function(self):
        r1 = extract_from_source("def foo(): pass\ndef bar(): pass", "python")
        r2 = extract_from_source("def foo(): pass", "python")
        report = diff_extractions(r1, r2)
        assert report.is_stale
        assert "bar" in report.removed_functions

    def test_changed_function(self):
        r1 = extract_from_source("def foo(): pass", "python")
        r2 = extract_from_source("def foo(x: int): pass", "python")
        report = diff_extractions(r1, r2)
        assert report.is_stale
        assert "foo" in report.changed_functions


class TestExtractionResult:
    def test_observation_id_generated(self):
        result = extract_from_source("def foo(): pass", "python")
        assert result.observation_id.startswith("obs_")

    def test_timestamp_generated(self):
        result = extract_from_source("def foo(): pass", "python")
        assert result.timestamp

    def test_to_symbolic_layer(self):
        result = extract_from_source("def foo(): pass", "python")
        layer = result.to_symbolic_layer()
        assert layer["source"] == "PARSER"
        assert layer["veracity"] == "DETERMINISTIC"
        assert "facts" in layer
        assert len(layer["facts"]) == 1
        assert layer["facts"][0]["identifier"] == "foo"

    def test_all_dependencies(self):
        code = """
import os
from pathlib import Path
"""
        result = extract_from_source(code.strip(), "python")
        deps = result.all_dependencies
        assert "os" in deps
        assert "pathlib" in deps
