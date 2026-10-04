"""Execute validated plans with bounded, observable read-only retrieval."""

from dataclasses import replace
from pathlib import Path
import re
from time import perf_counter
from typing import Literal

import tiktoken
from pydantic import BaseModel, ConfigDict, Field

from app.agents.goal_analyzer import GOAL_PROMPT_VERSION, Goal, analyze_goal
from app.agents.planner import PLAN_PROMPT_VERSION, Plan, SearchStep, plan_goal
from app.agents.synthesizer import (
    SYNTHESIS_PROMPT_VERSION, SYNTHESIS_SYSTEM_PROMPT,
    render_synthesis, synthesize_findings,
)
from app.agents.tool_selector import TOOL_SELECTION_PROMPT_VERSION, select_tool
from app.core.config import get_settings
from app.generation.context_builder import build_context
from app.retrieval.reranker import deduplicate_candidates
from app.retrieval.scope import PUBLIC_SCOPE, RetrievalScope
from app.retrieval.vector_search import search_chunks
from app.tools.dispatcher import ToolDispatcher, ToolError


ABSTENTION = "The available documents do not contain enough information."
State = Literal[
    "received", "analyzing", "planning", "searching", "searched",
    "evidence_selected", "selecting_tool", "reading", "read", "tool_failed",
    "synthesizing", "completed", "clarification", "failed",
]


class WorkflowEvent(BaseModel):
    state: State
    elapsed_ms: float = Field(ge=0)
    step_id: str | None = None
    result_count: int | None = None
    tool_name: str | None = None
    tool_status: str | None = None
    argument_summary: dict[str, int] | None = None


class WorkflowUsage(BaseModel):
    model_calls: int
    tokens: int
    elapsed_ms: float


class WorkflowCitation(BaseModel):
    source_id: str
    document: str
    page: int | None
    section: str | None = None


class WorkflowMetadata(BaseModel):
    goal_prompt_version: str
    plan_prompt_version: str
    synthesis_prompt_version: str
    generation_model: str
    embedding_model: str
    retrieval_method: Literal["vector"]
    max_steps: int
    max_model_calls: int
    max_tokens: int
    max_runtime_seconds: int
    tool_selection_prompt_version: str | None = None
    max_tool_calls: int | None = None


class WorkflowResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: Literal["completed", "clarification"]
    answer: str
    citations: list[WorkflowCitation]
    goal: Goal | None
    plan: Plan | None
    trace: list[WorkflowEvent]
    usage: WorkflowUsage
    metadata: WorkflowMetadata


class WorkflowBudgetExceeded(RuntimeError):
    """A configured workflow limit would be exceeded."""


class WorkflowRunError(RuntimeError):
    """A failed workflow with its observable state transitions."""

    def __init__(self, cause: Exception, trace: list[WorkflowEvent]):
        super().__init__(str(cause))
        self.cause = cause
        self.trace = trace


class _Budget:
    def __init__(self, settings, started: float):
        self.settings = settings
        self.started = started
        self.model_calls = 0
        self.tokens = 0

    def check_time(self):
        if perf_counter() - self.started > self.settings.workflow_max_runtime_seconds:
            raise WorkflowBudgetExceeded("workflow runtime budget exceeded")

    def call(self):
        self.check_time()
        if self.model_calls >= self.settings.workflow_max_model_calls:
            raise WorkflowBudgetExceeded("workflow model-call budget exceeded")
        self.model_calls += 1

    def add_tokens(self, count: int):
        self.tokens += count
        if self.tokens > self.settings.workflow_max_tokens:
            raise WorkflowBudgetExceeded("workflow token budget exceeded")
        self.check_time()

    def require_tokens(self, count: int):
        self.check_time()
        if self.tokens + count > self.settings.workflow_max_tokens:
            raise WorkflowBudgetExceeded("workflow token budget exceeded")

    def usage(self) -> WorkflowUsage:
        return WorkflowUsage(
            model_calls=self.model_calls, tokens=self.tokens,
            elapsed_ms=(perf_counter() - self.started) * 1000,
        )


def _estimate_tokens(text: str) -> int:
    return len(tiktoken.get_encoding("cl100k_base").encode(text))


def _merge_step_results(result_sets: list[list[dict]]) -> list[dict]:
    """Interleave steps so the first search cannot crowd out later evidence."""
    interleaved = []
    for rank in range(max((len(results) for results in result_sets), default=0)):
        for results in result_sets:
            if rank < len(results):
                interleaved.append(results[rank])
    return deduplicate_candidates(interleaved)


