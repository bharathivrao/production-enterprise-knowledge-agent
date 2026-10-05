import logging
from contextlib import asynccontextmanager
from threading import BoundedSemaphore, Lock
from time import perf_counter
from uuid import UUID, uuid4

import ollama
import psycopg
from psycopg_pool import PoolTimeout
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST

from app.api import health, ingest, query, sessions
from app.core.config import get_settings
from app.core.model_client import model_client
from app.db.database import close_database_pool, start_database_pool
from app.guardrails.auth import Actor, get_actor
from app.observability import (
    REQUESTS, REQUEST_DURATION, configure_logging, metrics_payload, request_id_var,
)
from app.retrieval.reranker import close_reranker


logger = logging.getLogger(__name__)
configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    model_client.start()
    try:
        start_database_pool()
    except (psycopg.Error, TimeoutError):
        logger.exception("Database pool was unavailable during startup")
        close_database_pool()
    yield
    close_database_pool()
    close_reranker()
    model_client.close()


app = FastAPI(title="Production Enterprise Knowledge Agent", lifespan=lifespan)
_admission_lock = Lock()
_admission_limit = None
_admission_semaphore = None


def _request_semaphore():
    global _admission_limit, _admission_semaphore
    limit = get_settings().max_concurrent_requests
    with _admission_lock:
        if _admission_limit != limit or _admission_semaphore is None:
            _admission_limit = limit
            _admission_semaphore = BoundedSemaphore(limit)
        return _admission_semaphore


@app.middleware("http")
async def bound_concurrent_requests(request: Request, call_next):
    if request.url.path in ("/", "/health", "/health/liveness"):
        return await call_next(request)
    semaphore = _request_semaphore()
    if not semaphore.acquire(blocking=False):
        return JSONResponse(
            status_code=429, headers={"Retry-After": "1"},
            content={"detail": "The service is busy. Try again later."},
        )
    try:
        return await call_next(request)
    finally:
        semaphore.release()


@app.middleware("http")
async def reject_known_oversized_uploads(request: Request, call_next):
    if request.url.path == "/documents" or request.url.path.startswith("/documents/"):
        content_length = request.headers.get("content-length")
        allowance = get_settings().max_upload_bytes + 64 * 1024
        if content_length:
            try:
                oversized = int(content_length) > allowance
            except ValueError:
                return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length header."})
            if oversized:
                return JSONResponse(status_code=413, content={"detail": "Request exceeds the upload limit."})
    return await call_next(request)


@app.middleware("http")
async def observe_requests(request: Request, call_next):
    supplied = request.headers.get("x-request-id", "")
    try:
        request_id = str(UUID(supplied))
    except (ValueError, TypeError, AttributeError):
        request_id = str(uuid4())
    token = request_id_var.set(request_id)
    started = perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        duration = perf_counter() - started
        route = getattr(request.scope.get("route"), "path", "unmatched")
        REQUESTS.labels(request.method, route, str(status_code)).inc()
        REQUEST_DURATION.labels(request.method, route).observe(duration)
        logger.info(
            "http_request_complete",
            extra={
                "request_method": request.method,
                "request_path": route,
                "status_code": status_code,
                "duration_ms": round(duration * 1000, 2),
            },
        )
        request_id_var.reset(token)


@app.exception_handler(ollama.ResponseError)
async def handle_model_response_error(request: Request, error: ollama.ResponseError):
    logger.error("Model service returned an error: status=%s", error.status_code)
    return JSONResponse(status_code=502, content={"detail": "The model service could not complete the request."})


@app.exception_handler(psycopg.OperationalError)
async def handle_database_error(request: Request, error: psycopg.OperationalError):
    logger.exception("Database operation failed")
    return JSONResponse(status_code=503, content={"detail": "The database is unavailable. Try again later."})


@app.exception_handler(PoolTimeout)
async def handle_database_pool_timeout(request: Request, error: PoolTimeout):
    logger.exception("Database pool timed out")
    return JSONResponse(status_code=503, content={"detail": "The database is unavailable. Try again later."})


app.include_router(health.router)
app.include_router(query.router)
app.include_router(ingest.router)
app.include_router(sessions.router)


@app.get("/")
async def root():
    return {"message": "Welcome to Enterprise Knowledge Agent"}


@app.get("/metrics", include_in_schema=False)
def metrics(_: Actor = Depends(get_actor)):
    return Response(metrics_payload(), media_type=CONTENT_TYPE_LATEST)
