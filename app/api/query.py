from fastapi import APIRouter, Depends
import logging
import ollama
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from app.agents.goal_analyzer import InvalidGoalAnalysis
from app.guardrails.auth import Actor, audit, get_actor
from app.guardrails.pii import contains_credential, contains_high_risk_pii
from app.agents.planner import InvalidPlan
from app.agents.synthesizer import InvalidSynthesis
from app.agents.tool_selector import InvalidToolChoice
from app.agents.workflow import (
    WorkflowBudgetExceeded, WorkflowResult, WorkflowRunError,
    run_planned_answer, run_tool_answer,
)
from app.tools.dispatcher import ToolError
from app.generation.pipeline import answer_question
import httpx
from fastapi import HTTPException
from app.generation.citations import CitationValidationError
import psycopg
from psycopg_pool import PoolTimeout

from app.retrieval.vector_search import search_chunks
from app.retrieval.bm25 import search_keyword
from app.retrieval.hybrid import search_hybrid
from app.retrieval.reranker import RerankerUnavailableError, search_reranked
logger = logging.getLogger(__name__)

router = APIRouter(tags=["retrieval"])

class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    retriever: Literal["vector", "keyword", "hybrid", "reranked"] = "vector"

class CitationResponse(BaseModel):
    source_id: str
    document: str
    page: int | None
    section: str | None = None

class AnswerResponse(BaseModel):
    answer: str = Field(min_length=1)
    citations: list[CitationResponse]


class PlannedAskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=3, ge=1, le=3)

@router.post("/search")
def search(request: SearchRequest, actor: Actor = Depends(get_actor)):
    if contains_credential(request.query) or contains_high_risk_pii(request.query):
        raise HTTPException(422, "Do not submit sensitive values in queries.")
    audit("search", "allow", actor)
    try:
        searches = {
            "vector": search_chunks,
            "keyword": search_keyword,
            "hybrid": search_hybrid,
            "reranked": search_reranked,
        }
        results = searches[request.retriever](
            request.query, request.top_k, scope=actor.scope,
        )
        return {"results": results}
    except ConnectionError as error:
        logger.exception("Model service connection failed")

        raise HTTPException(
            status_code=503,
            detail="The model service is unavailable. Try again later.",
        ) from error
        
    except httpx.TimeoutException as error:
        logger.exception("Model service request timed out")

        raise HTTPException(
            status_code=504,
            detail="The model service timed out. Try again later.",
        ) from error
    except (psycopg.OperationalError, psycopg.errors.QueryCanceled, PoolTimeout) as error:
        logger.exception("Database request failed")
        raise HTTPException(503, "The database is unavailable. Try again later.") from error
    except RerankerUnavailableError as error:
        logger.exception("Reranker failed")
        raise HTTPException(503, "The reranker is unavailable. Try again later.") from error

    

@router.post("/ask", response_model=AnswerResponse, response_model_exclude_none=True)
def ask(request: SearchRequest, actor: Actor = Depends(get_actor)):
    if contains_credential(request.query) or contains_high_risk_pii(request.query):
        raise HTTPException(422, "Do not submit sensitive values in queries.")
    audit("ask", "allow", actor)
    try:
        if request.retriever == "vector":
            return answer_question(request.query, top_k=request.top_k, scope=actor.scope)
        return answer_question(
            request.query, top_k=request.top_k, retriever=request.retriever,
            scope=actor.scope,
        )
    except CitationValidationError as error:
        logger.exception("Generated answer failed citation validation")

        raise HTTPException(
            status_code=502,
            detail="The generated answer failed citation validation.",
        ) from error

    except ConnectionError as error:
        logger.exception("Model service connection failed")

        raise HTTPException(
            status_code=503,
            detail="The model service is unavailable. Try again later.",
        ) from error

    except httpx.TimeoutException as error:
        logger.exception("Model service request timed out")

        raise HTTPException(
            status_code=504,
            detail="The model service timed out. Try again later.",
        ) from error
    except (psycopg.OperationalError, psycopg.errors.QueryCanceled, PoolTimeout) as error:
        logger.exception("Database request failed")
        raise HTTPException(503, "The database is unavailable. Try again later.") from error
    except RerankerUnavailableError as error:
        logger.exception("Reranker failed")
        raise HTTPException(503, "The reranker is unavailable. Try again later.") from error


@router.post("/ask/planned", response_model=WorkflowResult, response_model_exclude_none=True)
def ask_planned(request: PlannedAskRequest, actor: Actor = Depends(get_actor)):
    return _answer_workflow(request, run_planned_answer, actor)


@router.post("/ask/tools", response_model=WorkflowResult, response_model_exclude_none=True)
def ask_tools(request: PlannedAskRequest, actor: Actor = Depends(get_actor)):
    return _answer_workflow(request, run_tool_answer, actor)


def _answer_workflow(request: PlannedAskRequest, runner, actor: Actor):
    if contains_credential(request.query) or contains_high_risk_pii(request.query):
        raise HTTPException(422, "Do not submit sensitive values in queries.")
    audit("ask_workflow", "allow", actor)
    try:
        return runner(request.query, top_k=request.top_k, scope=actor.scope)
    except WorkflowRunError as error:
        cause = error.cause
        if isinstance(cause, WorkflowBudgetExceeded):
            status_code, message = 504, "The planned answer exceeded its budget."
        elif isinstance(cause, ToolError):
            status_code = 504 if cause.code in ("timeout", "call_limit") else (
                503 if cause.code in ("dependency_unavailable", "tool_failed") else 502
            )
            message = "The tool request could not be completed."
        elif isinstance(cause, (InvalidGoalAnalysis, InvalidPlan, InvalidSynthesis,
                                InvalidToolChoice, CitationValidationError)):
            status_code, message = 502, "The planned answer failed validation."
        elif isinstance(cause, (ConnectionError, RerankerUnavailableError)):
            status_code, message = 503, "A required model service is unavailable."
        elif isinstance(cause, httpx.TimeoutException):
            status_code, message = 504, "A model request timed out."
        elif isinstance(cause, (psycopg.Error, PoolTimeout)):
            status_code, message = 503, "The database is unavailable."
        elif isinstance(cause, ollama.ResponseError):
            status_code, message = 502, "The model service could not complete the request."
        else:
            logger.exception("Planned answer failed unexpectedly")
            status_code, message = 500, "The planned answer could not be completed."
        raise HTTPException(
            status_code=status_code,
            detail={
                "message": message,
                "trace": [event.model_dump(exclude_none=True) for event in error.trace],
            },
        ) from error
