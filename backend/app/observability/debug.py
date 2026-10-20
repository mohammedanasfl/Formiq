"""Local agent debugging: an opt-in, developer-only view of one coach turn in the
terminal (AGENT_DEBUG, app.core.config).

It is a sink of its own. It shares nothing with the tracing backends: it never
touches Langfuse, never sets or reads LANGFUSE_CAPTURE_CONTENT, and writes only to
a stream (stderr by default), never to a file, the logging system or a service.
The coach records into it through RunTrace.debug, next to the trace, and never
reads anything back: the sink cannot change a turn, and a failure in it is
swallowed (it is logged by its type, once per turn).

Two levels, both off unless AGENT_DEBUG says so:

- events: the ordered timeline of the turn (the trajectory's own events, so the
  order is the trajectory's) and safe metadata: the prompt's identity (variant,
  size, hash), the tool declarations' identity, the sizes and roles of the
  messages sent, the tool calls' argument names, the outcome of every call and
  guard, the response's source and size. No text of any prompt or conversation.
- content: also the text of Formiq's own constants (the system prompt, the tool
  declarations, the replies Formiq itself writes, why a decision or reply was
  rejected) and the tool data that is safe to show.

What is safe to show is decided by allowlist, never by guessing at what looks
sensitive. Text a user, the model or stored data wrote (the message, the history,
the model's text and reply, plan names and notes, tool error messages, any string
value not on the lists below) is Private: it is shown as its role, its size and,
at the content level, a keyed hash (HMAC with a key made for this process, so a
short value cannot be recovered from it by trying candidates, and the same value
has the same hash within a run). Profile values and identifying fields are
redacted by name whatever their type. Numbers, booleans, ids, dates, the
catalog's own data and a short list of Formiq's result fields are shown. What the
model chose is shown only where it is Formiq's own vocabulary, which is what
Formiq declared to it for this turn: the tools offered, the argument names of
their schemas and the values those allow (FULL_BODY). A tool name, an argument
name or an argument value that is none of these is Private, whatever it looks
like. Anything shown also passes the scrubber, which removes the
configured secrets by value and tokens, keys, credentials, emails, phone numbers
and 32-character ids by pattern: a second line of defence, since a pattern cannot
find every sensitive value. Control characters are escaped, so no printed value
can drive the terminal.

Output is bounded: each message to MAX_MESSAGE_CHARS and each turn's content to
MAX_TURN_CHARS (Formiq's constants, printed once per process for each hash, to
MAX_CONSTANT_CHARS), always with a marker saying so. Four markers say why
something is not shown, and never mean another reason:

    <<not captured: ...>>    the level, or a cap, left it out
    <<unavailable: ...>>     there is nothing to show (the provider gave none)
    <<redacted: ...>>        it is private; its size, and at content its hash, are given
    <<truncated: ...>>       it was cut to its bound

Nothing here changes what the model is sent, what a tool does or what the API
answers.
"""

import hashlib
import hmac
import json
import logging
import os
import re
import sys
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, TextIO

logger = logging.getLogger(__name__)

LEVELS = ("events", "content")

# the longest text shown for one message, one value or one rendered result
MAX_MESSAGE_CHARS = 2_000
# the most content a turn prints, in all (the lines that say what happened are
# not content, and are bounded by the trajectory's own limit on events)
MAX_TURN_CHARS = 40_000
# the longest constant (the system prompt, the tool declarations) printed; each is
# printed once per process for each hash, so it is not charged to a turn
MAX_CONSTANT_CHARS = 40_000
MAX_ITEMS = 12
MAX_KEYS = 40
MAX_DEPTH = 6
MAX_FIELD_CHARS = 200
# a secret shorter than this is not scrubbed by value: it would mangle ordinary text
MIN_SECRET_CHARS = 8


# --- markers


def redacted(role: str, chars: int, digest: str | None = None) -> str:
    return f"<<redacted: {role}, {chars} chars{f', hmac {digest}' if digest else ''}>>"


def not_captured(why: str) -> str:
    return f"<<not captured: {why}>>"


def unavailable(why: str) -> str:
    return f"<<unavailable: {why}>>"


def truncated(chars: int, unit: str = "chars") -> str:
    return f"<<truncated: +{chars} {unit}>>"


