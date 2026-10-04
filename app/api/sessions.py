"""Capability-protected conversation endpoints (pre-authentication prototype)."""

import logging
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Response
import httpx
import ollama
from pydantic import BaseModel, ConfigDict, Field
import psycopg
from psycopg_pool import PoolTimeout

from app.agents.workflow import WorkflowBudgetExceeded, WorkflowRunError
from app.memory.conversation_memory import (
    SessionConflict, SessionCreated, SessionNotFound, SessionSnapshot,
    create_session, delete_session, load_session, reset_session,
)
from app.memory.session_workflow import (
    SessionAnswerResult, SessionBudgetExceeded, answer_in_session,
)
from app.memory.working_memory import InvalidFollowup
from app.retrieval.scope import PUBLIC_SCOPE
from app.tools.dispatcher import ToolError


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
def create(response: Response):
    _no_store(response)
    return create_session(scope=PUBLIC_SCOPE)


@router.get("/{session_id}", response_model=SessionSnapshot)
def get_history(
    session_id: UUID, response: Response,
    session_token: str = Header(alias="X-Session-Token", min_length=20),
):
    _no_store(response)
    try:
        return load_session(session_id, session_token, scope=PUBLIC_SCOPE)
    except SessionNotFound as error:
        raise _session_error(error) from error


@router.post("/{session_id}/ask", response_model=SessionAnswerResult,
             response_model_exclude_none=True)
def ask_in_session(
    session_id: UUID, request: SessionAskRequest, response: Response,
    session_token: str = Header(alias="X-Session-Token", min_length=20),
):
    _no_store(response)
    try:
        return answer_in_session(
            session_id, session_token, request.query,
            top_k=request.top_k, scope=PUBLIC_SCOPE,
        )
    except (SessionNotFound, SessionConflict, SessionBudgetExceeded,
            InvalidFollowup, WorkflowRunError) as error:
        raise _session_error(error) from error


@router.post("/{session_id}/reset", status_code=204)
def reset(
    session_id: UUID,
    session_token: str = Header(alias="X-Session-Token", min_length=20),
):
    try:
        reset_session(session_id, session_token, scope=PUBLIC_SCOPE)
    except SessionNotFound as error:
        raise _session_error(error) from error
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.delete("/{session_id}", status_code=204)
def delete(
    session_id: UUID,
    session_token: str = Header(alias="X-Session-Token", min_length=20),
):
    try:
        delete_session(session_id, session_token, scope=PUBLIC_SCOPE)
    except SessionNotFound as error:
        raise _session_error(error) from error
    return Response(status_code=204, headers={"Cache-Control": "no-store"})