def _merge_tool_results(result_sets: list[list[dict]]) -> list[dict]:
    """Interleave preview results without needing their full document text."""
    merged = []
    seen = set()
    for rank in range(max((len(results) for results in result_sets), default=0)):
        for results in result_sets:
            if rank < len(results) and results[rank]["chunk_id"] not in seen:
                item = results[rank]
                seen.add(item["chunk_id"])
                merged.append(item)
    return merged


def _named_documents(question: str, candidates: list[dict]) -> set[str]:
    """Resolve explicit names conservatively within already scoped candidates."""
    names = {candidate["document"] for candidate in candidates}
    lowered_question = question.casefold()
    exact = {name for name in names if name.casefold() in lowered_question}

    question_words = set(re.findall(r"[a-z0-9]+", lowered_question))
    matched = set()
    for name in names:
        title_words = [
            word for word in re.findall(r"[a-z0-9]+", Path(name).stem.casefold())
            if not re.fullmatch(r"v\d+", word)
        ]
        if len(title_words) >= 2 and set(title_words) <= question_words:
            matched.add(name)
    selected_names = exact | matched
    if exact or len(selected_names) >= 2:
        return selected_names
    return set()


def _restrict_to_named_documents(question: str, candidates: list[dict]) -> list[dict]:
    """Honor document names supplied by the user when titles resolve."""
    selected_names = _named_documents(question, candidates)
    return ([item for item in candidates if item["document"] in selected_names]
            if selected_names else candidates)


def run_planned_answer(
    question: str, *, top_k: int = 3, scope: RetrievalScope = PUBLIC_SCOPE,
) -> WorkflowResult:
    return _run_answer(question, top_k=top_k, scope=scope, use_tools=False)


def run_tool_answer(
    question: str, *, top_k: int = 3, scope: RetrievalScope = PUBLIC_SCOPE,
) -> WorkflowResult:
    """Use allowlisted search and scoped read tools before synthesis."""
    return _run_answer(question, top_k=top_k, scope=scope, use_tools=True)


