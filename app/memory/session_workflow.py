"""One bounded conversational turn over freshly retrieved, scoped evidence."""

from time import perf_counter
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.agents.workflow import (
    WorkflowCitation, WorkflowEvent, WorkflowMetadata, run_tool_answer,
)
from app.core.config import get_settings
from app.memory.conversation_memory import (
    append_turn, load_session, visible_source_titles,
)
from app.memory.working_memory import (
    FOLLOWUP_PROMPT_VERSION, WorkingMemory, resolve_followup, select_history,
)
from app.retrieval.scope import PUBLIC_SCOPE, RetrievalScope


class SessionBudgetExceeded(RuntimeError):
    """A conversational turn exceeded its combined resolver/workflow budget."""


class SessionUsage(BaseModel):
    model_calls: int = Field(ge=0)
    tokens: int = Field(ge=0)
    elapsed_ms: float = Field(ge=0)


class SessionAnswerResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    turn_id: UUID
    state: Literal["completed", "clarification"]
    original_question: str
    resolved_question: str | None
    answer: str
    citations: list[WorkflowCitation]
    memory: WorkingMemory
    trace: list[WorkflowEvent]
    usage: SessionUsage
    workflow_metadata: WorkflowMetadata | None
    followup_prompt_version: str


def answer_in_session(
    session_id: UUID, token: str, question: str, *, top_k: int = 3,
    scope: RetrievalScope = PUBLIC_SCOPE,
    subject: str = "legacy",
) -> SessionAnswerResult:
    if not question.strip() or len(question) > 2000:
        raise ValueError("question must contain 1 to 2000 characters")
    if not 1 <= top_k <= 3:
        raise ValueError("top_k must be between 1 and 3")
    started = perf_counter()
    settings = get_settings()
    snapshot = load_session(session_id, token, scope=scope, subject=subject)
    remembered_titles = {
        citation["document"] for turn in snapshot.turns
        for citation in turn.citations
        if isinstance(citation, dict) and citation.get("document")
    }
    visible_titles = visible_source_titles(remembered_titles, scope=scope)
    history = select_history(snapshot.turns, visible_titles=visible_titles)
    resolution, resolver_usage = resolve_followup(question, history)
    resolver_tokens = (
        resolver_usage["prompt_tokens"] + resolver_usage["completion_tokens"]
    )
    resolver_calls = 1 if history else 0
    if resolver_tokens > settings.session_max_tokens:
        raise SessionBudgetExceeded("Session token budget exceeded")

    if resolution.needs_clarification:
        state = "clarification"
        answer = resolution.clarification_question
        resolved_question = None
        citations = []
        trace = []
        metadata = None
        memory = WorkingMemory(
            question=question, resolved_question=question, goal_objective=None,
            plan_step_ids=[], tool_observations=[], cited_sources=[],
            unresolved_questions=[answer],
        )
        model_calls, tokens = resolver_calls, resolver_tokens
    else:
        resolved_question = resolution.standalone_question
        if history and not resolved_question.casefold().startswith(
            "according to the available documents,"
        ):
            grounded = f"According to the available documents, {resolved_question}"
            if len(grounded) <= 2000:
                resolved_question = grounded
        workflow = run_tool_answer(resolved_question, top_k=top_k, scope=scope)
        state, answer, citations = workflow.state, workflow.answer, workflow.citations
        trace, metadata = workflow.trace, workflow.metadata
        memory = WorkingMemory.from_result(question, resolved_question, workflow)
        model_calls = resolver_calls + workflow.usage.model_calls
        tokens = resolver_tokens + workflow.usage.tokens

    elapsed_ms = (perf_counter() - started) * 1000
    if (model_calls > settings.session_max_model_calls
            or tokens > settings.session_max_tokens
            or elapsed_ms > settings.session_max_runtime_seconds * 1000):
        raise SessionBudgetExceeded("Session workflow budget exceeded")
    turn_id = append_turn(
        session_id, token, scope=scope, expected_version=snapshot.version,
        user_question=question, resolved_question=resolved_question or question,
        answer=answer,
        citations=[item.model_dump(exclude_none=True) for item in citations],
        state=state,
        subject=subject,
    )
    return SessionAnswerResult(
        session_id=session_id, turn_id=turn_id, state=state,
        original_question=question, resolved_question=resolved_question,
        answer=answer, citations=citations, memory=memory, trace=trace,
        usage=SessionUsage(
            model_calls=model_calls, tokens=tokens,
            elapsed_ms=(perf_counter() - started) * 1000,
        ),
        workflow_metadata=metadata, followup_prompt_version=FOLLOWUP_PROMPT_VERSION,
    )