# --- what is Formiq's, and what is not


@dataclass(frozen=True)
class Authored:
    """Text Formiq wrote (its constants, its templates): it may be shown."""

    text: str


@dataclass(frozen=True)
class Private:
    """Text a user, the model or stored data wrote: never shown, only its role,
    its size and a keyed hash."""

    text: str
    role: str


# --- what a request, a response and a call look like to the sink; the agent builds
# them (app.agent.debug_view), so this module knows nothing of the agent or the model


@dataclass(frozen=True)
class PartView:
    """One part of a message sent to the model. kind: history, user_message,
    model_text, thought, function_call or function_response."""

    kind: str
    # a text part's text: Private, never shown
    text: str | None = None
    name: str | None = None
    call_id: str | None = None
    # the provider gave the call no id: this one is made from its name and position
    synthesized_id: bool = False
    # a call's arguments, or a result
    data: Any = None
    # original, or compacted / superseded: a note replaced the result before it was sent
    status: str = "original"
    # the result a note replaced
    replaced: Any = None
    signature_bytes: int | None = None
    # safe facts about the part, shown as they are
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MessageView:
    index: int
    role: str
    parts: tuple[PartView, ...]


@dataclass(frozen=True)
class RequestView:
    number: int | None
    round: int
    kind: str
    model: str | None
    # base, pending-note or safety/<category>
    variant: str
    instructions: str
    # (name, description, parameters) of each tool offered
    declarations: tuple[tuple[str, str, Any], ...]
    # what is configured on the request besides the prompt and the tools
    config: Mapping[str, Any]
    # sizes and counts of the request and of its fitting to the budget
    facts: Mapping[str, Any]
    messages: tuple[MessageView, ...]
    # the names of every operation Formiq knows, offered or not (a write the model
    # may ask for is one): Formiq's own vocabulary, which a tool name may be
    known_tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class CallView:
    name: str
    call_id: str | None
    synthesized_id: bool
    arguments: Mapping[str, Any]


# --- the rules of what is shown

# the tools whose results are the exercise catalog's own data: public, not the user's
CATALOG_TOOLS = frozenset({"search_exercises", "get_exercise"})

# By name, whatever the value or its type: the user's identity, their profile and
# body, health, notes and goals, credentials, and what approves a proposal.
SENSITIVE_KEYS = frozenset(
    {
        "first_name", "last_name", "full_name", "display_name", "username", "user_name",
        "email", "phone", "user_id", "age", "gender", "goal", "profile", "binding",
        "proposal_id", "password", "passwd", "secret", "token", "authorization",
        "api_key", "apikey",
    }
)  # fmt: skip
SENSITIVE_PARTS = (
    "weight", "height", "email", "phone", "password", "secret", "token", "authorization",
    "note", "injur", "medical", "condition", "allerg", "goal", "gender", "sleep", "birth",
    "address", "diet",
)  # fmt: skip

# The strings of a tool's result that are Formiq's own vocabulary or the catalog's
# names (the exercise, its section and equipment, how a workout changed): shown.
# Every other string of a result, such as a plan's name, is Private.
RESULT_STRING_KEYS = frozenset(
    {
        "exercise_name", "section", "status", "equipment", "uses", "focus", "revision", "kind",
        "muscle", "muscles", "main_exercises", "before", "after", "unchanged", "difficulty",
        "movement_pattern", "category", "tool", "code", "excluded_equipment", "limitations",
        "trained_regions", "missing_regions", "regions",
    }
)  # fmt: skip

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ][\d:.]+(?:Z|[+-]\d{2}:\d{2})?)?")
_IDENTIFIER = re.compile(r"[A-Za-z_][\w.\-]{0,60}")
_CALL_ID = re.compile(r"[A-Za-z0-9_.:\-]{1,64}")
# a field's path at the start of a validation message (max_minutes, exercises.0.sets);
# it is shown only when every name in it is one Formiq declared, since the rest of the
# message can quote what the model sent
_FIELD = re.compile(r"(?:^|; )([A-Za-z_][\w\-]{0,60}(?:\.[\w\-]{1,60})*): ")

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def declared_vocabulary(parameters: Any, names: set[str], enums: set[str]) -> None:
    """The argument names and the values a tool's JSON schema declares: the
    names of its properties, at any depth, and its enum values."""
    if isinstance(parameters, Mapping):
        for key, value in parameters.items():
            if key == "properties" and isinstance(value, Mapping):
                names.update(str(name) for name in value)
            elif key == "enum" and isinstance(value, list):
                enums.update(item for item in value if isinstance(item, str))
            declared_vocabulary(value, names, enums)
    elif isinstance(parameters, list | tuple):
        for item in parameters:
            declared_vocabulary(item, names, enums)


