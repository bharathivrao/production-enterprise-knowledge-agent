from unittest.mock import patch

import pytest

from app.agents.critic import (
    EvidenceReview, FindingReview, InvalidEvidenceReview, check_evidence,
    novel_search_query, safe_findings,
)
from app.agents.goal_analyzer import Goal
from app.agents.synthesizer import Finding, MISSING, SynthesisDraft


GOAL = Goal(
    objective="Find ownership", entities=["platform"],
    deliverables=["platform owner"], constraints=[],
)
DRAFT = SynthesisDraft(findings=[
    Finding(deliverable_index=0, text="Mercury owns the platform.", source_ids=["S1"]),
])


def test_checker_requires_every_deliverable():
    response = {"message": {"content": '{"findings":[],"search_query":null}'}}
    with patch("app.agents.critic.model_client.chat", return_value=response):
        with pytest.raises(InvalidEvidenceReview):
            check_evidence("Who owns the platform?", GOAL, DRAFT, "[S1] Mercury owns it")


def test_checker_sends_evidence_and_parses_verdict():
    response = {"message": {"content": (
        '{"findings":[{"deliverable_index":0,"verdict":"incomplete",'
        '"reason":"owner absent"}],"search_query":"platform owner"}'
    )}, "prompt_eval_count": 21, "eval_count": 13}
    with patch("app.agents.critic.model_client.chat", return_value=response) as chat:
        review, usage = check_evidence(
            "Who owns the platform?", GOAL, DRAFT, "[S1] unrelated text",
        )
    assert review.findings[0].verdict == "incomplete"
    assert usage == {"prompt_tokens": 21, "completion_tokens": 13}
    assert "unrelated text" in chat.call_args.kwargs["messages"][1]["content"]


def test_unsupported_findings_are_masked_and_repeated_search_is_rejected():
    review = EvidenceReview(findings=[
        FindingReview(deliverable_index=0, verdict="contradicted", reason="source disagrees"),
    ], search_query=" Platform   Owner ")
    masked = safe_findings(DRAFT, review)
    assert masked.findings[0].text == MISSING
    assert masked.findings[0].source_ids == []
    assert novel_search_query(review, {"platform owner"}) is None
    assert novel_search_query(review, set()) == "Platform   Owner"
