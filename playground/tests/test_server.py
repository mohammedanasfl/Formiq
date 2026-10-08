"""The playground launcher against the real application: the page is served,
messages go to the existing POST /coach/message unchanged, signed in with an
access token, the execution headers carry only safe trace metadata, errors keep
their API status, and the production application is untouched.

The route, authentication, CoachService, the coach graph and the tracer are
real; the model is a fake, the database session a mock, and tokens are signed
with a test-only secret.
"""

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from unittest.mock import Mock

import pytest
import server
from fastapi.testclient import TestClient
from google.genai import types

from app.ai import AIProviderError, GeminiProvider, ModelTurn, ToolCall
from app.api.dependencies import get_access_tokens, get_ai_provider
from app.core.config import settings
from app.core.security import AccessTokens
from app.db.database import get_db
from app.models import User
from app.observability import Tracer
from app.observability.memory import MemoryBackend

STATIC = server.PLAYGROUND / "static"
TOKENS = AccessTokens("playground-test-only-signing-secret-0123456789")


def bearer(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKENS.issue(user_id)}"}


def respond(
    reply: str, intent: str = "GENERAL_FITNESS", decision: str = "ANSWER"
) -> ModelTurn:
    call = ToolCall(
        "respond", {"intent": intent, "decision": decision, "reply": reply}, id="c1"
    )
    content = types.Content(
        role="model",
        parts=[
            types.Part(
                function_call=types.FunctionCall(
                    id=call.id, name=call.name, args=call.arguments
                )
            )
        ],
    )
    return ModelTurn(content=content, tool_calls=(call,))