def sensitive_key(key: str | None) -> bool:
    if not key:
        return False
    lowered = key.lower()
    return lowered in SENSITIVE_KEYS or any(part in lowered for part in SENSITIVE_PARTS)


def digest(text: str) -> str:
    """The stable hash of a Formiq constant (a prompt, the declarations), the same
    in every process. Never used for private text: that has a keyed hash."""
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def canonical(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True, ensure_ascii=False)


def clean(text: str) -> str:
    """The text with its control characters escaped: a printed value never drives
    the terminal."""
    return _CONTROL.sub(lambda match: f"\\x{ord(match.group()):02x}", text)


def bound(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + truncated(len(text) - limit)


class Scrubber:
    """Removes secrets from text that is about to be shown: the configured ones by
    value, and the shapes of tokens, keys, credentials, emails, phone numbers and
    long ids by pattern. Patterns are a second line of defence, not the first."""

    _PATTERNS = (
        (re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}"), "jwt"),
        (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"), "authorization"),
        (re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"), "api key"),
        (re.compile(r"\b(?:sk|pk|lf)[-_][A-Za-z0-9_-]{16,}"), "api key"),
        (re.compile(r"(?<=://)[^/\s:@]+:[^@\s]+(?=@)"), "credentials"),
        (re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"), "email"),
        (re.compile(r"(?<![\w.])\+\d[\d\s().-]{7,}\d(?!\w)"), "phone"),
        (re.compile(r"(?<![\w.])\(?\d{2,4}\)?[\s.-]\d{3,4}[\s.-]\d{3,4}(?!\w)"), "phone"),
        (re.compile(r"\b[0-9a-f]{32}\b"), "id"),
    )
    # a value after a name that says it is a secret; one already removed stays as it is
    _ASSIGNED = re.compile(
        r"(?i)\b(api[_ -]?key|secret|password|passwd|token|authorization)\b(\s*[:=]\s*)(?!<<)\S+"
    )

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        # the longest first, so a secret holding another is removed whole
        self._secrets = sorted(
            {secret for secret in secrets if secret and len(secret) >= MIN_SECRET_CHARS},
            key=len,
            reverse=True,
        )

    def exact(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, "<<redacted: secret>>")
        return text

    def __call__(self, text: str) -> str:
        text = self.exact(text)
        for pattern, label in self._PATTERNS:
            text = pattern.sub(f"<<redacted: {label}>>", text)
        return self._ASSIGNED.sub(
            lambda match: f"{match.group(1)}{match.group(2)}<<redacted: secret>>", text
        )


def _guarded(method: Callable[..., Any]) -> Callable[..., Any]:
    """A method of the turn's debug output that cannot fail the turn: an exception
    is logged by its type (a message could hold data), once, and ignored."""

    @wraps(method)
    def guarded(self: "TurnDebug", *args: Any, **kwargs: Any) -> Any:
        try:
            return method(self, *args, **kwargs)
        except Exception as error:  # noqa: BLE001 - debugging must not fail the turn
            self._failed(error)
            return None

    return guarded


class DebugSink:
    """The process's debug output: its level, its stream, what it scrubs and its
    bounds. begin() starts one turn's output (TurnDebug)."""

    def __init__(
        self,
        level: str,
        stream: TextIO | None = None,
        *,
        secrets: Iterable[str] = (),
        max_message_chars: int = MAX_MESSAGE_CHARS,
        max_turn_chars: int = MAX_TURN_CHARS,
        max_constant_chars: int = MAX_CONSTANT_CHARS,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        if level not in LEVELS:
            raise ValueError(f"the debug level is one of {', '.join(LEVELS)}")
        self.level = level
        self.scrub = Scrubber(secrets)
        self.max_message_chars = max_message_chars
        self.max_turn_chars = max_turn_chars
        self.max_constant_chars = max_constant_chars
        self.clock = clock
        # None: the process's stderr as it is when a line is written, so a
        # redirected or captured stderr is honoured
        self._stream = stream
        self._write_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._printed: set[tuple[str, str]] = set()
        # made for this process: the hash of a private value cannot be recovered
        # by trying candidates, and means nothing in another run
        self._key = os.urandom(16)

    @property
    def content(self) -> bool:
        return self.level == "content"

    def begin(self, turn_id: str, user_id: int | str) -> "TurnDebug":
        return TurnDebug(self, turn_id, user_id)

    def private_hash(self, text: str) -> str:
        return hmac.new(self._key, text.encode(), hashlib.sha256).hexdigest()[:12]

    def first(self, kind: str, key: str) -> bool:
        """True the first time in this process, for a constant of this hash."""
        with self._state_lock:
            if (kind, key) in self._printed:
                return False
            self._printed.add((kind, key))
            return True

    def emit(self, lines: Sequence[str]) -> None:
        """The lines, together: no other turn's line comes between them."""
        text = "".join(f"{clean(line)}\n" for line in lines)
        with self._write_lock:
            stream = sys.stderr if self._stream is None else self._stream
            try:
                stream.write(text)
            except UnicodeEncodeError:
                stream.write(text.encode("ascii", "backslashreplace").decode("ascii"))
            stream.flush()


class TurnDebug:
    """One coach turn's debug output. Every line carries the turn's short id, a
    sequence number that only grows and the milliseconds since the turn began, so
    turns running at once can be told apart and each read in order. Every public
    method is safe to call: it never raises."""

    def __init__(self, sink: DebugSink, turn_id: str, user_id: int | str) -> None:
        self.sink = sink
        self.turn_id = turn_id
        self._tag = clean(turn_id)[:8]
        self._began = sink.clock()
        self._seq = 0
        self._content_used = 0
        self._seen: dict[str, int] = {}
        self._warned = False
        # what Formiq declared to the model in this turn: the tools offered (and the
        # operations it knows), the argument names of their schemas and the values
        # those allow
        self._tools: set[str] = set()
        self._names: set[str] = set()
        self._enums: set[str] = set()
        sink.emit(
            [f"=== agent turn {clean(turn_id)} | user {clean(str(user_id))[:20]} "
             f"| AGENT_DEBUG={sink.level} ==="]
        )  # fmt: skip

    # --- lines

    def _failed(self, error: Exception) -> None:
        if not self._warned:
            self._warned = True
            logger.warning("Agent debug output failed (%s); the turn goes on", type(error).__name__)

    def _record(self, label: str, fields: str = "", body: Sequence[str] = ()) -> None:
        self._seq += 1
        elapsed = round((self.sink.clock() - self._began) * 1000)
        lines = [f"[{self._tag} #{self._seq:03d} +{elapsed:05d}ms] {label}{f' {fields}' if fields else ''}"]
        lines += [f"[{self._tag} #{self._seq:03d}]   {line}" for line in body]
        self.sink.emit(lines)

    def _value(self, value: Any) -> str:
        """A field's value: a primitive or a short list of them, scrubbed, cut."""
        if value is None:
            return "-"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int | float):
            return str(value)
        if isinstance(value, list | tuple):
            items = [self._value(item) for item in value[:MAX_ITEMS]]
            if len(value) > MAX_ITEMS:
                items.append(truncated(len(value) - MAX_ITEMS, "items"))
            return "[" + ",".join(items) + "]"
        text = bound(self.sink.scrub(str(value)), MAX_FIELD_CHARS)
        if text.startswith("<<") or re.fullmatch(r"[\w.:+/@#<>-]+", text):
            return text
        return json.dumps(text, ensure_ascii=False)

    def _fields(self, fields: Mapping[str, Any]) -> str:
        return " ".join(f"{key}={self._value(value)}" for key, value in fields.items())

    def _private(self, role: str, text: str) -> str:
        """Private text as what may be said of it: its role and size, and at the
        content level a keyed hash."""
        return redacted(role, len(text), self.sink.private_hash(text) if self.sink.content else None)

    # --- content, bounded: per message, then per turn

    def _shown(self, text: str) -> str:
        """Formiq's own text, scrubbed and cut to a message's bound."""
        return bound(self.sink.scrub(text), self.sink.max_message_chars)

    def _charge(self, text: str) -> str:
        """The text, if the turn may still print that much content; cut, or left
        out, with a marker when it may not."""
        room = self.sink.max_turn_chars - self._content_used
        if room <= 0:
            return not_captured(f"the turn's content cap of {self.sink.max_turn_chars} chars is reached")
        if len(text) > room:
            self._content_used = self.sink.max_turn_chars
            return text[:room] + truncated(len(text) - room)
        self._content_used += len(text)
        return text

    def _render(self, value: Any, *, key: str | None = None, mode: str = "args", depth: int = 0) -> str:
        """Data as the content level shows it: numbers, booleans, ids, enum-like
        words, dates and (in a result) the strings of RESULT_STRING_KEYS or the
        catalog; everything else, and every sensitive key, as <<redacted>>."""
        name = self._key_name(key, mode)
        if sensitive_key(key):
            return redacted(
                f"field {name}" if name else "field",
                len(canonical(value)),
                self.sink.private_hash(canonical(value)),
            )
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int | float):
            return str(value)
        if isinstance(value, str):
            if (
                mode == "catalog"
                or (mode == "result" and key in RESULT_STRING_KEYS)
                or (mode == "args" and value in self._enums)
                or _DATE.fullmatch(value)
            ):
                return json.dumps(self._shown(value), ensure_ascii=False)
            return self._private(f"text {name}" if name else "text", value)
        if depth >= MAX_DEPTH:
            return truncated(1, "levels")
        if isinstance(value, Mapping):
            shown = []
            for name, item in list(value.items())[:MAX_KEYS]:
                name = str(name)
                label = self._key_name(name, mode) or redacted("key", len(name))
                shown.append(f"{label}: {self._render(item, key=name, mode=mode, depth=depth + 1)}")
            if len(value) > MAX_KEYS:
                shown.append(truncated(len(value) - MAX_KEYS, "keys"))
            return "{" + ", ".join(shown) + "}"
        if isinstance(value, list | tuple):
            items = [self._render(item, key=key, mode=mode, depth=depth + 1) for item in value[:MAX_ITEMS]]
            if len(value) > MAX_ITEMS:
                items.append(truncated(len(value) - MAX_ITEMS, "items"))
            return "[" + ", ".join(items) + "]"
        return unavailable(f"a value of type {type(value).__name__} is not rendered")

    def _error(self, error: Any) -> str:
        """A tool's error: its code, and its message as a size and a hash, since a
        tool's message can quote what the model sent; with the fields a validation
        message names (identifiers only), and the catalog suggestions it carries."""
        if not isinstance(error, Mapping):
            return self._render(error, mode="result")
        parts = [f"code: {self._render(error.get('code'), key='code', mode='result')}"]
        message = error.get("message")
        if isinstance(message, str):
            parts.append(f"message: {self._private('tool message', message)}")
            fields = [f for f in dict.fromkeys(_FIELD.findall(message)) if self._plain_field(f)]
            if fields:
                parts.append(f"fields: {self._value(fields)}")
        if "suggestions" in error:
            parts.append(f"suggestions: {self._render(error['suggestions'], mode='catalog')}")
        if isinstance(error.get("loaded"), list):
            loaded = [
                f"{{tool: {self._tool(str(item.get('tool')))}, "
                f"result: {self._result(str(item.get('tool')), item.get('result'))}}}"
                for item in error["loaded"][:MAX_ITEMS]
                if isinstance(item, Mapping)
            ]
            parts.append(f"loaded: [{', '.join(loaded)}]")
        return "{" + ", ".join(parts) + "}"

    def _result(self, tool: str, result: Any) -> str:
        if not isinstance(result, Mapping):
            return self._render(result, mode="result")
        mode = "catalog" if tool in CATALOG_TOOLS else "result"
        parts = []
        if "output" in result:
            parts.append(f"output: {self._render(result['output'], mode=mode)}")
        if "error" in result:
            parts.append(f"error: {self._error(result['error'])}")
        if not parts:
            return self._render(result, mode=mode)
        return "{" + ", ".join(parts) + "}"

    def _key_name(self, key: str | None, mode: str) -> str | None:
        """A key's name where it may be said: in an argument, only a name a schema
        declared (the model chose it); in a result, a plain name (Formiq's own
        models wrote it). Else the name is not said, not even in a marker."""
        if key is None:
            return None
        known = key in self._names if mode == "args" else _IDENTIFIER.fullmatch(key)
        return clean(key) if known else None

    def _tool(self, name: str | None) -> str:
        """A tool's name when Formiq knows the operation or offered the tool; else it
        is the model's own text."""
        if name is None:
            return "-"
        return name if name in self._tools else self._private("tool name", name)

    def _argument_names(self, arguments: Mapping[str, Any]) -> str:
        names = sorted(str(name) for name in arguments)
        shown = [name for name in names if name in self._names]
        text = self._value(shown)
        if len(names) > len(shown):
            text += f" other_argument_names=<<redacted: {len(names) - len(shown)} name(s)>>"
        return text

    def _plain_field(self, path: str) -> bool:
        return all(part.isdigit() or part in self._names for part in path.split("."))

    def _call_id(self, call_id: str | None, synthesized: bool) -> str:
        if call_id is None:
            return "-"
        shown = call_id if _CALL_ID.fullmatch(call_id) else self._private("call id", call_id)
        return f"{self.sink.scrub(shown)}{' (synthesized)' if synthesized else ''}"

    # --- what the coach records

    @_guarded
    def event(self, event: Mapping[str, Any]) -> None:
        """One of the trajectory's events (app.observability.trajectory), as the
        trajectory recorded it: only its safe fields."""
        skipped = ("seq", "at", "t_ms", "type")
        fields = {key: value for key, value in event.items() if key not in skipped}
        if isinstance(fields.get("tool"), str):
            fields["tool"] = self._tool(fields["tool"])
        self._record(str(event.get("type")), f"ev={event.get('seq')} {self._fields(fields)}".rstrip())

    @_guarded
    def note(self, label: str, **fields: Any) -> None:
        """A line of safe metadata: counts, names, categories, never content."""
        self._record(label, self._fields(fields))

    @_guarded
    def user_input(self, message: str, history: Sequence[tuple[str, str]]) -> None:
        """What the client sent: the message and the earlier turns, as roles and
        sizes. Never their text: it is Private."""
        roles = [role for role, _ in history]
        body = []
        if self.sink.content:
            body = [f"history[{i}] {role}: {self._private(f'{role} turn', text)}" for i, (role, text) in enumerate(history)]
        self._record(
            "input",
            f"message={self._private('user message', message)} history_turns={len(history)} roles={self._value(roles)}",
            body,
        )

    @_guarded
    def request(self, build: Callable[[], RequestView]) -> None:
        """The model request about to be made: the prompt and the declarations
        (identity always, text at the content level once per process for each
        hash), the configuration, and every message in the order, with the roles
        and boundaries it is sent with. A result that a note replaced is shown as
        replaced, apart from the original."""
        view = build()
        self._tools.update(view.known_tools)
        for name, _, parameters in view.declarations:
            self._tools.add(name)
            declared_vocabulary(parameters, self._names, self._enums)
        self._record(
            "request",
            self._fields(
                {"n": view.number, "round": view.round, "kind": view.kind, "model": view.model, **view.facts}
            ),
        )
        self._constant("system_prompt", view.instructions, {"variant": view.variant})
        declarations = [
            {"name": name, "description": description, "parameters": parameters}
            for name, description, parameters in view.declarations
        ]
        lines = []
        for name, description, parameters in view.declarations:
            lines += [f"- {name}: {description}", f"    parameters: {canonical(parameters)}"]
        self._constant(
            "tool_declarations",
            canonical(declarations),
            {"n": len(declarations), "names": [name for name, _, _ in view.declarations]},
            lines=lines,
        )
        self._record("model_config", self._fields(view.config))
        for message in view.messages:
            self._message(message, view.number or 0)

    def _constant(
        self, label: str, text: str, fields: Mapping[str, Any], *, lines: Sequence[str] | None = None
    ) -> None:
        """A Formiq constant: its identity, and at the content level its text the
        first time this process sees this hash. The text is shown exactly as it is
        (only a configured secret would be removed from it): a test holds that no
        pattern of the scrubber alters Formiq's own prompt and declarations."""
        sink = self.sink
        key = digest(text)
        identity = self._fields({**fields, "chars": len(text), "sha256": key})
        if not sink.content:
            self._record(label, f"{identity} text={not_captured('level is events')}")
            return
        if not sink.first(label, key):
            self._record(label, f"{identity} text=<<printed earlier in this process>>")
            return
        shown = bound("\n".join(lines if lines is not None else text.split("\n")), sink.max_constant_chars)
        self._record(label, f"{identity} text=below", [sink.scrub.exact(line) for line in shown.split("\n")])

    def _message(self, message: MessageView, number: int) -> None:
        lines = [f"part {i} {line}" for i, part in enumerate(message.parts) for line in self._part(part, number)]
        self._record(f"context[{message.index}]", f"role={message.role} parts={len(message.parts)}", lines)

    def _part(self, part: PartView, number: int) -> list[str]:
        sink = self.sink
        labels = {"history": "history block", "user_message": "user message", "model_text": "model text", "thought": "model thought"}
        extra = self._fields(part.detail)
        extra = f" {extra}" if extra else ""
        signature = f" thought_signature_bytes={part.signature_bytes}" if part.signature_bytes else ""
        if part.kind in labels:
            return [f"{part.kind}: {self._private(labels[part.kind], part.text or '')}{extra}{signature}"]
        identity = f"name={self._tool(part.name)} id={self._call_id(part.call_id, part.synthesized_id)}"
        if part.kind == "function_call":
            if not sink.content:
                names = self._argument_names(part.data if isinstance(part.data, Mapping) else {})
                return [f"function_call: {identity} argument_names={names}{signature}"]
            args = self._data("function_call", part.name, part.data, number, "args")
            return [f"function_call: {identity}{signature} args={args}"]
        if part.kind == "function_response":
            if part.status != "original":
                size = len(canonical(part.replaced))
                original = f" replaced_hmac={sink.private_hash(canonical(part.replaced))}" if sink.content else ""
                return [
                    f"function_response: {identity} status={part.status} replaced_chars={size}{original} "
                    f"result={not_captured('a note replaced it before the request was sent')}"
                ]
            size = len(canonical(part.data))
            head = f"function_response: {identity} status=original chars={size}"
            if not sink.content:
                return [head]
            result = self._data("function_response", part.name, part.data, number, "result")
            return [f"{head} result={result}"]
        return [f"{part.kind}: {unavailable('this kind of part is not rendered')}"]

    def _data(self, kind: str, name: str | None, data: Any, number: int, mode: str) -> str:
        """A call's arguments or a result, rendered once in the turn: the same data
        met again (the next request sends back what the model asked for and what a
        tool returned) says where it was shown."""
        key = f"{kind}:{name}:{self.sink.private_hash(canonical(data))}"
        earlier = self._seen.get(key)
        if earlier is not None:
            return f"<<shown in request {earlier}>>"
        self._seen[key] = number
        text = self._result(name or "", data) if mode == "result" else self._render(data, mode="args")
        return self._charge(bound(text, self.sink.max_message_chars))

    @_guarded
    def response(
        self,
        number: int | None,
        *,
        text: str | None,
        calls: Sequence[CallView],
        usage: Mapping[str, int] | None,
        model_reported: str | None,
    ) -> None:
        """What the model returned: its text (Private), its calls with their ids and
        arguments, and the token counts the provider reported."""
        tokens: Any = unavailable("the provider reported none")
        if usage:
            tokens = " ".join(f"{name}={count}" for name, count in usage.items())
        shown_text = "-" if text is None else self._private("model text", text)
        body = []
        for index, call in enumerate(calls):
            identity = f"name={self._tool(call.name)} id={self._call_id(call.call_id, call.synthesized_id)}"
            if self.sink.content:
                args = self._data("function_call", call.name, call.arguments, number or 0, "args")
                body.append(f"call[{index}] {identity} args={args}")
            else:
                body.append(f"call[{index}] {identity} argument_names={self._argument_names(call.arguments)}")
        self._record(
            "response",
            f"request={number} model_reported={self._value(model_reported)} calls={len(calls)} text={shown_text} "
            f"thinking={unavailable('not requested')} tokens={tokens}",
            body,
        )

    @_guarded
    def tool(
        self,
        *,
        name: str,
        call_id: str | None,
        synthesized_id: bool,
        origin: str,
        outcome: str,
        category: str | None,
        code: str | None,
        repeat: str,
        duration_ms: int | None,
        result: Mapping[str, Any] | None,
    ) -> None:
        """A tool call's outcome: executed, blocked or failed, why, how long, and at
        the content level its result as far as it is safe to show."""
        head = self._fields(
            {
                "name": self._tool(name), "origin": origin, "outcome": outcome, "category": category,
                "error_code": code, "repeat": repeat, "ms": duration_ms,
                "result_chars": None if result is None else len(canonical(result)),
            }
        )  # fmt: skip
        head = f"{head} id={self._call_id(call_id, synthesized_id)}"
        body = []
        if self.sink.content and result is not None:
            body = [f"result={self._charge(bound(self._result(name, result), self.sink.max_message_chars))}"]
        self._record("tool_result", head, body)

    @_guarded
    def guard(
        self,
        name: str,
        *,
        accepted: bool,
        by: str | None = None,
        reason: str | None = None,
        rejection: Authored | None = None,
        respond_args: Mapping[str, Any] | None = None,
        fields: Sequence[str] = (),
        **facts: Any,
    ) -> None:
        """A guard's verdict on the model's decision or reply: accepted, or why not.
        reason is the category; rejection, Formiq's own words for it, shown at the
        content level; respond_args, the model's respond arguments (its reply Private)."""
        known = {"by": by, "reason": reason}
        head = self._fields(
            {"accepted": accepted, **{k: v for k, v in known.items() if v is not None}, **facts}
        )
        if fields:
            # only paths of names Formiq declared: any other is the model's own text
            plain = [name for name in fields if self._plain_field(name)]
            hidden = len(fields) - len(plain)
            head += f" invalid_fields={self._value(plain)}"
            if hidden:
                head += f" other_invalid_fields=<<redacted: {hidden} field name(s)>>"
        body = []
        if self.sink.content:
            if rejection is not None:
                body.append(f"rejection: {self._charge(self._shown(rejection.text))}")
            if respond_args is not None:
                body.append(f"respond: {self._charge(bound(self._render(respond_args), self.sink.max_message_chars))}")
        self._record(name, head, body)

    @_guarded
    def response_source(self, source: str, detail: str, reply: Authored | Private) -> None:
        """Who wrote the reply the user gets: the model, or Formiq (a safety
        fallback, a generic one, or the card of the proposal Formiq accepted)."""
        text = reply.text
        body = []
        if isinstance(reply, Authored):
            shown = f"chars={len(text)} sha256={digest(text)}"
            if self.sink.content:
                body = [self._charge(self._shown(text))]
            else:
                shown += f" text={not_captured('level is events')}"
        else:
            shown = f"reply={self._private('model reply', text)}"
        self._record("response_source", f"source={source} detail={detail} {shown}", body)

    @_guarded
    def summary(self, build: Callable[[], Mapping[str, Any]]) -> None:
        """The turn's end: its outcome, tokens and time, from the trajectory's
        summary, which holds only safe fields."""
        summary = build()
        tokens = summary.get("tokens") or {}
        latency = summary.get("latency_ms") or {}
        calls = summary.get("tool_calls") or {}
        proposal = summary.get("proposal") or {}
        self._record(
            "summary",
            self._fields(
                {
                    "status": summary.get("status"),
                    "termination": summary.get("termination"),
                    "intent": summary.get("intent"),
                    "decision": summary.get("decision"),
                    "model": summary.get("model"),
                    "model_requests": summary.get("model_requests"),
                    "tool_calls_requested": calls.get("requested"),
                    "tool_calls_executed": calls.get("executed"),
                    "tool_calls_blocked": calls.get("blocked"),
                    "tool_calls_failed": calls.get("failed"),
                    "proposal": proposal.get("outcome"),
                    "proposal_ref": proposal.get("proposal_ref"),
                    "tokens_total": tokens.get("total"),
                    "tokens_source": tokens.get("source"),
                    "latency_turn_ms": latency.get("turn"),
                    "latency_model_ms": latency.get("model_total"),
                    "latency_tool_ms": latency.get("tool_total"),
                    "failure_reasons": summary.get("failure_reasons"),
                }
            ),
        )
        self._record("end", "")
