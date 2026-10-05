"""Provider-neutral, fail-closed JWT access-token authentication."""

from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
import logging
import re

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt

from app.core.config import get_settings
from app.guardrails.policies import request_limiter
from app.retrieval.scope import RetrievalScope


logger = logging.getLogger(__name__)
_bearer = HTTPBearer(auto_error=False)
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$")


@dataclass(frozen=True)
class Actor:
    subject: str
    tenant_id: str
    groups: tuple[str, ...]
    roles: tuple[str, ...]

    @property
    def scope(self) -> RetrievalScope:
        return RetrievalScope(
            tenant_id=self.tenant_id,
            principals=tuple(dict.fromkeys((
                "public", f"user:{self.subject}", *self.groups,
            ))),
        )


def audit(action: str, decision: str, actor: Actor | None = None) -> None:
    """Record policy metadata only; never log tokens, prompts, or document text."""
    subject_hash = (
        sha256(actor.subject.encode("utf-8")).hexdigest()[:16] if actor else "anonymous"
    )
    logger.info(
        "security_event",
        extra={
            "action": action,
            "decision": decision,
            "subject_hash": subject_hash,
            "tenant": actor.tenant_id if actor else "none",
        },
    )


@lru_cache(maxsize=8)
def _jwks_client(url: str, timeout: int, lifespan: int) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, timeout=timeout, lifespan=lifespan)


def _claim_names(value: object, *, maximum: int = 32) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError("Invalid authorization claims")
    if any(not isinstance(item, str) or not _NAME.fullmatch(item) for item in value):
        raise ValueError("Invalid authorization claims")
    return tuple(dict.fromkeys(value))


def verify_access_token(token: str) -> Actor:
    settings = get_settings()
    if not settings.auth_issuer or not settings.auth_audience or not settings.auth_jwks_url:
        raise HTTPException(503, "Authentication is not configured.")
    if not settings.auth_jwks_url.startswith("https://"):
        raise HTTPException(503, "Authentication is not configured securely.")
    if len(token) > 8192:
        raise HTTPException(401, "Invalid access token.", headers={"WWW-Authenticate": "Bearer"})
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256" or header.get("typ") not in (
            "at+jwt", "application/at+jwt",
        ):
            raise ValueError("Unsupported access-token header")
        key = _jwks_client(
            settings.auth_jwks_url, settings.auth_jwks_timeout_seconds,
            settings.auth_jwks_cache_seconds,
        ).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token, key.key, algorithms=["RS256"],
            audience=settings.auth_audience, issuer=settings.auth_issuer,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
        subject = claims["sub"]
        tenant = claims.get(settings.auth_tenant_claim)
        if not isinstance(subject, str) or not _NAME.fullmatch(subject):
            raise ValueError("Invalid subject")
        if not isinstance(tenant, str) or not _NAME.fullmatch(tenant):
            raise ValueError("Invalid tenant")
        groups = _claim_names(claims.get(settings.auth_groups_claim, []))
        if any(group.startswith("user:") for group in groups):
            raise ValueError("Reserved principal namespace")
        roles = _claim_names(claims.get(settings.auth_roles_claim, []))
    except jwt.exceptions.PyJWKClientConnectionError as error:
        audit("authenticate", "jwks_unavailable")
        raise HTTPException(503, "Identity provider is unavailable.") from error
    except (jwt.PyJWTError, ValueError, KeyError, TypeError) as error:
        audit("authenticate", "deny")
        raise HTTPException(
            401, "Invalid access token.", headers={"WWW-Authenticate": "Bearer"},
        ) from error
    actor = Actor(subject=subject, tenant_id=tenant, groups=groups, roles=roles)
    audit("authenticate", "allow", actor)
    return actor


def get_actor(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Actor:
    if credentials is None or credentials.scheme.lower() != "bearer":
        audit("authenticate", "missing")
        raise HTTPException(
            401, "Bearer access token required.", headers={"WWW-Authenticate": "Bearer"},
        )
    actor = verify_access_token(credentials.credentials)
    limit = get_settings().rate_limit_requests_per_minute
    if not request_limiter.allow(f"{actor.tenant_id}:{actor.subject}", limit=limit):
        audit("request_rate", "deny", actor)
        raise HTTPException(429, "Rate limit exceeded.", headers={"Retry-After": "60"})
    return actor


def require_document_writer(actor: Actor = Depends(get_actor)) -> Actor:
    if "document:write" not in actor.roles:
        audit("document_write", "deny", actor)
        raise HTTPException(403, "Document write permission required.")
    audit("document_write", "allow", actor)
    return actor


def require_document_manager(actor: Actor = Depends(get_actor)) -> Actor:
    if "document:manage" not in actor.roles:
        audit("document_manage", "deny", actor)
        raise HTTPException(403, "Document management permission required.")
    audit("document_manage", "allow", actor)
    return actor
