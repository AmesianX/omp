"""Tests for OMP Observer (semantic track) functionality."""

import pytest
from omp import (
    extract_from_source,
    build_observer_prompt,
    reconcile,
    SemanticObservation,
    OBSERVER_SYSTEM_PROMPT,
)


class TestObserver:
    def test_build_prompt(self):
        prompt = build_observer_prompt("User asks for feature X", "Agent implemented Y")
        assert OBSERVER_SYSTEM_PROMPT in prompt
        assert "User asks for feature X" in prompt
        assert "Agent implemented Y" in prompt

    def test_semantic_observation_from_json(self):
        json_str = '''
        {
            "intent_summary": "Add login feature",
            "implicit_constraints": ["Use JWT"],
            "user_preferences": [],
            "unresolved_ambiguity": null,
            "bias_warnings": []
        }
        '''
        obs = SemanticObservation.from_json(json_str)
        assert obs.intent_summary == "Add login feature"
        assert "Use JWT" in obs.implicit_constraints

    def test_reconcile(self):
        sym = extract_from_source("def foo(): pass", "python")
        sem = SemanticObservation(
            intent_summary="Testing",
            implicit_constraints=["Must be fast"],
        )
        mem = reconcile(sym, sem)
        assert mem.symbolic_layer["source"] == "PARSER"
        assert mem.semantic_layer["source"] == "OBSERVER_LLM"
        assert mem.semantic_layer["intent_context"] == "Testing"
        assert "Must be fast" in mem.semantic_layer["implicit_constraints"]
