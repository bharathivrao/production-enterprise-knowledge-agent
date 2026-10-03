from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_readiness_reports_dependencies():
    with (
        patch("app.api.health.database_ready", return_value=True),
        patch("app.api.health.model_ready", return_value=True),
    ):
        response = client.get("/health/readiness")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_readiness_returns_503_for_dependency_outage():
    with (
        patch("app.api.health.database_ready", side_effect=TimeoutError),
        patch("app.api.health.model_ready", return_value=True),
    ):
        response = client.get("/health/readiness")
    assert response.status_code == 503
    assert response.json()["dependencies"]["database"] == "unavailable"
