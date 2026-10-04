"""Small local Stage 6 multi-turn behavior check (no session token in report)."""

import argparse
import json
from pathlib import Path

from app.memory.conversation_memory import create_session, delete_session, load_session
from app.memory.session_workflow import answer_in_session
from app.retrieval.scope import PUBLIC_SCOPE


FIRST_QUESTION = (
    "For a severity-one incident on the payments platform, who responds "
    "according to the payment incident runbook?"
)
FOLLOWUP_QUESTION = "Who owns that service?"


def run_scenario() -> dict:
    created = create_session(scope=PUBLIC_SCOPE)
    try:
        first = answer_in_session(
            created.session_id, created.session_token, FIRST_QUESTION,
        )
        second = answer_in_session(
            created.session_id, created.session_token, FOLLOWUP_QUESTION,
        )
        snapshot = load_session(
            created.session_id, created.session_token, scope=PUBLIC_SCOPE,
        )
        first_sources = {item.document for item in first.citations}
        second_sources = {item.document for item in second.citations}
        checks = {
            "first_turn_grounded_in_incident_runbook": (
                "payment-incident-runbook.md" in first_sources
            ),
            "followup_resolves_payments_platform": (
                "payments platform" in (second.resolved_question or "").casefold()
            ),
            "followup_grounded_in_ownership_guide": (
                "service-ownership.md" in second_sources
            ),
            "two_turns_persisted": len(snapshot.turns) == 2,
            "followup_uses_fresh_tool_search": any(
                event.tool_name == "search_documents" for event in second.trace
            ),
        }
        return {
            "scenario": "payment-platform-ownership-followup",
            "passed": all(checks.values()),
            "checks": checks,
            "first_turn": first.model_dump(mode="json", exclude_none=True),
            "followup_turn": second.model_dump(mode="json", exclude_none=True),
            "session_deleted_after_run": True,
        }
    finally:
        delete_session(
            created.session_id, created.session_token, scope=PUBLIC_SCOPE,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate one Stage 6 follow-up")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = run_scenario()
    serialized = json.dumps(report, indent=2) + "\n"
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(serialized, encoding="utf-8")
        print(f"Report saved to {arguments.output}")
    else:
        print(serialized)
    if not report["passed"]:
        raise SystemExit(1)
