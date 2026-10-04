from datetime import datetime, timedelta, timezone
from threading import BoundedSemaphore
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
import jwt
import pytest

from app.core.config import get_settings
from app.guardrails.auth import Actor, verify_access_token
from app.guardrails.policies import request_limiter
from app.main import app


PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC = PRIVATE.public_key()
SETTINGS = get_settings().model_copy(update={
    "auth_issuer": "https://identity.example.test/",
    "auth_audience": "enterprise-knowledge-api",
    "auth_jwks_url": "https://identity.example.test/jwks",
})


def token(**overrides):
    now = datetime.now(timezone.utc)
    payload = {
        "iss": SETTINGS.auth_issuer, "aud": SETTINGS.auth_audience,
        "sub": "alice", "tenant_id": "tenant-a", "groups": ["team-a"],
        "roles": ["document:write"], "iat": now,
        "exp": now + timedelta(minutes=10),
    }
    payload.update(overrides)
    return jwt.encode(
        payload, PRIVATE, algorithm="RS256", headers={"typ": "at+jwt", "kid": "test"},
    )


@pytest.fixture
def configured_auth():
    request_limiter.clear()
    client = SimpleNamespace(get_signing_key_from_jwt=lambda _: SimpleNamespace(key=PUBLIC))
    with (patch("app.guardrails.auth.get_settings", return_value=SETTINGS),
          patch("app.guardrails.auth._jwks_client", return_value=client)):
        yield
    request_limiter.clear()


def test_valid_signature_derives_tenant_and_principals(configured_auth):
    actor = verify_access_token(token())
    assert actor == Actor(
        subject="alice", tenant_id="tenant-a", groups=("team-a",),
        roles=("document:write",),
    )
    assert actor.scope.principals == ("public", "user:alice", "team-a")


@pytest.mark.parametrize("changes", [
    {"aud": "wrong-api"},
    {"iss": "https://other.example.test/"},
    {"exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
    {"tenant_id": "bad tenant"},
    {"groups": "team-a"},
    {"groups": ["user:bob"]},
])
def test_invalid_claims_fail_closed(configured_auth, changes):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as captured:
        verify_access_token(token(**changes))
    assert captured.value.status_code == 401


def test_tampered_signature_and_id_token_are_rejected(configured_auth):
    from fastapi import HTTPException

    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    payload = jwt.decode(token(), options={"verify_signature": False})
    forged = jwt.encode(
        payload, other, algorithm="RS256", headers={"typ": "at+jwt", "kid": "test"},
    )
    id_token = jwt.encode(payload, PRIVATE, algorithm="RS256", headers={"typ": "JWT"})
    for value in (forged, id_token):
        with pytest.raises(HTTPException) as captured:
            verify_access_token(value)
        assert captured.value.status_code == 401


@pytest.mark.real_auth
def test_api_requires_bearer_and_rejects_request_supplied_scope(configured_auth):
    client = TestClient(app)
    assert client.post("/search", json={"query": "policy"}).status_code == 401
    with patch("app.api.query.search_chunks", return_value=[]) as search:
        response = client.post(
            "/search", headers={"Authorization": f"Bearer {token()}"},
            json={"query": "policy"},
        )
    assert response.status_code == 200
    assert search.call_args.kwargs["scope"].tenant_id == "tenant-a"
    assert "team-a" in search.call_args.kwargs["scope"].principals
    response = client.post(
        "/search", headers={"Authorization": f"Bearer {token()}"},
        json={"query": "policy", "tenant_id": "other"},
    )
    assert response.status_code == 422


@pytest.mark.real_auth
def test_document_write_requires_role(configured_auth):
    reader = token(roles=[])
    response = TestClient(app).post(
        "/documents", headers={"Authorization": f"Bearer {reader}"},
        files={"file": ("policy.md", b"Public policy", "text/markdown")},
    )
    assert response.status_code == 403


@pytest.mark.real_auth
def test_document_writer_cannot_manage_visible_documents(configured_auth):
    response = TestClient(app).delete(
        "/documents/11111111-1111-1111-1111-111111111111",
        headers={"Authorization": f"Bearer {token()}"},
    )
    assert response.status_code == 403


@pytest.mark.real_auth
def test_per_identity_rate_limit(configured_auth):
    low_limit = SETTINGS.model_copy(update={"rate_limit_requests_per_minute": 1})
    with (patch("app.guardrails.auth.get_settings", return_value=low_limit),
          patch("app.api.query.search_chunks", return_value=[])):
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {token()}"}
        assert client.post("/search", headers=headers, json={"query": "policy"}).status_code == 200
        response = client.post("/search", headers=headers, json={"query": "policy"})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"


@pytest.mark.real_auth
def test_global_admission_limit_rejects_before_work():
    semaphore = BoundedSemaphore(1)
    assert semaphore.acquire(blocking=False)
    try:
        with patch("app.main._request_semaphore", return_value=semaphore):
            response = TestClient(app).post("/search", json={"query": "policy"})
        assert response.status_code == 429
    finally:
        semaphore.release()
