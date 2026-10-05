"""Capability-protected conversation endpoints (pre-authentication prototype)."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response
import httpx
import ollama
from pydantic import BaseModel, ConfigDict, Field
import psycopg
from psycopg_pool import PoolTimeout

from app.agents.workflow import WorkflowBudgetExceeded, WorkflowRunError
from app.guardrails.auth import Actor, audit, get_actor
from app.guardrails.pii import contains_credential, contains_high_risk_pii
from app.memory.conversation_memory import (
    SessionConflict, SessionCreated, SessionNotFound, SessionSnapshot,
    create_session, delete_session, load_session, reset_session,
)
from app.memory.session_workflow import (
    SessionAnswerResult, SessionBudgetExceeded, answer_in_session,
)
from app.memory.working_memory import InvalidFollowup
from app.tools.dispatcher import ToolError
from app.observability import record_workflow_trace


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sessions", tags=["sessions"])


class SessionAskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=3, ge=1, le=3)


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _session_error(error: Exception) -> HTTPException:
    if isinstance(error, SessionNotFound):
        return HTTPException(404, "Session not found.")
    if isinstance(error, SessionConflict):
        return HTTPException(409, "Session changed; retry with fresh history.")
    if isinstance(error, SessionBudgetExceeded):
        return HTTPException(504, "The session answer exceeded its budget.")
    if isinstance(error, InvalidFollowup):
        return HTTPException(502, "The follow-up question failed validation.")
    if isinstance(error, WorkflowRunError):
        cause = error.cause
        if isinstance(cause, (WorkflowBudgetExceeded, httpx.TimeoutException)):
            status = 504
        elif isinstance(cause, (ConnectionError, psycopg.Error, PoolTimeout)):
            status = 503
        elif isinstance(cause, ToolError):
            status = 504 if cause.code in ("timeout", "call_limit") else (
                503 if cause.code in ("dependency_unavailable", "tool_failed") else 502
            )
        elif isinstance(cause, ollama.ResponseError):
            status = 502
        else:
            status = 502
        return HTTPException(status, {
            "message": "The session answer could not be completed.",
            "trace": [event.model_dump(exclude_none=True) for event in error.trace],
        })
    logger.exception("Session request failed unexpectedly")
    return HTTPException(500, "The session request could not be completed.")


@router.post("", response_model=SessionCreated, status_code=201)
def create(response: Response, actor: Actor = Depends(get_actor)):
    _no_store(response)
    audit("session_create", "allow", actor)
    return create_session(scope=actor.scope, subject=actor.subject)


@router.get("/{session_id}", response_model=SessionSnapshot)
def get_history(
    session_id: UUID, response: Response,
    session_token: str = Header(alias="X-Session-Token", min_length=20),
    actor: Actor = Depends(get_actor),
):
    _no_store(response)
    try:
        snapshot = load_session(
            session_id, session_token, scope=actor.scope, subject=actor.subject,
        )
        audit("session_history", "allow", actor)
        return snapshot
    except SessionNotFound as error:
        audit("session_history", "deny", actor)
        raise _session_error(error) from error


@router.post("/{session_id}/ask", response_model=SessionAnswerResult,
             response_model_exclude_none=True)
def ask_in_session(
    session_id: UUID, request: SessionAskRequest, response: Response,
    session_token: str = Header(alias="X-Session-Token", min_length=20),
    actor: Actor = Depends(get_actor),
):
    _no_store(response)
    if contains_credential(request.query) or contains_high_risk_pii(request.query):
        raise HTTPException(422, "Do not submit sensitive values in queries.")
    try:
        result = answer_in_session(
            session_id, session_token, request.query,
            top_k=request.top_k, scope=actor.scope, subject=actor.subject,
        )
        record_workflow_trace(result.trace)
        audit("session_ask", "allow", actor)
        return result
    except (SessionNotFound, SessionConflict, SessionBudgetExceeded,
            InvalidFollowup, WorkflowRunError) as error:
        if isinstance(error, WorkflowRunError):
            record_workflow_trace(error.trace)
        audit("session_ask", "deny", actor)
        raise _session_error(error) from error


@router.post("/{session_id}/reset", status_code=204)
def reset(
    session_id: UUID,
    session_token: str = Header(alias="X-Session-Token", min_length=20),
    actor: Actor = Depends(get_actor),
):
    try:
        reset_session(
            session_id, session_token, scope=actor.scope, subject=actor.subject,
        )
        audit("session_reset", "allow", actor)
    except SessionNotFound as error:
        audit("session_reset", "deny", actor)
        raise _session_error(error) from error
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.delete("/{session_id}", status_code=204)
def delete(
    session_id: UUID,
    session_token: str = Header(alias="X-Session-Token", min_length=20),
    actor: Actor = Depends(get_actor),
):
    try:
        delete_session(
            session_id, session_token, scope=actor.scope, subject=actor.subject,
        )
        audit("session_delete", "allow", actor)
    except SessionNotFound as error:
        audit("session_delete", "deny", actor)
        raise _session_error(error) from error
    return Response(status_code=204, headers={"Cache-Control": "no-store"})
