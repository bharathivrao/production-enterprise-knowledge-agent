from app.evaluation.generation import AnswerGrade, ClaimAssessment
from app.generation.generator import ANSWER_PROMPT_VERSION, ANSWER_SYSTEM_PROMPT


def test_answer_prompt_requires_direct_citations_and_clarification():
    assert ANSWER_PROMPT_VERSION == "3.1.0"
    assert "directly supports the factual claim" in ANSWER_SYSTEM_PROMPT
    assert "ask one concise clarifying question" in ANSWER_SYSTEM_PROMPT


def test_claim_citation_support_is_claim_level_ratio():
    grade = AnswerGrade(
        factual_correctness=2, completeness=4, faithfulness=2, answer_relevance=3,
        claims=[
            ClaimAssessment(claim="supported", cited_source_ids=["S1"], supported=True),
            ClaimAssessment(claim="invented", cited_source_ids=["S1"], supported=False),
        ],
        rationale="mixed",
    )
    assert grade.claim_citation_support == 0.5


def test_claim_citation_support_is_complete_for_correct_abstention():
    grade = AnswerGrade(
        factual_correctness=4, completeness=4, faithfulness=4, answer_relevance=4,
        claims=[], rationale="correct abstention",
    )
    assert grade.claim_citation_support == 1.0
