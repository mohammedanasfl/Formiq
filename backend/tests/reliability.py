"""Helpers for the reliability tests: a model that answers from what each
request sends it, through the real Gemini SDK over a mock transport, a tracer
that records concurrent requests, and sessions that report being closed.

Nothing here calls Gemini or Langfuse, and nothing waits on time: threads meet
at barriers, and every wait has a bound so a broken run fails instead of
hanging.
"""

import json
import threading
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.ai import GeminiProvider
from app.observability import Tracer
from app.observability.memory import MemoryBackend, Node

# the longest any test waits on another thread
WAIT_SECONDS = 20

Handler = Callable[[httpx.Request], httpx.Response]


def transport_provider(handler: Handler, *, timeout_seconds: float = 30) -> GeminiProvider:
    """A real GeminiProvider, SDK included, whose HTTP requests go to handler
    instead of Google: the provider every request shares in production."""
    provider = GeminiProvider("test-key", "gemini-reliability", timeout_seconds=timeout_seconds)
    api = provider._client._api_client
    # the SDK's own client, replaced by one with a mock transport; the SDK
    # still builds, sends and parses every request
    assert isinstance(api._httpx_client, httpx.Client)
    api._httpx_client = httpx.Client(transport=httpx.MockTransport(handler))
    return provider


def model_response(name: str, **arguments: Any) -> httpx.Response:
    """Gemini's response calling one tool."""
    return model_calls([(name, arguments)])


def model_calls(calls: list[tuple[str, dict[str, Any]]]) -> httpx.Response:
    parts = [{"functionCall": {"name": name, "args": args}} for name, args in calls]
    return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": parts}}]})


def respond_response(reply: str, intent: str, decision: str) -> httpx.Response:
    return model_response("respond", intent=intent, decision=decision, reply=reply)


def api_error(code: int, status: str) -> httpx.Response:
    """Gemini's error response; its message must never reach the client."""
    return httpx.Response(
        code, json={"error": {"code": code, "message": "UPSTREAM_DETAIL_CANARY", "status": status}}
    )


class SentRequest:
    """One request the SDK sent, as Gemini would read it."""

    def __init__(self, request: httpx.Request) -> None:
        self.body = json.loads(request.content)
        self.timeout = request.extensions.get("timeout")
        contents = self.body["contents"]
        first = [part["text"] for part in contents[0]["parts"]]
        # the user's message is the first content's last part; the earlier
        # conversation, when there is one, is the part before it
        self.message = first[-1]
        self.history = first[0] if len(first) > 1 else ""
        self.results = [
            part["functionResponse"]
            for content in contents[1:]
            for part in content["parts"]
            if "functionResponse" in part
        ]
        config = self.body.get("toolConfig", {}).get("functionCallingConfig", {})
        self.allowed = config.get("allowedFunctionNames", [])
        self.text = json.dumps(self.body)

    @property
    def token(self) -> str:
        """The request's own marker: the message's first word."""
        return self.message.split()[0]


class EchoModel:
    """A model that answers from what each request sends, and nothing else.

    The message starts with a token naming the request. Its first turn calls
    the tool the message asks for; once a result is back, it responds with the
    token and what the latest result says. So a reply that holds another
    request's token, user or data could only come from shared state.

    It records every request it is sent, by token. With a barrier, each
    request's first model call waits there for the others, so all of them are
    in flight at once.
    """

    def __init__(self, barrier: threading.Barrier | None = None) -> None:
        self.barrier = barrier
        self.lock = threading.Lock()
        self.sent: dict[str, list[SentRequest]] = defaultdict(list)
        # what the model does instead of answering, by token: a response or an
        # exception to raise from the transport
        self.failures: dict[str, httpx.Response | Exception] = {}
        self.on_request: Callable[[SentRequest], None] | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        sent = SentRequest(request)
        with self.lock:
            self.sent[sent.token].append(sent)
        if self.on_request is not None:
            self.on_request(sent)
        if self.barrier is not None and not sent.results:
            self.barrier.wait(WAIT_SECONDS)
        failure = self.failures.get(sent.token)
        if isinstance(failure, Exception):
            raise failure
        if failure is not None:
            return failure
        return self.turn(sent)

    def requests(self, token: str) -> list[SentRequest]:
        with self.lock:
            return list(self.sent[token])

    def turn(self, sent: SentRequest) -> httpx.Response:
        if not sent.results:
            name, arguments = ask(sent.message)
            return model_response(name, **arguments)
        name, output = sent.results[-1]["name"], sent.results[-1]["response"]
        if "output" not in output:
            code = output.get("error", {}).get("code", "unknown")
            return respond_response(
                f"{sent.token} error={code.lower()}", INTENTS[name], "CANNOT_ANSWER"
            )
        return respond_response(
            f"{sent.token} {summary(name, output['output'])}", INTENTS[name], "RETRIEVE_THEN_ANSWER"
        )


