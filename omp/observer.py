"""
OMP Observer - Semantic Track integration for the Dual-Track Memory.

The Observer captures the "Why" (intent, context, preferences) while the
Parser captures the "What" (signatures, types, dependencies).  This module
provides the prompt template, output schema, and reconciliation logic.

The Observer does NOT call an LLM directly - it provides the interface
so any LLM (Claude, GPT, Llama, etc.) can be plugged in.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

from omp.models import ExtractionResult


# ---------------------------------------------------------------------------
# Observer output schema
# ---------------------------------------------------------------------------

@dataclass
class SemanticObservation:
    """Output of the Observer LLM - the Semantic Track."""

    intent_summary: str
    implicit_constraints: list[str] = field(default_factory=list)
    user_preferences: list[str] = field(default_factory=list)
    unresolved_ambiguity: Optional[str] = None
    bias_warnings: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SemanticObservation":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_json(cls, text: str) -> "SemanticObservation":
        """Parse the JSON output from an Observer LLM."""
        d = json.loads(text)
        return cls.from_dict(d)


# ---------------------------------------------------------------------------
# The Observer Prompt (from fixme.md spec)
# ---------------------------------------------------------------------------

OBSERVER_SYSTEM_PROMPT = """System Role: Memory Architect (Observer Mode)

Objective:
Analyze the recent interaction between the User and the Coding Agent.
Your task is to extract the Semantic Intent and Contextual Nuance ONLY.

Constraints:
1. DO NOT record function signatures, variable types, or file structures.
   A deterministic parser is handling these "Hard Facts."
2. FOCUS ON the "Why" and the "How":
   - Why did the user ask for this change?
   - What architectural patterns were preferred?
   - What was the user frustrated by?
3. IDENTIFY implicit constraints
   (e.g., "The user seems to prefer functional patterns over OOP").
4. FLAG any potential bias warnings
   (e.g., "User expressed frustration with library X - may bias future suggestions").

Output Format (strict JSON, no prose):
{
  "intent_summary": "Short description of the goal",
  "implicit_constraints": ["List of non-obvious rules mentioned"],
  "user_preferences": ["Patterns or styles the user favored"],
  "unresolved_ambiguity": "What was left unclear for the next turn?",
  "bias_warnings": ["Any detected biases or emotional signals"]
}"""


def build_observer_prompt(user_message: str, agent_response: str) -> str:
    """Build the full Observer prompt with injected context.

    Returns a prompt string ready to be sent to any LLM.
    The LLM should return JSON matching the SemanticObservation schema.
    """
    return f"""{OBSERVER_SYSTEM_PROMPT}

Input Data:
- User Message: {user_message}
- Agent Action: {agent_response}

Respond with the JSON object only. No explanation, no markdown fencing."""


# ---------------------------------------------------------------------------
# Dual-Track Reconciliation
# ---------------------------------------------------------------------------

@dataclass
class DualTrackMemory:
    """A complete Dual-Track Memory entry combining Symbolic + Semantic."""

    observation_id: str
    timestamp: str
    symbolic_layer: dict
    semantic_layer: dict
    linkage: dict

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


def reconcile(
    symbolic: ExtractionResult,
    semantic: SemanticObservation,
    original_snippet_ref: Optional[str] = None,
) -> DualTrackMemory:
    """Combine a Symbolic extraction and a Semantic observation into
    the full Dual-Track Memory schema defined in the OMP spec.

    Args:
        symbolic: The parser output (deterministic facts).
        semantic: The observer output (probabilistic intent).
        original_snippet_ref: Optional reference ID for the raw context store.

    Returns:
        A DualTrackMemory entry ready for storage.
    """
    # Build the active_pointer from the first function or the file itself
    pointers = []
    for fn in symbolic.functions:
        pointers.append(fn.active_pointer)
    for cls in symbolic.classes:
        for m in cls.methods:
            pointers.append(m.active_pointer)

    primary_pointer = pointers[0] if pointers else f"{symbolic.file}#L1"

    return DualTrackMemory(
        observation_id=symbolic.observation_id,
        timestamp=symbolic.timestamp,
        symbolic_layer=symbolic.to_symbolic_layer(),
        semantic_layer={
            "source": "OBSERVER_LLM",
            "veracity": "PROBABILISTIC",
            "intent_context": semantic.intent_summary,
            "implicit_constraints": semantic.implicit_constraints,
            "user_preferences": semantic.user_preferences,
            "bias_warnings": semantic.bias_warnings,
            "unresolved_ambiguity": semantic.unresolved_ambiguity,
        },
        linkage={
            "active_pointer": primary_pointer,
            "original_snippet_ref": original_snippet_ref,
        },
    )
