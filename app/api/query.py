from fastapi import APIRouter
import logging
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
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
    model_config = ConfigDict(str_strip_whitespace=True)

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

@router.post("/search")
def search(request: SearchRequest):
    try:
        searches = {
            "vector": search_chunks,
            "keyword": search_keyword,
            "hybrid": search_hybrid,
            "reranked": search_reranked,
        }
        results = searches[request.retriever](request.query, request.top_k)
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
def ask(request: SearchRequest):
    try:
        if request.retriever == "vector":
            return answer_question(request.query, top_k=request.top_k)
        return answer_question(
            request.query, top_k=request.top_k, retriever=request.retriever,
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