INTENTS = {
    "get_user_profile": "PROFILE",
    "get_workout_plan": "WORKOUT_PLAN",
    "get_workout_session": "WORKOUT_HISTORY",
    "get_exercise": "EXERCISE",
    "search_exercises": "EXERCISE",
}


def ask(message: str) -> tuple[str, dict[str, Any]]:
    """The tool call a message asks for: "<token> goal", "<token> plan <id>",
    or "<token> exercise <id>"."""
    words = message.split()
    if "plan" in words:
        return "get_workout_plan", {"plan_id": int(words[words.index("plan") + 1])}
    if "exercise" in words:
        return "get_exercise", {"exercise_id": int(words[words.index("exercise") + 1])}
    return "get_user_profile", {}


def summary(name: str, output: dict[str, Any]) -> str:
    """What the model repeats of a result: ids and a number, never a name, so the
    reply passes Formiq's reply check."""
    if name == "get_user_profile":
        return f"user={output['user_id']} age={output['profile']['age']}"
    if name == "get_workout_plan":
        return f"plan={output['plan_id']} exercises={len(output['exercises'])}"
    return f"exercise={output['exercise_id']}"


# --- running requests at once ---


def concurrently(jobs: list[Callable[[], Any]]) -> list[Any]:
    """Each job's result, or the exception it raised, in the jobs' order; all
    jobs run at once, each on its own thread."""

    def run(job: Callable[[], Any]) -> Any:
        try:
            return job()
        except Exception as error:  # noqa: BLE001 - the test inspects it
            return error

    with ThreadPoolExecutor(len(jobs)) as pool:
        futures = [pool.submit(run, job) for job in jobs]
        return [future.result(timeout=WAIT_SECONDS * 3) for future in futures]


# --- tracing many requests at once ---


class ConcurrentBackend(MemoryBackend):
    """The in-memory backend, safe to share between threads, as the production
    tracer is shared between requests."""

    def __init__(self) -> None:
        super().__init__()
        self.lock = threading.RLock()

    def start_trace(self, **kwargs):
        with self.lock:
            return super().start_trace(**kwargs)

    def start(self, parent, **kwargs):
        with self.lock:
            return super().start(parent, **kwargs)

    def update(self, handle, **kwargs):
        with self.lock:
            super().update(handle, **kwargs)

    def end(self, handle):
        with self.lock:
            super().end(handle)

    def end_trace(self, handle):
        with self.lock:
            super().end_trace(handle)

    def roots(self) -> list[Node]:
        with self.lock:
            return [node for node in self.nodes if node.parent is None]

    def subtree(self, root: Node) -> list[Node]:
        """The observations of one request's trace."""
        with self.lock:
            found, frontier = [], [root.id]
            while frontier:
                parent = frontier.pop()
                children = [node for node in self.nodes if node.parent == parent]
                found += children
                frontier += [child.id for child in children]
            return found


def concurrent_tracer() -> tuple[Tracer, ConcurrentBackend]:
    backend = ConcurrentBackend()
    return Tracer(backend), backend


# --- sessions ---


class TrackedSessions:
    """Sessions on the test database that record being opened and closed."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.opened: list[Session] = []
        self.closed: list[Session] = []
        tracked = self

        class TrackedSession(Session):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__(*args, **kwargs)
                with tracked.lock:
                    tracked.opened.append(self)

            def close(self) -> None:
                with tracked.lock:
                    tracked.closed.append(self)
                super().close()

        self.session_class = TrackedSession

    def unclosed(self) -> list[Session]:
        with self.lock:
            return [s for s in self.opened if not any(s is c for c in self.closed)]

    def in_transaction(self) -> list[Session]:
        with self.lock:
            return [s for s in self.opened if s.in_transaction()]