@pytest.fixture(scope="module")
def client():
    # once per process: the middleware must be added before the app starts
    if not getattr(server.app.state, "playground_installed", False):
        server.install()
        server.app.state.playground_installed = True
    return TestClient(server.app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def tokens():
    """Tokens are signed and verified with the test-only secret."""
    server.app.dependency_overrides[get_access_tokens] = lambda: TOKENS
    yield TOKENS
    server.app.dependency_overrides.pop(get_access_tokens, None)


def user(user_id: int) -> Mock:
    found = Mock(spec=User)
    found.id = user_id
    return found


@pytest.fixture
def db():
    """A mock session: user 404 does not exist, every other user does."""
    session = Mock()
    session.get.side_effect = lambda model, user_id: (
        None if user_id == 404 else user(user_id)
    )
    server.app.dependency_overrides[get_db] = lambda: session
    yield session
    server.app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def model():
    provider = Mock(spec=GeminiProvider)
    provider.model = "fake"
    server.app.dependency_overrides[get_ai_provider] = lambda: provider
    yield provider
    server.app.dependency_overrides.pop(get_ai_provider, None)


def execution(response) -> dict:
    return json.loads(response.headers[server.EXECUTION_HEADER])


# --- the page ---


def test_the_page_loads_with_its_warnings(client):
    page = client.get("/playground/")

    assert page.status_code == 200
    assert "LOCAL DEVELOPMENT ONLY" in page.text
    assert "The access token is kept in this page's memory only." in page.text
    assert 'type="password"' in page.text
    for asset in ("playground.js", "app.js", "styles.css"):
        assert client.get(f"/playground/{asset}").status_code == 200
    assert client.get("/", follow_redirects=False).headers["location"] == "/playground/"


def test_only_the_static_folder_is_served(client):
    for path in (
        "server.py",
        "README.md",
        "tests/test_server.py",
        "../server.py",
        "%2e%2e/server.py",
    ):
        assert client.get(f"/playground/{path}").status_code == 404, path


# --- the coach endpoint, unchanged ---


def test_a_message_goes_to_the_existing_endpoint_for_the_signed_in_user(client, db, model):
    model.generate_turn.side_effect = [
        respond("Progressive overload is adding load over time.")
    ]
    history = [
        {"role": "user", "text": "Hi"},
        {"role": "coach", "text": "Hello! How can I help?"},
    ]

    response = client.post(
        "/coach/message",
        headers=bearer(7),
        json={"message": "What is progressive overload?", "history": history},
    )

    assert response.status_code == 200
    # the API's own body, nothing added
    assert response.json() == {
        "reply": "Progressive overload is adding load over time."
    }
    # the user the token names, looked up to sign the request in and by the coach
    assert {call.args for call in db.get.call_args_list} == {(User, 7)}
    sent = model.generate_turn.call_args.args[0][0].parts
    assert "Hello! How can I help?" in sent[0].text
    assert sent[-1].text == "What is progressive overload?"
    run = execution(response)
    assert run["status"] == "success"
    assert (run["intent"], run["decision"], run["safety_category"]) == (
        "GENERAL_FITNESS",
        "ANSWER",
        "SAFE",
    )
    assert run["conversation_turns"] == 2
    assert response.headers[server.REQUEST_ID_HEADER] == run["request_id"]


def test_the_execution_headers_hold_metadata_never_content(client, db, model):
    model.generate_turn.side_effect = [respond("SENTINEL-REPLY")]

    response = client.post(
        "/coach/message",
        headers=bearer(7),
        json={
            "message": "SENTINEL-MESSAGE",
            "history": [{"role": "coach", "text": "SENTINEL-HISTORY"}],
        },
    )

    headers = json.dumps(dict(response.headers))
    assert "SENTINEL" not in headers
    assert set(execution(response)) <= set(server.SHOWN)
    assert "user_id" not in execution(response)


def test_a_flagged_request_shows_its_safety_category(client, db, model):
    model.generate_turn.side_effect = [
        respond(
            "Please stop and see a doctor or physiotherapist.",
            "SAFETY_SENSITIVE",
            "SAFE_REDIRECT",
        )
    ]

    response = client.post(
        "/coach/message", headers=bearer(7), json={"message": "I have sharp knee pain."}
    )

    run = execution(response)
    assert (run["safety_category"], run["status"]) == (
        "PAIN_OR_INJURY",
        "safety_redirect",
    )
    assert run["tools_used"] == []


def test_errors_keep_their_api_status_and_show_only_their_category(client, db, model):
    model.generate_turn.side_effect = AIProviderError("SENTINEL provider detail")

    response = client.post(
        "/coach/message", headers=bearer(7), json={"message": "What is my goal?"}
    )

    assert response.status_code == 502
    assert execution(response)["status"] == "provider_error"
    assert "SENTINEL" not in response.text + json.dumps(dict(response.headers))


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer not-a-token"}, bearer(404)],
    ids=["no_token", "bad_token", "unknown_user"],
)
def test_without_a_valid_token_the_coach_never_runs(client, db, model, headers):
    response = client.post(
        "/coach/message", headers=headers, json={"message": "What is my goal?"}
    )

    assert response.status_code == 401
    model.generate_turn.assert_not_called()
    # the coach never started, so there is no execution to show
    assert server.EXECUTION_HEADER not in response.headers


def test_an_unconfigured_provider_is_a_503(client, db):
    server.app.dependency_overrides[get_ai_provider] = lambda: GeminiProvider(
        None, "m", timeout_seconds=1
    )
    try:
        response = client.post(
            "/coach/message", headers=bearer(7), json={"message": "What is my goal?"}
        )
    finally:
        server.app.dependency_overrides.pop(get_ai_provider, None)

    assert response.status_code == 503
    assert execution(response)["status"] == "provider_not_configured"


def test_an_invalid_request_is_rejected_by_the_api_as_before(client, db, model):
    response = client.post(
        "/coach/message", headers=bearer(7), json={"user_id": 7, "message": ""}
    )

    assert response.status_code == 422
    model.generate_turn.assert_not_called()


def test_other_endpoints_get_no_playground_headers(client):
    response = client.get("/health")

    assert server.EXECUTION_HEADER not in response.headers


