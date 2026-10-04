from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from app.memory.conversation_memory import SessionCreated, SessionNotFound, SessionSnapshot


client = TestClient(app)
SESSION_ID = uuid4()
TOKEN = "a" * 43
NOW = datetime.now(timezone.utc)


def test_create_session_returns_one_time_token_without_caching():
    created = SessionCreated(
        session_id=SESSION_ID, session_token=TOKEN,
        expires_at=NOW + timedelta(hours=24),
    )
    with patch("app.api.sessions.create_session", return_value=created) as create:
        response = client.post("/sessions")
    assert response.status_code == 201
    assert response.json()["session_token"] == TOKEN
    assert response.headers["cache-control"] == "no-store"
    assert create.call_args.kwargs["scope"].principals == (
        "public", "user:test-user",
    )
    assert create.call_args.kwargs["subject"] == "test-user"


def test_history_requires_capability_and_never_allows_caller_scope():
    response = client.get(f"/sessions/{SESSION_ID}")
    assert response.status_code == 422
    snapshot = SessionSnapshot(
        session_id=SESSION_ID, version=0, created_at=NOW,
        expires_at=NOW + timedelta(hours=24), turns=[],
    )
    with patch("app.api.sessions.load_session", return_value=snapshot) as load:
        response = client.get(
            f"/sessions/{SESSION_ID}", headers={"X-Session-Token": TOKEN},
        )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    load.assert_called_once()
    assert "session_token" not in response.json()


def test_invalid_session_token_has_same_not_found_result():
    with patch("app.api.sessions.load_session", side_effect=SessionNotFound()):
        response = client.get(
            f"/sessions/{SESSION_ID}", headers={"X-Session-Token": TOKEN},
        )
    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found."


def test_session_ask_rejects_caller_scope_and_missing_token():
    response = client.post(
        f"/sessions/{SESSION_ID}/ask",
        json={"query": "Who owns it?", "tenant_id": "other"},
        headers={"X-Session-Token": TOKEN},
    )
    assert response.status_code == 422
    response = client.post(
        f"/sessions/{SESSION_ID}/ask", json={"query": "Who owns it?"},
    )
    assert response.status_code == 422


def test_reset_and_delete_are_capability_protected():
    with (
        patch("app.api.sessions.reset_session") as reset,
        patch("app.api.sessions.delete_session") as delete,
    ):
        reset_response = client.post(
            f"/sessions/{SESSION_ID}/reset",
            headers={"X-Session-Token": TOKEN},
        )
        delete_response = client.delete(
            f"/sessions/{SESSION_ID}",
            headers={"X-Session-Token": TOKEN},
        )
    assert reset_response.status_code == 204
    assert delete_response.status_code == 204
    reset.assert_called_once()
    delete.assert_called_once()
