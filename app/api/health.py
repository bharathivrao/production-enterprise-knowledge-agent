import httpx
import psycopg
from psycopg_pool import PoolTimeout
from fastapi import APIRouter, Response, status

from app.core.model_client import model_ready
from app.db.database import database_ready


router = APIRouter(prefix="/health", tags=["system_health"])


@router.get("")
def health_check():
    """Shallow process health; dependency checks belong to readiness."""
    return {"status": "ok", "version": "0.1.0"}


@router.get("/liveness")
def liveness_check():
    return {"status": "live"}


@router.get("/readiness")
def readiness_check(response: Response):
    dependencies = {"database": "unavailable", "model_service": "unavailable"}
    try:
        if database_ready():
            dependencies["database"] = "ready"
    except (psycopg.Error, PoolTimeout, TimeoutError):
        pass
    try:
        if model_ready():
            dependencies["model_service"] = "ready"
    except (ConnectionError, httpx.HTTPError):
        pass
    ready = all(value == "ready" for value in dependencies.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if ready else "not_ready", "dependencies": dependencies}