def test_simultaneous_requests_each_get_their_own_metadata(client, db, model):
    barrier = threading.Barrier(2)

    def turn(contents, **kwargs):
        barrier.wait(10)
        return respond(f"reply to {contents[0].parts[-1].text}")

    model.generate_turn.side_effect = turn
    results = {}

    def ask(turns):
        history = [{"role": "user", "text": "earlier"}] * turns
        results[turns] = client.post(
            "/coach/message",
            headers=bearer(7),
            json={"message": f"m{turns}", "history": history},
        )

    threads = [threading.Thread(target=ask, args=(turns,)) for turns in (0, 3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(20)

    assert {
        turns: execution(results[turns])["conversation_turns"] for turns in (0, 3)
    } == {0: 0, 3: 3}
    assert results[0].json() == {"reply": "reply to m0"}
    assert execution(results[0])["request_id"] != execution(results[3])["request_id"]


# --- tracing still reaches the configured backend ---


def test_the_configured_tracing_still_receives_every_call():
    inner = MemoryBackend()
    record: dict = {}
    token = server._record.set(record)
    try:
        with Tracer(server.RecordingBackend(inner)).request(
            "coach_request", request_id="r1", user_id=7
        ) as trace:
            with trace.child("step"):
                pass
            trace.finish("success", intent="PROFILE")
    finally:
        server._record.reset(token)

    assert [node.name for node in inner.nodes] == ["coach_request", "step"]
    assert inner.nodes[0].metadata["intent"] == "PROFILE"
    assert record["status"] == "success" and record["request_id"] == "r1"


# --- what the playground is not ---


def test_the_production_application_is_unchanged():
    # in a fresh process, without the playground: no page, no middleware, no override
    probe = (
        "import json\nfrom app.main import app\n"
        "print(json.dumps({'paths': sorted(app.openapi()['paths']), 'mounts': [getattr(r, 'path', None) for r in app.routes],"
        " 'middleware': len(app.user_middleware), 'overrides': len(app.dependency_overrides)}))"
    )
    env = {**os.environ, "DATABASE_URL": os.environ["DATABASE_URL"]}
    output = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=server.BACKEND,
        capture_output=True,
        text=True,
        check=True,
        env=env,
    ).stdout
    production = json.loads(output)

    assert not any(
        path.startswith("/playground") or path == "/" for path in production["paths"]
    )
    assert "/playground" not in production["mounts"]
    assert production["middleware"] == 0
    assert production["overrides"] == 0


def test_the_playground_runs_only_locally_and_in_development(monkeypatch):
    assert server.HOST == "127.0.0.1"
    monkeypatch.setattr(settings, "app_env", "production")
    with pytest.raises(SystemExit, match="APP_ENV=development"):
        server.main([])


def test_the_playground_holds_no_credentials_and_reaches_no_database():
    files = [*STATIC.iterdir(), server.PLAYGROUND / "server.py"]
    # no key, no database URL, and nothing kept in storage or cookies: the
    # access token lives in the page's memory only
    secret = re.compile(
        r"AIza[0-9A-Za-z_-]{10,}|sk-lf-|pk-lf-|postgres(ql)?://|localStorage|sessionStorage|"
        r"indexedDB|document\.cookie|eyJ[0-9A-Za-z_-]{10,}",
        re.IGNORECASE,
    )
    assert [path.name for path in files if secret.search(path.read_text())] == []
    # the page calls two endpoints, on its own origin, and never sends cookies
    script = (STATIC / "app.js").read_text()
    assert re.findall(r"fetch\(([^,]+),", script) == ["P.COACH_PATH", "P.LOGIN_PATH"]
    assert script.count('credentials: "omit"') == 2
    assert not re.search(r"https?://", script + (STATIC / "playground.js").read_text())
    # the launcher reaches data only through the application's API
    imported = set()
    for node in ast.walk(ast.parse((server.PLAYGROUND / "server.py").read_text())):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    forbidden = (
        "sqlalchemy",
        "psycopg",
        "app.db",
        "app.models",
        "app.repositories",
        "app.services",
    )
    assert sorted(name for name in imported if name.startswith(forbidden)) == []


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_the_page_logic():
    result = subprocess.run(
        ["node", "--test", str(server.PLAYGROUND / "tests" / "playground.test.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-2000:]
