import pytest

from app.agents.goal_analyzer import Goal
from app.agents.synthesizer import (
    Finding, InvalidSynthesis, SynthesisDraft, render_synthesis,
)


GOAL = Goal(
    objective="Compare response and recovery validation",
    entities=["payments"],
    deliverables=["Who responds", "How recovery is validated"],
    constraints=[],
)
SOURCES = {
    "S1": {"document": "incident.md", "page": None, "section": "Response"},
    "S2": {"document": "incident.md", "page": None, "section": "Recovery"},
}


def test_synthesis_renders_a_supported_finding_for_each_deliverable():
    draft = SynthesisDraft(findings=[
        Finding(deliverable_index=0, text="The primary on-call responds.", source_ids=["S1"]),
        Finding(deliverable_index=1, text="Validate settlement totals.", source_ids=["S2"]),
    ])
    answer, citations = render_synthesis(GOAL, draft, SOURCES)
    assert "Who responds: The primary on-call responds. [S1]" in answer
    assert "How recovery is validated: Validate settlement totals. [S2]" in answer
    assert {citation["source_id"] for citation in citations} == {"S1", "S2"}


def test_synthesis_rejects_missing_deliverable_and_unknown_citation():
    with pytest.raises(InvalidSynthesis, match="every deliverable"):
        render_synthesis(GOAL, SynthesisDraft(findings=[
            Finding(deliverable_index=0, text="The primary on-call responds.", source_ids=["S1"]),
        ]), SOURCES)
    with pytest.raises(InvalidSynthesis, match="unknown source"):
        render_synthesis(GOAL, SynthesisDraft(findings=[
            Finding(deliverable_index=0, text="The primary on-call responds.", source_ids=["S99"]),
            Finding(deliverable_index=1, text="Validate settlement totals.", source_ids=["S2"]),
        ]), SOURCES)


def test_missing_evidence_must_be_explicit_and_uncited():
    with pytest.raises(InvalidSynthesis, match="Uncited"):
        render_synthesis(GOAL, SynthesisDraft(findings=[
            Finding(deliverable_index=0, text="The primary on-call responds.", source_ids=[]),
            Finding(deliverable_index=1, text="Validate settlement totals.", source_ids=["S2"]),
        ]), SOURCES)