def _run_answer(
    question: str, *, top_k: int, scope: RetrievalScope, use_tools: bool,
) -> WorkflowResult:
    if not question.strip() or len(question) > 2000:
        raise ValueError("question must contain 1 to 2000 characters")
    if not 1 <= top_k <= 3:
        raise ValueError("top_k must be between 1 and 3")

    settings = get_settings()
    if use_tools:
        settings = settings.model_copy(update={
            "workflow_max_steps": settings.tool_workflow_max_steps,
            "workflow_max_model_calls": settings.tool_workflow_max_model_calls,
        })
    started = perf_counter()
    budget = _Budget(settings, started)
    trace: list[WorkflowEvent] = []
    metadata = WorkflowMetadata(
        goal_prompt_version=GOAL_PROMPT_VERSION,
        plan_prompt_version=PLAN_PROMPT_VERSION,
        synthesis_prompt_version=SYNTHESIS_PROMPT_VERSION,
        generation_model=settings.generation_model,
        embedding_model=settings.embedding_model,
        retrieval_method="vector",
        max_steps=settings.workflow_max_steps,
        max_model_calls=settings.workflow_max_model_calls,
        max_tokens=settings.workflow_max_tokens,
        max_runtime_seconds=settings.workflow_max_runtime_seconds,
        tool_selection_prompt_version=(
            TOOL_SELECTION_PROMPT_VERSION if use_tools else None
        ),
        max_tool_calls=settings.tool_workflow_max_tool_calls if use_tools else None,
    )

    def transition(state: State, *, step_id=None, result_count=None,
                   tool_name=None, tool_status=None, argument_summary=None):
        trace.append(WorkflowEvent(
            state=state, step_id=step_id, result_count=result_count,
            tool_name=tool_name, tool_status=tool_status,
            argument_summary=argument_summary,
            elapsed_ms=(perf_counter() - started) * 1000,
        ))

    transition("received")
    try:
        transition("analyzing")
        budget.call()
        analysis, usage = analyze_goal(question)
        budget.add_tokens(usage["prompt_tokens"] + usage["completion_tokens"])
        if analysis.needs_clarification:
            transition("clarification")
            return WorkflowResult(
                state="clarification", answer=analysis.clarification_question,
                citations=[], goal=None, plan=None, trace=trace,
                usage=budget.usage(), metadata=metadata,
            )

        transition("planning")
        budget.call()
        plan, usage = plan_goal(
            analysis.goal, question, max_steps=settings.workflow_max_steps,
        )
        budget.add_tokens(usage["prompt_tokens"] + usage["completion_tokens"])

        # Hold the scope's timestamp fixed across all searches in the plan.
        fixed_scope = replace(scope, as_of=scope.normalized_as_of())
        dispatcher = ToolDispatcher(
            fixed_scope, max_calls=settings.tool_workflow_max_tool_calls,
            max_elapsed_seconds=settings.tool_max_elapsed_seconds,
        ) if use_tools else None
        result_sets = []
        for step in plan.steps:
            if not isinstance(step, SearchStep):
                continue
            transition("searching", step_id=step.step_id,
                       tool_name="search_documents" if use_tools else None,
                       argument_summary={"query_chars": len(step.query), "top_k": top_k}
                       if use_tools else None)
            budget.require_tokens(_estimate_tokens(step.query))
            budget.call()  # vector retrieval makes one embedding-model call
            if dispatcher:
                try:
                    observation = dispatcher.execute(
                        "search_documents", {"query": step.query, "top_k": top_k},
                    )
                except ToolError as error:
                    transition("tool_failed", step_id=step.step_id,
                               tool_name="search_documents", tool_status=error.code)
                    raise
                results = observation.result
            else:
                results = search_chunks(step.query, top_k=top_k, scope=fixed_scope)
            budget.add_tokens(_estimate_tokens(step.query))
            result_sets.append(results)
            transition("searched", step_id=step.step_id, result_count=len(results),
                       tool_name="search_documents" if use_tools else None,
                       tool_status="ok" if use_tools else None)

        candidates = _restrict_to_named_documents(
            question, (_merge_tool_results(result_sets) if use_tools
                       else _merge_step_results(result_sets)),
        )
        transition("evidence_selected", result_count=len(candidates))
        if dispatcher and candidates:
            if len(plan.steps) + 1 > settings.workflow_max_steps:
                raise WorkflowBudgetExceeded("workflow step budget exceeded")
            transition("selecting_tool")
            budget.call()
            required_documents = _named_documents(question, candidates)
            if len(required_documents) > 3:
                required_documents = set()
            choice, selection_usage = select_tool(
                question, analysis.goal, candidates,
                required_documents=required_documents,
            )
            budget.add_tokens(
                selection_usage["prompt_tokens"] + selection_usage["completion_tokens"]
            )
            transition("reading", step_id="read_1", tool_name=choice.tool,
                       argument_summary={"chunk_count": len(choice.chunk_ids)})
            try:
                observation = dispatcher.execute(
                    choice.tool, {"chunk_ids": choice.chunk_ids},
                )
            except ToolError as error:
                transition("tool_failed", step_id="read_1", tool_name=choice.tool,
                           tool_status=error.code)
                raise
            candidates = observation.result
            transition("read", step_id="read_1", tool_name=choice.tool,
                       tool_status="ok", result_count=observation.count)
        transition("synthesizing", step_id=plan.steps[-1].step_id)
        if candidates:
            evidence = build_context(candidates)
            estimated_prompt = _estimate_tokens(
                SYNTHESIS_SYSTEM_PROMPT + question + analysis.goal.model_dump_json()
                + evidence["context"]
            )
            budget.require_tokens(estimated_prompt + 128)
            max_output_tokens = min(
                768, settings.workflow_max_tokens - budget.tokens - estimated_prompt,
            )
            budget.call()
            draft, usage = synthesize_findings(
                question, analysis.goal, evidence["context"],
                max_output_tokens=max_output_tokens,
            )
            budget.add_tokens(
                usage["prompt_tokens"] + usage["completion_tokens"]
            )
            answer, citations = render_synthesis(
                analysis.goal, draft, evidence["sources"],
            )
        else:
            answer, citations = ABSTENTION, []

        budget.check_time()
        transition("completed")
        return WorkflowResult(
            state="completed", answer=answer, citations=citations,
            goal=analysis.goal, plan=plan, trace=trace, usage=budget.usage(),
            metadata=metadata,
        )
    except Exception as error:
        transition("failed")
        raise WorkflowRunError(error, trace) from error


if __name__ == "__main__":
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description="Run a bounded planned answer.")
    parser.add_argument("question")
    parser.add_argument("--top-k", type=int, default=3, choices=(1, 2, 3))
    parser.add_argument("--tools", action="store_true", help="Use Stage 5 read-only tools")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    try:
        runner = run_tool_answer if arguments.tools else run_planned_answer
        result = runner(arguments.question, top_k=arguments.top_k)
    except WorkflowRunError as error:
        print(json.dumps({
            "error_type": type(error.cause).__name__,
            "trace": [event.model_dump(exclude_none=True) for event in error.trace],
        }), file=sys.stderr)
        raise SystemExit(1) from error
    serialized = result.model_dump_json(indent=2, exclude_none=True) + "\n"
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(serialized, encoding="utf-8")
        print(f"Report saved to {arguments.output}")
    else:
        print(serialized)
