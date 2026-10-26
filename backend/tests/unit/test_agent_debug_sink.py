"""AGENT_DEBUG, local debugging of the coach's turns (app.observability.debug): the
setting and where it is refused, what the sink may show and what it never does,
its bounds, and that it can fail without a turn noticing.

Nothing here calls a model, a database or Langfuse: the sink writes to memory.
The turns it shows are tested with the graph in test_agent_debug_turns.
"""

import ast
import hashlib
import io
import json
import logging
import re
import sys
import threading
from pathlib import Path

import pytest
from pydantic import ValidationError

import app.observability.debug as debug_module
from app.api import dependencies
from app.core.config import Settings, agent_debug_allowed
from app.observability import TRACING_OFF, Tracer
from app.observability.debug import (
    MAX_CONSTANT_CHARS,
    MAX_MESSAGE_CHARS,
    MAX_TURN_CHARS,
    Authored,
    CallView,
    DebugSink,
    MessageView,
    PartView,
    Private,
    RequestView,
    Scrubber,
    digest,
)
from tests.observability import RecordingBackend, debugging, labelled, parse

BASE = {"database_url": "postgresql://user:DB-PASSWORD-CANARY@localhost/db"}


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """The settings read only what a test gives them."""
    for name in ("APP_ENV", "AGENT_DEBUG"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def loggers_enabled(monkeypatch):
    """Alembic's logging setup disables the loggers that exist once the integration
    tests' migrations ran: these tests read what the debug output logs of its own
    failures, so their loggers are enabled again."""
    for name in ("app.observability.debug", "app.observability.tracing", "app.agent.debug_view"):
        monkeypatch.setattr(logging.getLogger(name), "disabled", False)


def settings_with(**values) -> Settings:
    return Settings(_env_file=None, **BASE, **values)


# --- the setting: off by default, refused where it must not run


def test_the_debug_output_is_off_by_default():
    assert settings_with().agent_debug == "off"
    assert settings_with(app_env="production").agent_debug == "off"


@pytest.mark.parametrize(
    ("value", "level"),
    [
        ("off", "off"),
        ("events", "events"),
        ("content", "content"),
        ("Events", "events"),
        (" CONTENT ", "content"),
        ("", "off"),
    ],
)
def test_the_three_levels(value, level):
    assert settings_with(app_env="development", agent_debug=value).agent_debug == level


def test_an_unknown_level_is_refused_not_ignored():
    with pytest.raises(ValidationError):
        settings_with(app_env="development", agent_debug="loud")


@pytest.mark.parametrize("level", ["events", "content"])
@pytest.mark.parametrize("app_env", ["production", "staging", "prod", "Development", ""])
def test_it_is_refused_outside_development_and_test(app_env, level):
    with pytest.raises(ValidationError, match="local development only"):
        settings_with(app_env=app_env, agent_debug=level)


@pytest.mark.parametrize("level", ["events", "content"])
@pytest.mark.parametrize("app_env", ["development", "test"])
def test_it_is_allowed_in_development_and_test(app_env, level):
    assert settings_with(app_env=app_env, agent_debug=level).agent_debug == level


@pytest.mark.parametrize("level", ["events", "content"])
def test_it_is_refused_when_app_env_is_left_to_its_default(level):
    # the default says "development" of an application that may be anywhere
    with pytest.raises(ValidationError, match="APP_ENV") as refused:
        settings_with(agent_debug=level)

    assert "by default, not set" in str(refused.value)


def test_app_env_given_by_the_environment_counts_as_set(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AGENT_DEBUG", "content")

    assert Settings(_env_file=None, **BASE).agent_debug == "content"


def test_app_env_given_by_a_dotenv_file_counts_as_set(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("APP_ENV=test\nAGENT_DEBUG=events\n")

    assert Settings(_env_file=dotenv, **BASE).agent_debug == "events"


def test_the_refusal_names_no_secret_and_no_other_setting():
    with pytest.raises(ValidationError) as refused:
        settings_with(
            app_env="production",
            agent_debug="content",
            gemini_api_key="GEMINI-KEY-CANARY-123",
            auth_jwt_secret="JWT-SECRET-CANARY-" + "x" * 32,
            langfuse_secret_key="LANGFUSE-SECRET-CANARY",
        )

    message = str(refused.value)
    for canary in ("CANARY", "postgresql://", "password"):
        assert canary not in message


def test_the_permitted_environments_are_exactly_development_and_test():
    assert agent_debug_allowed("development", explicit=True)
    assert agent_debug_allowed("test", explicit=True)
    assert not agent_debug_allowed("development", explicit=False)
    assert not agent_debug_allowed("production", explicit=True)
    assert not agent_debug_allowed(None, explicit=True)


def test_building_the_sink_checks_the_actual_settings_again(monkeypatch):
    # the settings may have been changed after they loaded
    changed = settings_with(app_env="development", agent_debug="content")
    monkeypatch.setattr(changed, "app_env", "production")
    monkeypatch.setattr(dependencies, "settings", changed)
    with pytest.raises(ValueError, match="local development only"):
        dependencies.build_debug_sink()

    # and a default APP_ENV is no permission, whatever else was set
    unset = settings_with()
    monkeypatch.setattr(unset, "agent_debug", "events")
    monkeypatch.setattr(dependencies, "settings", unset)
    with pytest.raises(ValueError, match="local development only"):
        dependencies.build_debug_sink()


def test_no_sink_is_built_when_it_is_off(monkeypatch):
    monkeypatch.setattr(dependencies, "settings", settings_with())

    assert dependencies.build_debug_sink() is None


def test_the_tracer_has_no_debug_output_by_default(monkeypatch):
    monkeypatch.setattr(dependencies, "settings", settings_with(app_env="test"))
    dependencies.get_tracer.cache_clear()
    try:
        tracer = dependencies.get_tracer()
    finally:
        dependencies.get_tracer.cache_clear()

    assert tracer.debug is None


def test_the_debug_output_rides_on_its_own_tracer_and_the_shared_one_is_untouched(monkeypatch):
    monkeypatch.setattr(
        dependencies, "settings", settings_with(app_env="test", agent_debug="events")
    )
    dependencies.get_tracer.cache_clear()
    try:
        tracer = dependencies.get_tracer()
    finally:
        dependencies.get_tracer.cache_clear()

    assert tracer.debug is not None and tracer.debug.level == "events"
    assert tracer is not TRACING_OFF and TRACING_OFF.debug is None
    assert tracer.enabled is False  # no backend: the debug output is not tracing
    assert tracer.capture_content is False


def test_the_debug_output_leaves_what_langfuse_is_configured_with_alone(monkeypatch):
    configured = Tracer(RecordingBackend(), capture_content=True)
    monkeypatch.setattr(dependencies, "create_tracer", lambda **kwargs: configured)
    monkeypatch.setattr(
        dependencies, "settings", settings_with(app_env="development", langfuse_capture_content=True)
    )
    dependencies.get_tracer.cache_clear()
    try:
        without = dependencies.get_tracer()
        monkeypatch.setattr(dependencies.settings, "agent_debug", "content")
        dependencies.get_tracer.cache_clear()
        with_debug = dependencies.get_tracer()
    finally:
        dependencies.get_tracer.cache_clear()

    assert without is configured
    # the same backend and the same capture setting, the debug output beside them
    assert with_debug.backend is configured.backend
    assert with_debug.capture_content is configured.capture_content is True
    assert with_debug.debug is not None


def test_the_secrets_the_sink_scrubs_are_collected_by_value(monkeypatch):
    monkeypatch.setattr(
        dependencies,
        "settings",
        settings_with(
            app_env="test",
            gemini_api_key="GEMINI-KEY-CANARY",
            auth_jwt_secret="J" * 40,
            langfuse_secret_key="LANGFUSE-SECRET-CANARY",
            langfuse_public_key="LANGFUSE-PUBLIC-CANARY",
            test_database_url="postgresql://user:TEST-PASSWORD-CANARY@localhost/formiq_test",
        ),
    )

    assert set(dependencies.debug_secrets()) == {
        "GEMINI-KEY-CANARY",
        "J" * 40,
        "LANGFUSE-SECRET-CANARY",
        "LANGFUSE-PUBLIC-CANARY",
        "DB-PASSWORD-CANARY",
        "TEST-PASSWORD-CANARY",
    }


# --- the scrubber: a second line of defence


def test_configured_secrets_are_removed_by_value_wherever_they_are():
    scrub = Scrubber(["GEMINI-KEY-CANARY-123", "JWT-SECRET-CANARY-456", "short"])

    scrubbed = scrub("a GEMINI-KEY-CANARY-123, b-JWT-SECRET-CANARY-456-c, and short")

    assert "CANARY" not in scrubbed
    # a secret too short to be told from ordinary text is not scrubbed by value
    assert "short" in scrubbed


@pytest.mark.parametrize(
    ("text", "gone"),
    [
        ("token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.c2lnbmF0dXJl", "eyJhbGci"),
        ("Authorization: Bearer abcdef1234567890", "abcdef1234567890"),
        ("key AIzaSyA-1234567890abcdefghijklmnopqrstu", "AIzaSy"),
        ("secret: hunter2hunter2", "hunter2"),
        ("password=hunter2hunter2", "hunter2"),
        ("postgresql://user:pa55word@localhost/db", "pa55word"),
        ("mail someone.name+tag@example.co.uk please", "someone.name"),
        ("call +44 20 7946 0958 now", "7946"),
        ("call (555) 123-4567 now", "123-4567"),
        ("call 555-123-4567 now", "123-4567"),
        ("id 0123456789abcdef0123456789abcdef", "0123456789abcdef0123456789abcdef"),
        ("lf_sk_1234567890abcdefghij", "lf_sk_"),
    ],
)
def test_the_shapes_of_secrets_and_contact_details_are_removed(text, gone):
    assert gone not in Scrubber()(text)


def test_ordinary_text_dates_and_figures_are_left_alone():
    text = "3 sets of 10 reps, 60 s rest, on 2026-10-17T10:30:00Z: plan 12, session 4, exercise 41"

    assert Scrubber()(text) == text


def test_no_pattern_alters_formiqs_own_prompts_and_declarations():
    # they are shown exactly as they are, so no pattern of the scrubber may reach them
    from app.agent.graph import COACH_INSTRUCTIONS, safety_instructions
    from app.agent.policy import SAFETY_POLICY
    from app.tools import TOOL_DECLARATIONS

    scrub = Scrubber()
    texts = [COACH_INSTRUCTIONS, *(safety_instructions(p) for p in SAFETY_POLICY.values())]
    texts += [json.dumps([d.name, d.description, d.parameters]) for d in TOOL_DECLARATIONS]

    for text in texts:
        assert scrub(text) == text


# --- what is shown, and what is redacted, whatever it looks like


def turn_debug(level="content", **options):
    debugger = debugging(level, **options)
    return debugger.sink.begin("a" * 32, 5), debugger


PLAN = {
    "output": {
        "plan_id": 12,
        "user_id": 5,
        "name": "Zainab's rehab plan",
        "status": "PLANNED",
        "scheduled_date": "2026-10-18",
        "age": 34,
        "gender": "female",
        "profile": {"first_name": "Zainab", "last_name": "Qureshi", "weight_kg": 71.5},
        "free": "my left knee hurts when I squat",
        "ok": True,
        "nothing": None,
        "exercises": [
            {
                "exercise_name": "Goblet Squat",
                "section": "MAIN_WORKOUT",
                "sets": 3,
                "reps": 10,
                "weight_kg": 20.5,
                "notes": "careful with the knee",
            }
        ],
    }
}


def show_tool(name, result, level="content", declared=None, **options):
    turn, debugger = turn_debug(level, **options)
    if declared is not None:
        turn.request(lambda: request_view(declarations=declared))
    turn.tool(
        name=name, call_id="call-1", synthesized_id=False, origin="model", outcome="ok",
        category=None, code=None, repeat="none", duration_ms=3, result=result,
    )  # fmt: skip
    return debugger.stream.getvalue()


def test_numbers_ids_enum_words_dates_and_catalog_fields_are_shown():
    shown = show_tool("get_workout_plan", PLAN)

    for text in (
        "plan_id: 12",
        'status: "PLANNED"',
        'scheduled_date: "2026-10-18"',
        'exercise_name: "Goblet Squat"',
        'section: "MAIN_WORKOUT"',
        "sets: 3",
        "reps: 10",
        "ok: true",
        "nothing: null",
    ):
        assert text in shown


def test_identity_profile_body_health_and_notes_are_redacted_by_name_whatever_the_type():
    shown = show_tool("get_workout_plan", PLAN)

    for secret in ("Zainab", "Qureshi", "female", "71.5", "20.5", "knee", "34,"):
        assert secret not in shown
    for redacted in ("field profile", "field age", "field gender", "field weight_kg", "field notes", "field user_id"):
        assert f"<<redacted: {redacted}," in shown


def test_any_other_string_is_private_by_default_and_a_plans_name_is_one():
    shown = show_tool("get_workout_plan", PLAN)

    assert "rehab" not in shown and "squat" not in shown.replace("Goblet Squat", "")
    assert "<<redacted: text name, 19 chars, hmac " in shown
    assert "<<redacted: text free, 31 chars, hmac " in shown


def test_the_exercise_catalogs_own_data_is_shown_apart_from_what_is_sensitive():
    catalog = {
        "output": {
            "exercises": [
                {
                    "name": "Barbell Squat",
                    "instructions": ["Stand tall.", "Bend the knees."],
                    "equipment": ["Barbell"],
                    "notes": "a catalog note is still a note",
                }
            ]
        }
    }

    shown = show_tool("search_exercises", catalog)

    assert 'name: "Barbell Squat"' in shown and '"Bend the knees."' in shown
    assert "a catalog note" not in shown and "<<redacted: field notes," in shown


def test_a_tools_error_shows_its_code_and_the_fields_it_names_never_its_message():
    error = {
        "error": {
            "code": "INVALID_INPUT",
            "message": (
                "max_minutes: Input should be less than or equal to 180; "
                "exercises.0.sets: Field required; "
                "the catalog has no equipment 'my torn ACL brace'"
            ),
            "suggestions": [{"exercise_id": 41, "name": "Dead Bug", "for": "the core"}],
        }
    }

    declared = (
        (
            "propose_workout_plan",
            "Propose a workout.",
            {"properties": {"max_minutes": {}, "exercises": {"items": {"properties": {"sets": {}}}}}},
        ),
    )

    shown = show_tool("propose_workout_plan", error, declared=declared)

    assert 'code: "INVALID_INPUT"' in shown
    assert "fields: [max_minutes,exercises.0.sets]" in shown
    assert "ACL" not in shown and "<<redacted: tool message," in shown
    # Formiq's own suggestions are catalog exercises
    assert 'name: "Dead Bug"' in shown and 'for: "the core"' in shown


def test_the_results_formiq_loaded_for_a_refused_proposal_are_rendered_by_the_same_rules():
    refusal = {
        "error": {
            "code": "CONTEXT_MISSING",
            "message": "Formiq read get_user_profile for you",
            "loaded": [{"tool": "get_user_profile", "result": {"output": {"profile": {"goal": "knee rehab"}}}}],
        }
    }

    shown = show_tool("propose_workout_plan", refusal)

    assert "knee rehab" not in shown
    assert "loaded: [" in shown and "<<redacted: field profile," in shown


def test_a_value_the_sink_cannot_render_is_unavailable_not_guessed():
    shown = show_tool("get_workout_plan", {"output": {"odd": object()}})

    assert "<<unavailable: a value of type object is not rendered>>" in shown


def test_a_key_that_is_not_a_plain_name_is_redacted():
    shown = show_tool("get_workout_plan", {"output": {"my knee hurts": 1, "plan_id": 3}})

    assert "my knee hurts" not in shown and "<<redacted: key, 13 chars>>" in shown and "plan_id: 3" in shown


# what the model chose is shown only where it is Formiq's own vocabulary


SCHEMA = {
    "properties": {
        "use": {"enum": ["MAIN_WORKOUT", "WARM_UP"], "type": "string"},
        "muscle": {"type": "string"},
        "exercises": {"items": {"properties": {"exercise_id": {}, "sets": {}}}},
    }
}


def show_call(name, arguments, known=()):
    turn, debugger = turn_debug("content")
    turn.request(lambda: request_view(declarations=(("search_exercises", "Search.", SCHEMA),), known=known))
    turn.response(1, text=None, calls=[CallView(name, "call-1", False, arguments)], usage=None, model_reported=None)
    return debugger.stream.getvalue()


def test_an_argument_name_is_shown_only_if_a_schema_declared_it():
    shown = show_call(
        "search_exercises",
        {"use": "WARM_UP", "my_knee_surgery_flag": 1, "my_knee_surgery_notes": 2, "muscle": "Chest"},
    )

    assert "use: " in shown and "muscle: " in shown
    # a name that looks like any other, and is the model's own, is not shown: not as a key, and
    # not in the marker of a value that is redacted for its name
    assert "my_knee_surgery" not in shown
    assert "<<redacted: key, 20 chars>>: 1" in shown
    assert "<<redacted: key, 21 chars>>: <<redacted: field, 1 chars, hmac " in shown


def test_an_argument_value_is_shown_only_if_a_schema_allows_it():
    shown = show_call("search_exercises", {"use": "WARM_UP", "muscle": "SURGERY", "extra": "MAIN_WORKOUT"})

    assert 'use: "WARM_UP"' in shown
    # shaped like a word of the vocabulary, but not one the schema allows for this
    assert "SURGERY" not in shown and "<<redacted: text muscle, 7 chars," in shown


def test_the_names_of_the_arguments_of_a_call_are_filtered_at_the_events_level_too():
    turn, debugger = turn_debug("events")
    turn.request(lambda: request_view(declarations=(("search_exercises", "Search.", SCHEMA),)))

    turn.response(1, text=None, calls=[CallView("search_exercises", "c1", False, {"use": 1, "knee_pain_history": 2})], usage=None, model_reported=None)

    out = debugger.stream.getvalue()
    assert "argument_names=[use] other_argument_names=<<redacted: 1 name(s)>>" in out
    assert "knee_pain" not in out


def test_a_tool_name_is_shown_if_it_was_offered_or_is_one_formiq_knows_and_else_it_is_private():
    offered = show_call("search_exercises", {})
    known = show_call("cancel_workout_plan", {}, known=("cancel_workout_plan",))
    invented = show_call("my_knee_surgery_tool", {}, known=("cancel_workout_plan",))

    assert "call[0] name=search_exercises " in offered
    assert "call[0] name=cancel_workout_plan " in known
    assert "knee_surgery" not in invented and "call[0] name=<<redacted: tool name, 20 chars, hmac " in invented


def test_a_tool_name_in_an_event_is_filtered_by_the_same_rule():
    turn, debugger = turn_debug("events")
    turn.request(lambda: request_view())

    turn.event({"seq": 1, "type": "tool_call_requested", "tool": "get_user_profile"})
    turn.event({"seq": 2, "type": "tool_call_requested", "tool": "knee_surgery_tool"})

    out = debugger.stream.getvalue()
    assert "tool=get_user_profile" in out and "knee_surgery" not in out
    assert "tool=<<redacted: tool name, 17 chars>>" in out


def test_a_result_string_is_shown_by_its_key_never_by_its_shape():
    result = {"output": {"name": "ACL", "status": "PLANNED", "section": "JOHN"}}

    shown = show_tool("get_workout_plan", result)

    # a plan named in capitals is still a plan's name; the keys of Formiq's own vocabulary are shown
    assert 'status: "PLANNED"' in shown and "ACL" not in shown
    assert "<<redacted: text name, 3 chars," in shown
    assert 'section: "JOHN"' in shown  # a vocabulary key: its value comes from Formiq's own enum


def test_the_fields_a_guard_names_are_shown_only_if_declared():
    turn, debugger = turn_debug("events")
    turn.request(lambda: request_view(declarations=(("search_exercises", "Search.", SCHEMA),)))

    turn.guard("decision_validation", accepted=False, by="invalid_call", fields=["use", "exercises.0.sets", "knee_pain", "exercises.0.my_notes"])

    out = debugger.stream.getvalue()
    assert "invalid_fields=[use,exercises.0.sets] other_invalid_fields=<<redacted: 2 field name(s)>>" in out
    assert "knee_pain" not in out and "my_notes" not in out


def test_private_values_have_a_role_a_size_and_a_keyed_hash_that_is_not_the_plain_one():
    first, one = turn_debug()
    other = debugging("content")
    second = other.sink.begin("b" * 32, 5)
    text = "female"

    first.user_input(text, [])
    first.user_input(text, [])
    second.user_input(text, [])

    hashes = [line.fields.split("hmac ")[1].rstrip(">") for line in parse(one.stream.getvalue())]
    # the same value has the same hash in one run, and a short value cannot be tried out
    assert hashes[0].split(" ")[0] == hashes[1].split(" ")[0]
    plain = hashlib.sha256(text.encode()).hexdigest()[:12]
    assert plain not in one.stream.getvalue()
    # and it means nothing in another run
    assert one.sink.private_hash(text) != other.sink.private_hash(text)
    assert text not in one.stream.getvalue()


def test_control_characters_are_escaped_so_a_value_cannot_drive_the_terminal():
    turn, debugger = turn_debug("events")

    turn.note("check", tool="\x1b[31mred\x1b[0m\x07", other="a\rb")

    out = debugger.stream.getvalue()
    # no control character reaches the terminal (only the line ends do), and the value is still readable
    assert not re.search(r"[\x00-\x09\x0b-\x1f\x7f-\x9f]", out)
    assert "31mred" in out


def test_a_secret_in_a_shown_field_is_removed():
    turn, debugger = turn_debug("content", secrets=["GEMINI-KEY-CANARY-123"])

    turn.note("check", reason="GEMINI-KEY-CANARY-123 and a@b.example", token="Bearer abcdef1234567890")

    out = debugger.stream.getvalue()
    assert "CANARY" not in out and "a@b.example" not in out and "abcdef1234567890" not in out


# --- the levels, and the four markers that say why something is not shown


DECLARED = (("get_user_profile", "The profile.", {"type": "object"}),)


def request_view(instructions="PROMPT TEXT", messages=(), declarations=DECLARED, known=()):
    return RequestView(
        number=1,
        round=0,
        kind="open",
        model="model-x",
        variant="base",
        instructions=instructions,
        declarations=declarations,
        known_tools=known,
        config={"function_calling_mode": "ANY"},
        facts={"messages": len(messages)},
        messages=tuple(messages),
    )


def test_the_events_level_shows_a_constants_identity_never_its_text():
    turn, debugger = turn_debug("events")

    turn.request(lambda: request_view("A SECRET-FREE PROMPT"))

    out = debugger.stream.getvalue()
    (prompt,) = labelled(parse(out), "system_prompt")
    assert f"sha256={digest('A SECRET-FREE PROMPT')}" in prompt.fields and "chars=20" in prompt.fields
    assert "text=<<not captured: level is events>>" in prompt.fields
    assert "SECRET-FREE" not in out


def test_the_content_level_shows_a_constant_once_per_process_for_each_hash():
    turn, debugger = turn_debug("content")
    other = debugger.sink.begin("b" * 32, 6)

    turn.request(lambda: request_view("THE PROMPT TEXT"))
    turn.request(lambda: request_view("THE PROMPT TEXT"))
    other.request(lambda: request_view("THE PROMPT TEXT"))
    other.request(lambda: request_view("ANOTHER PROMPT"))

    out = debugger.stream.getvalue()
    assert out.count("THE PROMPT TEXT") == 1
    # the prompt and the declarations of the second request, of the other turn's first, and the
    # declarations of its second: each text was printed once, and is named by its hash after
    assert out.count("text=<<printed earlier in this process>>") == 2 + 2 + 1
    assert out.count("ANOTHER PROMPT") == 1


def test_the_four_markers_say_why_and_never_another_reason():
    turn, debugger = turn_debug("content", max_message_chars=40)
    parts = (
        PartView(kind="user_message", text="private words"),
        PartView(kind="function_response", name="search_exercises", call_id="c1", data={"output": {"name": "x" * 500}}),
        PartView(kind="function_response", name="get_workout_plan", call_id="c2", data={}, status="compacted", replaced={"output": {"a": 1}}),
    )

    turn.request(lambda: request_view(messages=[MessageView(0, "user", parts)]))
    turn.response(1, text=None, calls=[], usage=None, model_reported=None)

    out = debugger.stream.getvalue()
    assert "<<redacted: user message, 13 chars, hmac " in out  # private: its size and hash
    assert "<<truncated: +" in out  # a bound
    assert "<<not captured: a note replaced it before the request was sent>>" in out
    assert "thinking=<<unavailable: not requested>>" in out  # nothing to show
    assert "tokens=<<unavailable: the provider reported none>>" in out


def test_the_events_level_never_gives_a_hash_or_a_result():
    turn, debugger = turn_debug("events")
    parts = (
        PartView(kind="user_message", text="private words"),
        PartView(kind="function_response", name="get_workout_plan", call_id="c1", data=PLAN),
    )

    turn.request(lambda: request_view(messages=[MessageView(0, "user", parts)]))
    turn.user_input("private words", [("user", "more private words")])

    out = debugger.stream.getvalue()
    assert "hmac" not in out and "plan_id" not in out and "PLANNED" not in out
    assert "<<redacted: user message, 13 chars>>" in out


# --- the bounds


def test_a_message_is_cut_to_its_bound_with_a_marker():
    shown = show_tool("search_exercises", {"output": {"description": "d" * 10_000}}, max_message_chars=100)

    (line,) = [line for line in shown.splitlines() if "result=" in line]
    assert "<<truncated: +" in line and len(line) < 300 and "d" * 200 not in line
    assert MAX_MESSAGE_CHARS == 2_000


def test_a_turn_stops_printing_content_at_its_cap_and_says_so_but_still_says_what_happened():
    turn, debugger = turn_debug("content", max_turn_chars=300)

    for number in range(6):
        turn.tool(
            name="search_exercises", call_id=f"c{number}", synthesized_id=False, origin="model",
            outcome="ok", category=None, code=None, repeat="none", duration_ms=1,
            result={"output": {"description": f"{number}" * 150}},
        )  # fmt: skip

    lines = parse(debugger.stream.getvalue())
    heads = labelled(lines, "tool_result")
    assert len(heads) == 6  # what happened is always said
    bodies = [line.body[0] for line in heads]
    assert any("<<truncated: +" in body for body in bodies)
    assert any("<<not captured: the turn's content cap of 300 chars is reached>>" in body for body in bodies)
    assert MAX_TURN_CHARS == 40_000


def test_lists_keys_and_depth_are_bounded():
    deep = {"output": {"a": {"b": {"c": {"d": {"e": {"f": {"g": 1}}}}}}}}
    wide = {"output": {f"k{n}": n for n in range(60)}}
    long = {"output": {"ids": list(range(30))}}

    assert "<<truncated: +1 levels>>" in show_tool("get_workout_plan", deep)
    assert "<<truncated: +20 keys>>" in show_tool("get_workout_plan", wide)
    assert "<<truncated: +18 items>>" in show_tool("get_workout_plan", long)


def test_a_constant_is_cut_to_its_own_bound():
    turn, debugger = turn_debug("content", max_constant_chars=80)

    turn.request(lambda: request_view("P" * 500))

    (prompt,) = labelled(parse(debugger.stream.getvalue()), "system_prompt")
    assert prompt.body and "<<truncated: +" in prompt.body[-1]
    assert MAX_CONSTANT_CHARS == 40_000


# --- lines: whole, ordered, and never mixed between turns


def test_the_lines_of_turns_running_at_once_are_whole_and_each_turns_are_in_order():
    debugger = debugging("content")
    barrier = threading.Barrier(8)

    def worker(index: int) -> None:
        turn = debugger.sink.begin(f"{index:08x}" + "0" * 24, index)
        barrier.wait(10)
        for _ in range(40):
            turn.user_input("a message", [("user", "one"), ("coach", "two"), ("user", "three")])
            turn.note("tick", worker=index)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)

    lines = parse(debugger.stream.getvalue())  # a block cut in two would fail to parse
    assert len(lines) == 8 * 80
    for index in range(8):
        mine = [line for line in lines if line.tag == f"{index:08x}"]
        assert [line.seq for line in mine] == list(range(1, 81))
        assert all(len(line.body) == 3 for line in labelled(mine, "input"))


# --- the sink fails, the turn does not notice


class Flaky(io.StringIO):
    """A stream that works for the first writes, then fails with a message that holds a secret."""

    def __init__(self, working: int) -> None:
        super().__init__()
        self.working = working

    def write(self, text):
        if self.working <= 0:
            raise OSError("API_KEY_CANARY: the terminal is gone")
        self.working -= 1
        return super().write(text)


def test_a_failing_stream_fails_nothing_and_is_reported_once_by_its_type(caplog):
    stream = Flaky(working=1)  # the header is written
    sink = DebugSink("content", stream)
    turn = sink.begin("c" * 32, 1)

    with caplog.at_level(logging.WARNING, logger="app.observability.debug"):
        turn.note("one")
        turn.note("two")
        turn.request(lambda: request_view())
        turn.tool(name="x", call_id=None, synthesized_id=False, origin="model", outcome="ok",
                  category=None, code=None, repeat="none", duration_ms=None, result={})  # fmt: skip
        turn.summary(lambda: {})

    reported = [r for r in caplog.records if "Agent debug output failed" in r.getMessage()]
    assert len(reported) == 1 and "OSError" in reported[0].getMessage()
    assert "CANARY" not in caplog.text


def test_a_failing_builder_fails_nothing(caplog):
    turn, _ = turn_debug()

    with caplog.at_level(logging.WARNING, logger="app.observability.debug"):
        turn.request(lambda: 1 / 0)
        turn.summary(lambda: 1 / 0)

    assert "ZeroDivisionError" in caplog.text


def test_a_debug_output_that_cannot_start_does_not_stop_the_request(caplog):
    tracer = Tracer(RecordingBackend(), debug=DebugSink("events", Flaky(working=0)))

    with caplog.at_level(logging.WARNING, logger="app.observability.tracing"):
        with tracer.request("coach_request", request_id="r" * 32, user_id=1) as trace:
            trace.count("anything")

    assert trace.debug is None and "OSError" in caplog.text and "CANARY" not in caplog.text


def test_a_terminal_that_cannot_show_a_character_gets_it_escaped_not_an_error():
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="ascii")
    turn = DebugSink("events", stream).begin("d" * 32, 1)

    turn.note("check", tool="Soulevé de terre")
    stream.flush()

    assert "Soulev\\xe9 de terre" in raw.getvalue().decode()


# --- what the sink is, and is not


def test_the_debug_module_uses_only_the_standard_library_and_writes_no_file():
    tree = ast.parse(Path(debug_module.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}

    assert imported <= set(sys.stdlib_module_names), imported - set(sys.stdlib_module_names)
    assert "open" not in calls
    assert "FileHandler" not in Path(debug_module.__file__).read_text()


def test_the_sink_writes_to_the_streams_it_is_given_and_by_default_to_stderr(capsys):
    DebugSink("events").begin("e" * 32, 1).note("hello")

    captured = capsys.readouterr()
    assert "note" not in captured.out and "hello" in captured.err
    assert captured.out == ""


def test_the_classes_that_tag_provenance_are_plain_data():
    assert Authored("x").text == "x" and Private("y", "role").role == "role"
