"""Capability-protected, bounded PostgreSQL conversation history."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import secrets
from typing import Literal
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict

from app.core.config import get_settings
from app.db.database import database_connection
from app.retrieval.scope import RetrievalScope, document_filter_sql


class SessionNotFound(LookupError):
    """A session is absent, expired, unauthorized, or has an invalid token."""


class SessionConflict(RuntimeError):
    """The session changed while a turn was being computed."""


class StoredTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: UUID
    turn_index: int
    user_question: str
    resolved_question: str
    answer: str
    citations: list[dict]
    state: Literal["completed", "clarification"]
    created_at: datetime


class SessionSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    version: int
    created_at: datetime
    expires_at: datetime
    turns: list[StoredTurn]


class SessionCreated(BaseModel):
    session_id: UUID
    session_token: str
    expires_at: datetime


def _token_hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def _scope_matches(row: tuple, scope: RetrievalScope, subject: str) -> bool:
    return (row[1] == scope.tenant_id and row[2] == subject
            and set(row[3]) == set(scope.principals))


def purge_expired_sessions() -> int:
    """Delete expired sessions and their cascading turns."""
    with database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM conversation_sessions WHERE expires_at <= CURRENT_TIMESTAMP"
            )
            return cursor.rowcount


def create_session(*, scope: RetrievalScope, subject: str = "legacy") -> SessionCreated:
    settings = get_settings()
    purge_expired_sessions()
    session_id = uuid4()
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=settings.session_ttl_hours)
    with database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO conversation_sessions
                    (id, token_hash, tenant_id, owner_subject, principals,
                     created_at, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (session_id, _token_hash(token), scope.tenant_id, subject,
                 list(scope.principals), now, expires_at),
            )
    return SessionCreated(
        session_id=session_id, session_token=token, expires_at=expires_at,
    )


def load_session(
    session_id: UUID, token: str, *, scope: RetrievalScope,
    subject: str = "legacy",
) -> SessionSnapshot:
    settings = get_settings()
    with database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT token_hash, tenant_id, owner_subject, principals,
                       version, created_at, expires_at
                FROM conversation_sessions
                WHERE id = %s AND expires_at > CURRENT_TIMESTAMP
                """,
                (session_id,),
            )
            row = cursor.fetchone()
            if row is None or not _scope_matches(row, scope, subject) or not hmac.compare_digest(
                row[0], _token_hash(token),
            ):
                raise SessionNotFound("Session not found")
            cursor.execute(
                """
                SELECT id, turn_index, user_question, resolved_question,
                       answer, citations, state, created_at
                FROM conversation_turns
                WHERE session_id = %s
                ORDER BY turn_index DESC
                LIMIT %s
                """,
                (session_id, settings.session_max_stored_turns),
            )
            turn_rows = cursor.fetchall()
    return SessionSnapshot(
        session_id=session_id, version=row[4], created_at=row[5],
        expires_at=row[6],
        turns=[StoredTurn(
            turn_id=item[0], turn_index=item[1], user_question=item[2],
            resolved_question=item[3], answer=item[4], citations=item[5],
            state=item[6], created_at=item[7],
        ) for item in reversed(turn_rows)],
    )


def visible_source_titles(titles: set[str], *, scope: RetrievalScope) -> set[str]:
    """Reauthorize remembered source names before using them as context."""
    if not titles:
        return set()
    filters, parameters = document_filter_sql(scope)
    with database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT DISTINCT d.filename FROM documents AS d "
                "WHERE d.filename = ANY(%s::text[]) AND " + filters,
                [sorted(titles), *parameters],
            )
            return {row[0] for row in cursor.fetchall()}


def append_turn(
    session_id: UUID, token: str, *, scope: RetrievalScope,
    expected_version: int, user_question: str, resolved_question: str,
    answer: str, citations: list[dict], state: Literal["completed", "clarification"],
    subject: str = "legacy",
) -> UUID:
    settings = get_settings()
    turn_id = uuid4()
    with database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE conversation_sessions
                SET version = version + 1
                WHERE id = %s AND token_hash = %s AND tenant_id = %s
                  AND owner_subject = %s
                  AND principals = %s AND version = %s
                  AND expires_at > CURRENT_TIMESTAMP
                RETURNING version
                """,
                (session_id, _token_hash(token), scope.tenant_id, subject,
                 list(scope.principals), expected_version),
            )
            row = cursor.fetchone()
            if row is None:
                raise SessionConflict("Session changed or is unavailable")
            turn_index = row[0]
            cursor.execute(
                """
                INSERT INTO conversation_turns
                    (id, session_id, turn_index, user_question,
                     resolved_question, answer, citations, state)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (turn_id, session_id, turn_index, user_question,
                 resolved_question, answer, Jsonb(citations), state),
            )
            cursor.execute(
                """
                DELETE FROM conversation_turns
                WHERE session_id = %s AND turn_index <= %s
                """,
                (session_id, turn_index - settings.session_max_stored_turns),
            )
    return turn_id


def reset_session(
    session_id: UUID, token: str, *, scope: RetrievalScope,
    subject: str = "legacy",
) -> None:
    with database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE conversation_sessions SET version = version + 1
                WHERE id = %s AND token_hash = %s AND tenant_id = %s
                  AND owner_subject = %s
                  AND principals = %s AND expires_at > CURRENT_TIMESTAMP
                """,
                (session_id, _token_hash(token), scope.tenant_id, subject,
                 list(scope.principals)),
            )
            if cursor.rowcount != 1:
                raise SessionNotFound("Session not found")
            cursor.execute(
                "DELETE FROM conversation_turns WHERE session_id = %s",
                (session_id,),
            )


def delete_session(
    session_id: UUID, token: str, *, scope: RetrievalScope,
    subject: str = "legacy",
) -> None:
    with database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM conversation_sessions
                WHERE id = %s AND token_hash = %s AND tenant_id = %s
                  AND owner_subject = %s
                  AND principals = %s
                """,
                (session_id, _token_hash(token), scope.tenant_id, subject,
                 list(scope.principals)),
            )
            if cursor.rowcount != 1:
                raise SessionNotFound("Session not found")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Purge expired conversation sessions")
    parser.add_argument("--purge-expired", action="store_true", required=True)
    parser.parse_args()
    print(f"Purged {purge_expired_sessions()} expired sessions")
