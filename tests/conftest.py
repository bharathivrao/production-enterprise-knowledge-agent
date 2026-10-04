"""Legacy API tests use a verified-actor fixture; auth tests exercise the real edge."""

import pytest

from app.guardrails.auth import Actor, get_actor
from app.main import app


@pytest.fixture(autouse=True)
def authenticated_api_fixture(request):
    if request.node.get_closest_marker("real_auth"):
        yield
        return
    actor = Actor(
        subject="test-user", tenant_id="default", groups=("public",),
        roles=("document:write", "document:manage", "document:publish"),
    )
    app.dependency_overrides[get_actor] = lambda: actor
    yield
    app.dependency_overrides.pop(get_actor, None)
