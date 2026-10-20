"""AGENT_DEBUG on real turns of the coach graph (app.observability.debug,
app.agent.debug_view): that the timeline is the turn's, in order; that the
request shown is the request sent; that every refusal, retry, limit, failure and
fallback is visible; that nothing private is printed; that the turn is the same
with the debug output off, at events and at content; and that Langfuse still
receives metadata only.

The model and the tools are scripted: nothing calls Gemini, a database or the
network, and Langfuse exports to memory.
"""

import json
import logging
import re
import uuid
from unittest.mock import Mock

import httpx
import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.agent import CANNOT_ANSWER_REPLY, CoachContext, ConversationTurn, coach_graph, initial_state
from app.agent import debug_view
from app.agent import graph as graph_module
from app.agent.graph import PROPOSAL_NOT_MADE_REPLY, PendingProposal, safety_instructions
from app.agent.policy import OUT_OF_SCOPE_REPLY, SAFETY_POLICY
from app.agent.trust import REPLY_CLAIMS_CHANGE
from app.ai import AIProviderError, GeminiProvider, turn_config
from app.observability import Tracer
from app.observability.debug import DebugSink, canonical, digest
from app.tools import TOOL_DECLARATIONS
from tests.coach import FakeTools, call, fake_provider, respond_turn, tool_turn
from tests.observability import Debugging, RecordingBackend, comparable, debugging, labelled, parse
from tests.unit.test_coach_accepted_proposal_fallback import CLAIM, until_the_limit
from tests.unit.test_coach_proposal_budget import MISSING_CORE, READS, propose, proposal_tools
from tests.unit.test_coach_reply_duration import MESSAGE, PROPOSED_26
from tests.unit.test_reliability_observability import langfuse
from tests.unit.test_reliability_state import SCENARIOS, ScenarioModel, outcome

USER = 7
REQUEST_ID = "3f9a1c2b4d5e6f708192a3b4c5d6e7f8"
TAG = REQUEST_ID[:8]

PROFILE = {
    "output": {
        "user_id": USER,
        "profile": {
            "first_name": "Zainab-CANARY",
            "last_name": "Qureshi-CANARY",
            "age": 987654321,
            "height_cm": 171.25,
            "weight_kg": 71.5,
            "gender": "female-CANARY",
            "goal": "ACL-REHAB-CANARY",
        },
    }
}
PLAN = {
    "output": {
        "plan_id": 12,
        "name": "PLAN-NAME-CANARY",
        "status": "PLANNED",
        "exercises": [
            {
                "exercise_name": "Goblet Squat",
                "section": "MAIN_WORKOUT",
                "sets": 3,
                "reps": 10,
                "weight_kg": 20.5,
                "notes": "KNEE-INJURY-NOTE-CANARY",
            }
        ],
    }
}


@pytest.fixture(autouse=True)
def loggers_enabled(monkeypatch):
    """Alembic's logging setup disables the loggers that exist once the integration
    tests' migrations ran: these tests read what the debug output logs of its own
    failures, so their loggers are enabled again."""
    for name in ("app.observability.debug", "app.observability.tracing", "app.agent.debug_view"):
        monkeypatch.setattr(logging.getLogger(name), "disabled", False)


class Tools(FakeTools):
    """Formiq's tool declarations, with scripted results."""

    declarations = TOOL_DECLARATIONS


def answers(item):
    return {"get_user_profile": PROFILE, "get_workout_plan": PLAN}.get(
        item.name, {"output": {"tool": item.name}}
    )


def scripted():
    """The model reads the profile and a plan, then answers from them."""
    return fake_provider(
        tool_turn(call("get_user_profile"), call("get_workout_plan", plan_id=12)),
        respond_turn("Plan 12 fits your goal.", "ADAPTATION", "RETRIEVE_THEN_ANSWER"),
    )


def run_turn(
    provider, tools, message, history=(), *, debugger=None, level="content", request_id=REQUEST_ID, **context
):
    """One turn through the graph with the debug output, ended as the coach
    service ends it. The state, the trace and the debugger."""
    debugger = debugger or debugging(level)
    with debugger.tracer.request("coach_request", request_id=request_id, user_id=USER) as trace:
        trace.debug.user_input(message, [(turn.role, turn.text) for turn in history])
        state = coach_graph.invoke(
            initial_state(message, history),
            context=CoachContext(user_id=USER, provider=provider, tools=tools, trace=trace, **context),
        )
        trace.trajectory.finish("success")
        trace.debug.summary(trace.trajectory.summary)
    return state, trace, debugger


def lines_of(debugger: Debugging):
    return parse(debugger.stream.getvalue())


def request_blocks(lines):
    """Each model request's lines: the `request` line and what follows it up to the
    model's response."""
    blocks, current = [], None
    for line in lines:
        if line.label == "request":
            current = [line]
            blocks.append(current)
        elif line.label == "response":
            current = None
        elif current is not None:
            current.append(line)
    return blocks


def sent_to_the_model(provider, index):
    return provider.generate_turn.call_args_list[index].args[0]


# --- default off


def test_with_the_debug_output_off_nothing_is_printed_or_built(capsys, caplog, monkeypatch):
    def forbidden(**fields):
        raise AssertionError("a debug view was built while debugging was off")

    monkeypatch.setattr(debug_view, "request_view", forbidden)
    tracer = Tracer(RecordingBackend())

    with caplog.at_level(logging.DEBUG):
        with tracer.request("coach_request", request_id=REQUEST_ID, user_id=USER) as trace:
            state = coach_graph.invoke(
                initial_state("Does plan 12 fit my goal?"),
                context=CoachContext(user_id=USER, provider=scripted(), tools=Tools(answers), trace=trace),
            )

    assert trace.debug is None
    assert state["final_response"] == "Plan 12 fits your goal."
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", "")
    assert "agent turn" not in caplog.text and "app.observability.debug" not in caplog.text


# --- ordered events, correlated


def test_the_timeline_is_the_trajectorys_events_in_their_order():
    _, trace, debugger = run_turn(scripted(), Tools(answers), "Does plan 12 fit my goal?", level="events")

    lines = lines_of(debugger)
    events = [line for line in lines if line.fields.startswith("ev=")]
    assert [line.label for line in events] == [e["type"] for e in trace.trajectory.events]
    assert [int(line.fields.split()[0][3:]) for line in events] == [e["seq"] for e in trace.trajectory.events]
    # the turn from its start to its end, each stage in its place
    labels = [line.label for line in lines]
    for earlier, later in [
        ("turn_started", "input"),
        ("input", "safety_check"),
        ("safety_check", "model_request_started"),
        ("model_request_started", "request"),
        ("request", "model_request_completed"),
        ("model_request_completed", "response"),
        ("response", "tool_call_requested"),
        ("tool_call_executed", "tool_result"),
        ("tool_result", "decision_validation"),
        ("decision_validation", "reply_validation"),
        ("reply_validation", "response_source"),
        ("response_source", "turn_completed"),
        ("turn_completed", "summary"),
    ]:
        assert labels.index(earlier) < labels.index(later), (earlier, later)


def test_every_line_has_the_turns_id_a_sequence_that_only_grows_and_the_elapsed_time():
    _, _, debugger = run_turn(scripted(), Tools(answers), "Does plan 12 fit my goal?", level="events")

    output = debugger.stream.getvalue()
    lines = parse(output)
    assert output.splitlines()[0] == f"=== agent turn {REQUEST_ID} | user {USER} | AGENT_DEBUG=events ==="
    assert {line.tag for line in lines} == {TAG}
    assert [line.seq for line in lines] == list(range(1, len(lines) + 1))
    assert [line.ms for line in lines] == sorted(line.ms for line in lines)


def test_turns_are_told_apart_by_their_ids():
    debugger = debugging("events")
    other = "9e8d7c6b" + "0" * 24

    run_turn(scripted(), Tools(answers), "Does plan 12 fit my goal?", debugger=debugger)
    run_turn(scripted(), Tools(answers), "Does plan 12 fit my goal?", debugger=debugger, request_id=other)

    lines = lines_of(debugger)
    for tag in (TAG, "9e8d7c6b"):
        mine = [line for line in lines if line.tag == tag]
        assert [line.seq for line in mine] == list(range(1, len(mine) + 1)) and mine


# --- the request shown is the request sent


def test_the_context_shown_is_the_context_sent_message_by_message():
    provider = scripted()
    history = [ConversationTurn("user", "I train at home"), ConversationTurn("coach", "Noted")]

    _, _, debugger = run_turn(provider, Tools(answers), "Does plan 12 fit my goal?", history)

    blocks = request_blocks(lines_of(debugger))
    assert len(blocks) == 2
    for number, block in enumerate(blocks):
        sent = sent_to_the_model(provider, number)
        rows = [line for line in block if line.label.startswith("context[")]
        assert [line.label for line in rows] == [f"context[{i}]" for i in range(len(sent))]
        assert [line.fields for line in rows] == [
            f"role={content.role} parts={len(content.parts)}" for content in sent
        ]
        # the calls and their results, each with the id it is sent with
        for row, content in zip(rows, sent, strict=True):
            for body, part in zip(row.body, content.parts, strict=True):
                if part.function_call:
                    assert f"name={part.function_call.name} id={part.function_call.id}" in body
                if part.function_response:
                    assert f"name={part.function_response.name} id={part.function_response.id}" in body


def test_the_history_and_the_current_message_are_separate_parts_with_their_own_sizes_and_hashes():
    provider = scripted()
    history = [ConversationTurn("user", "I train at home"), ConversationTurn("coach", "Noted")]
    message = "Does plan 12 fit my goal?"

    _, _, debugger = run_turn(provider, Tools(answers), message, history)

    first = sent_to_the_model(provider, 0)[0]
    (context, current) = [part.text for part in first.parts]
    (row,) = [line for line in lines_of(debugger) if line.label == "context[0]"][:1]
    hash_of = debugger.sink.private_hash
    assert row.fields == "role=user parts=2"
    assert row.body[0] == (
        f"part 0 history: <<redacted: history block, {len(context)} chars, hmac {hash_of(context)}>> "
        "turns=[user,coach] omitted=0"
    )
    assert row.body[1] == (
        f"part 1 user_message: <<redacted: user message, {len(message)} chars, hmac {hash_of(message)}>>"
    )
    assert current == message


def test_without_a_history_the_message_is_alone():
    provider = scripted()

    _, _, debugger = run_turn(provider, Tools(answers), "Does plan 12 fit my goal?")

    row = [line for line in lines_of(debugger) if line.label == "context[0]"][0]
    assert row.fields == "role=user parts=1" and row.body[0].startswith("part 0 user_message:")


def test_what_the_model_returned_is_shown_with_its_call_ids():
    provider = scripted()

    _, _, debugger = run_turn(provider, Tools(answers), "Does plan 12 fit my goal?")

    first, second = labelled(lines_of(debugger), "response")
    assert first.fields.startswith("request=1 ") and " calls=2 " in first.fields
    assert "call[0] name=get_user_profile id=call-" in first.body[0] and "args={}" in first.body[0]
    assert "args={plan_id: 12}" in first.body[1]
    assert second.body[0].startswith("call[0] name=respond id=call-")
    assert "intent: \"ADAPTATION\"" in second.body[0] and "reply: <<redacted: text reply," in second.body[0]


def test_a_call_the_provider_gave_no_id_is_shown_with_one_made_from_its_name():
    first = tool_turn(call("get_user_profile"))
    nameless = type(first)(
        content=first.content,
        tool_calls=tuple(type(c)(name=c.name, arguments=c.arguments, id=None) for c in first.tool_calls),
    )
    provider = fake_provider(nameless, respond_turn("Hi.", "GENERAL_FITNESS", "ANSWER"))

    _, _, debugger = run_turn(provider, Tools(answers), "What is my goal?")

    response = labelled(lines_of(debugger), "response")[0]
    assert "id=get_user_profile-0 (synthesized)" in response.body[0]


# --- the prompt: its identity always, its text once per process at content


def test_the_prompt_variant_and_hash_are_those_of_the_text_the_model_was_sent():
    provider = scripted()
    _, _, debugger = run_turn(provider, Tools(answers), "Does plan 12 fit my goal?", level="events")

    sent = provider.generate_turn.call_args_list[0].kwargs["instructions"]
    (prompt, *_) = labelled(lines_of(debugger), "system_prompt")
    assert prompt.fields.startswith(f"variant=base chars={len(sent)} sha256={digest(sent)}")

    # a proposal awaiting approval adds its note: another variant, another hash
    provider = scripted()
    pending = PendingProposal(expires_in_minutes=20, revises_plan_id=3)
    _, _, debugger = run_turn(
        provider, Tools(answers), "Does plan 12 fit my goal?", level="events",
        pending_proposal=pending, proposal_awaiting_approval=True,
    )  # fmt: skip
    sent_pending = provider.generate_turn.call_args_list[0].kwargs["instructions"]
    (prompt, *_) = labelled(lines_of(debugger), "system_prompt")
    assert sent_pending != sent and sent_pending.endswith(graph_module.pending_note(pending))
    assert prompt.fields.startswith(f"variant=pending-note chars={len(sent_pending)} sha256={digest(sent_pending)}")


def test_a_flagged_request_is_the_safety_variant_with_its_category():
    provider = fake_provider(
        respond_turn(
            "I can't advise on that. Please see a physiotherapist; gentle walking is fine.",
            "SAFETY_SENSITIVE",
            "SAFE_REDIRECT",
        )
    )

    _, _, debugger = run_turn(
        provider, Tools(answers), "I have sharp knee pain when I squat. Should I push through it?", level="events"
    )

    sent = provider.generate_turn.call_args_list[0].kwargs["instructions"]
    lines = lines_of(debugger)
    (prompt,) = labelled(lines, "system_prompt")
    assert prompt.fields.startswith(f"variant=safety/PAIN_OR_INJURY chars={len(sent)} sha256={digest(sent)}")
    assert sent == safety_instructions(SAFETY_POLICY["PAIN_OR_INJURY"])
    (check,) = labelled(lines, "safety_check")
    assert "flagged=true category=PAIN_OR_INJURY" in check.fields and "tool_calls_allowed=false" in check.fields


def test_the_prompts_text_is_exactly_what_was_sent_and_printed_once_per_process(monkeypatch):
    monkeypatch.setattr(
        graph_module, "COACH_INSTRUCTIONS", f"{graph_module.COACH_INSTRUCTIONS} PROMPT-TEXT-CANARY"
    )
    debugger = debugging("content")
    first, second = scripted(), scripted()

    run_turn(first, Tools(answers), "Does plan 12 fit my goal?", debugger=debugger)
    run_turn(second, Tools(answers), "Does plan 12 fit my goal?", debugger=debugger, request_id="1" * 32)

    sent = first.generate_turn.call_args_list[0].kwargs["instructions"]
    prompts = labelled(lines_of(debugger), "system_prompt")
    # four requests, one printing: the text exactly as the model was sent it
    assert debugger.stream.getvalue().count("PROMPT-TEXT-CANARY") == 1
    assert [p.fields.endswith("text=below") for p in prompts] == [True, False, False, False]
    assert "\n".join(prompts[0].body) == sent
    assert all(f"sha256={digest(sent)}" in p.fields for p in prompts)
    assert all(p.fields.endswith("text=<<printed earlier in this process>>") for p in prompts[1:])


def test_the_events_level_prints_the_identity_of_the_prompt_never_its_text(monkeypatch):
    monkeypatch.setattr(
        graph_module, "COACH_INSTRUCTIONS", f"{graph_module.COACH_INSTRUCTIONS} PROMPT-TEXT-CANARY"
    )

    _, _, debugger = run_turn(scripted(), Tools(answers), "Does plan 12 fit my goal?", level="events")

    output = debugger.stream.getvalue()
    assert "PROMPT-TEXT-CANARY" not in output and "You are Formiq" not in output
    assert "text=<<not captured: level is events>>" in output


def test_the_declarations_and_the_configuration_are_those_the_provider_is_sent():
    provider = scripted()
    _, _, debugger = run_turn(provider, Tools(answers), "Does plan 12 fit my goal?", level="content")

    kwargs = provider.generate_turn.call_args_list[0].kwargs
    lines = lines_of(debugger)
    (declarations, *_) = labelled(lines, "tool_declarations")
    names = [tool.name for tool in kwargs["tools"]]
    expected = canonical(
        [{"name": t.name, "description": t.description, "parameters": t.parameters} for t in kwargs["tools"]]
    )
    assert f"names=[{','.join(names)}]" in declarations.fields
    assert f"sha256={digest(expected)}" in declarations.fields and f"chars={len(expected)}" in declarations.fields
    assert declarations.body[0].startswith(f"- {names[0]}: ")
    (config, *_) = labelled(lines, "model_config")
    assert "function_calling_mode=ANY" in config.fields
    assert f"allowed_function_names=[{','.join(kwargs['required_tool_names'])}]" in config.fields
    assert "automatic_function_calling=disabled" in config.fields
    assert 'generation_settings="none set: the model\'s defaults apply"' in config.fields
    assert "config_fields_set=[system_instruction,tools,tool_config,automatic_function_calling]" in config.fields


def test_the_configuration_described_is_the_configuration_the_provider_builds():
    provider = scripted()
    run_turn(provider, Tools(answers), "Does plan 12 fit my goal?", level="events")
    kwargs = provider.generate_turn.call_args_list[0].kwargs
    # the graph asks for nothing beyond these, so the view's own call to turn_config matches
    assert set(kwargs) == {"instructions", "tools", "required_tool_names"}
    described = turn_config(kwargs["instructions"], kwargs["tools"], True, kwargs["required_tool_names"])

    real = GeminiProvider("not-a-real-key", "model", timeout_seconds=1)
    real._client = Mock()
    real._client.models.generate_content.side_effect = RuntimeError("stop here")
    with pytest.raises(AIProviderError):
        real.generate_turn([], **kwargs)

    sent = real._client.models.generate_content.call_args.kwargs["config"]
    assert sent.model_dump() == described.model_dump()
    assert not [name for name in type(sent).model_fields if getattr(sent, name) is not None and name not in
                {"system_instruction", "tools", "tool_config", "automatic_function_calling"}]


# --- tools, guards, retries and limits


def run_scripted(*turns, tools=None, message="Does plan 12 fit my goal?", level="content", **context):
    provider = fake_provider(*turns)
    state, trace, debugger = run_turn(provider, tools or Tools(answers), message, level=level, **context)
    return state, trace, debugger, provider


def test_a_tool_that_fails_shows_its_code_and_category_and_never_its_message():
    failing = Tools(
        lambda item: {"error": {"code": "RESOURCE_NOT_FOUND", "message": "no plan 12 TOOLMSG-CANARY"}}
    )

    _, _, debugger, _ = run_scripted(
        tool_turn(call("get_workout_plan", plan_id=12)),
        respond_turn("I can't read that plan.", "WORKOUT_PLAN", "CANNOT_ANSWER"),
        tools=failing,
        message="What is in plan 12?",
    )

    (result,) = labelled(lines_of(debugger), "tool_result")
    assert "outcome=error category=ownership_failure error_code=RESOURCE_NOT_FOUND" in result.fields
    assert 'code: "RESOURCE_NOT_FOUND"' in result.body[0] and "<<redacted: tool message," in result.body[0]
    assert "TOOLMSG-CANARY" not in debugger.stream.getvalue()


def test_a_refused_write_an_unknown_id_and_a_repeated_search_are_blocked_and_say_why():
    _, _, debugger, _ = run_scripted(
        tool_turn(call("cancel_workout_plan", plan_id=1)),
        tool_turn(call("get_workout_plan", plan_id=999)),
        tool_turn(call("search_exercises", use="MAIN_WORKOUT")),
        tool_turn(call("search_exercises", use="MAIN_WORKOUT")),
        respond_turn("I can't do that.", "GENERAL_FITNESS", "ANSWER"),
        message="Delete my plan",
    )

    results = labelled(lines_of(debugger), "tool_result")
    outcomes = [(r.fields.split()[0], "outcome=blocked" in r.fields, re.search(r"category=(\S+)", r.fields).group(1)) for r in results]
    assert outcomes == [
        ("name=cancel_workout_plan", True, "write_not_authorized"),
        ("name=get_workout_plan", True, "id_not_grounded"),
        ("name=search_exercises", False, "-"),
        ("name=search_exercises", True, "duplicate_call"),
    ]
    assert "repeat=unchanged" in results[3].fields
    assert "neither the user nor a tool gave this id" not in debugger.stream.getvalue()


def test_a_refused_decision_shows_who_refused_it_why_and_that_the_model_was_asked_again():
    _, _, debugger, provider = run_scripted(
        respond_turn("Your goal is fat loss.", "PROFILE", "RETRIEVE_THEN_ANSWER"),
        tool_turn(call("get_user_profile")),
        respond_turn("Your goal is fat loss.", "PROFILE", "RETRIEVE_THEN_ANSWER"),
        message="What is my goal?",
    )

    lines = lines_of(debugger)
    rejected, accepted = labelled(lines, "decision_validation")
    assert "accepted=false by=decision_policy" in rejected.fields
    assert rejected.body[0].startswith("rejection: a PROFILE answer needs data that get_user_profile returned")
    assert re.fullmatch(
        r'respond: \{intent: "PROFILE", decision: "RETRIEVE_THEN_ANSWER", '
        r"reply: <<redacted: text reply, 22 chars, hmac \w{12}>>\}",
        rejected.body[1],
    )
    (returned,) = labelled(lines, "rejection_returned_to_model")
    assert "iteration=0 iteration_limit=5 round_kind=open model_asked_again=true" in returned.fields
    assert "accepted=true" in accepted.fields and "decision=RETRIEVE_THEN_ANSWER" in accepted.fields
    # the model was in fact asked again
    assert provider.generate_turn.call_count == 3
    labels = [line.label for line in lines]
    assert labels.index("rejection_returned_to_model") < labels.index("model_request_started", labels.index("rejection_returned_to_model"))


def test_a_refused_reply_shows_its_reason_and_formiqs_words_for_it_never_the_reply():
    claim = "I've updated your workout plan."

    _, _, debugger, _ = run_scripted(
        respond_turn(claim, "GENERAL_FITNESS", "ANSWER"),
        respond_turn("Progressive overload means doing a little more over time.", "GENERAL_FITNESS", "ANSWER"),
        message="What is progressive overload?",
    )

    rejected, accepted = labelled(lines_of(debugger), "reply_validation")
    assert "accepted=false reason=change_claim" in rejected.fields
    assert rejected.body == [f"rejection: {REPLY_CLAIMS_CHANGE}"]
    assert "accepted=true" in accepted.fields
    assert claim not in debugger.stream.getvalue()


def test_a_respond_call_that_is_not_valid_shows_the_fields_it_names_not_its_text():
    bad = tool_turn(call("respond", intent="GENERAL_FITNESS", **{"EXTRA-KEY-NAME-CANARY": 1}))

    _, _, debugger, _ = run_scripted(
        bad, respond_turn("Hi.", "GENERAL_FITNESS", "ANSWER"), message="Hello"
    )

    (invalid, _) = labelled(lines_of(debugger), "decision_validation")
    assert "accepted=false by=invalid_call" in invalid.fields
    assert "invalid_fields=[decision,reply]" in invalid.fields
    assert "other_invalid_fields=<<redacted: 1 field name(s)>>" in invalid.fields
    assert "EXTRA-KEY-NAME-CANARY" not in debugger.stream.getvalue()


def test_a_turn_that_reaches_its_limit_says_so_and_who_wrote_the_reply():
    refused = respond_turn("Your goal is fat loss.", "PROFILE", "RETRIEVE_THEN_ANSWER")

    state, _, debugger, provider = run_scripted(*[refused] * 6, message="What is my goal?")

    lines = lines_of(debugger)
    assert provider.generate_turn.call_count == 6
    last = labelled(lines, "rejection_returned_to_model")[-1]
    assert "iteration=5 iteration_limit=5 round_kind=decision model_asked_again=false" in last.fields
    (termination,) = labelled(lines, "termination")
    assert termination.fields == "reason=retry_limit_reached"
    (source,) = labelled(lines, "response_source")
    assert source.fields.startswith("source=generic_fallback detail=retry_limit")
    assert source.body == [CANNOT_ANSWER_REPLY] == [state["final_response"]]


def test_a_provider_failure_shows_its_category_and_never_its_text():
    error = AIProviderError("the model request failed")
    error.__cause__ = httpx.TimeoutException("API_KEY_CANARY: timed out")
    debugger = debugging("content")

    with pytest.raises(AIProviderError):
        run_turn(fake_provider(error), Tools(answers), "What is my goal?", debugger=debugger)

    lines = lines_of(debugger)
    (failure,) = labelled(lines, "provider_error")
    assert "category=provider_timeout" in failure.fields and "outcome=error" in failure.fields
    assert "CANARY" not in debugger.stream.getvalue()


def test_a_request_over_its_budget_is_not_sent_and_says_so():
    state, _, debugger, provider = run_scripted(
        respond_turn("Hi.", "GENERAL_FITNESS", "ANSWER"), message="Hello", max_context_chars=10
    )

    lines = lines_of(debugger)
    (fit,) = labelled(lines, "context_fit")
    assert "budget=10" in fit.fields and "fits=false" in fit.fields
    assert [line.fields for line in labelled(lines, "termination")] == ["reason=context_budget_exceeded"]
    assert not labelled(lines, "request") and provider.generate_turn.call_count == 0
    (source,) = labelled(lines, "response_source")
    assert source.fields.startswith("source=generic_fallback detail=context_budget")
    assert state["final_response"] == CANNOT_ANSWER_REPLY


def test_compaction_shows_the_original_results_apart_from_the_ones_a_note_replaced():
    debugger = debugging("content")

    result = outcome(SCENARIOS["B"], tracer=debugger.tracer)

    lines = lines_of(debugger)
    fits = [line for line in labelled(lines, "context_fit") if "compacted_results=1" in line.fields]
    assert fits and "compaction_count=1" in fits[0].fields
    rows = [body for line in lines if line.label.startswith("context[") for body in line.body]
    compacted = [row for row in rows if "status=compacted" in row]
    original = [row for row in rows if "status=original" in row]
    assert compacted and original
    assert all("replaced_chars=" in row and "replaced_hmac=" in row for row in compacted)
    assert all("<<not captured: a note replaced it before the request was sent>>" in row for row in compacted)
    assert all("chars=" in row for row in original)
    assert result["final_response"] == "Plan 12 has one exercise."


def test_the_accepted_proposal_card_fallback_is_visible_as_what_it_is():
    state, trace, debugger = run_turn(
        until_the_limit(CLAIM), proposal_tools(PROPOSED_26), MESSAGE
    )

    lines = lines_of(debugger)
    (source,) = labelled(lines, "response_source")
    assert source.fields.startswith("source=card_fallback detail=accepted_proposal")
    assert source.body == [state["final_response"]]  # Formiq's own words, from the card
    assert [line.fields for line in labelled(lines, "termination")] == ["reason=retry_limit_reached"]
    refused = [line for line in labelled(lines, "reply_validation") if "accepted=false" in line.fields]
    assert refused and all("reason=change_claim" in line.fields for line in refused)
    # the model's refused wording is never shown
    output = debugger.stream.getvalue()
    assert CLAIM not in output and "squat variation" not in output


def test_every_kind_of_reply_says_who_wrote_it():
    def source_of(provider, tools, message, **context):
        _, _, debugger = run_turn(provider, tools, message, level="content", **context)
        return labelled(lines_of(debugger), "response_source")[-1]

    model = source_of(scripted(), Tools(answers), "Does plan 12 fit my goal?")
    assert model.fields.startswith("source=model detail=decision_accepted reply=<<redacted: model reply, 23 chars,")
    assert model.body == [] and "Plan 12 fits your goal." not in model.fields

    redirect = source_of(
        fake_provider(respond_turn("Paris.", "OUT_OF_SCOPE", "CANNOT_ANSWER")), Tools(answers), "Who won the world cup?"
    )
    assert redirect.fields.startswith("source=generic_fallback detail=out_of_scope_redirect")
    assert redirect.body == [OUT_OF_SCOPE_REPLY]

    flagged = "I have sharp knee pain when I squat. Should I push through it?"
    safe = source_of(
        fake_provider(
            respond_turn("I can't advise on that. Please see a physiotherapist; gentle walking is fine.", "SAFETY_SENSITIVE", "SAFE_REDIRECT")
        ),
        Tools(answers),
        flagged,
    )
    assert safe.fields.startswith("source=model detail=decision_accepted")

    fallback = source_of(fake_provider(tool_turn(call("get_user_profile"))), Tools(answers), flagged)
    assert fallback.fields.startswith("source=safety_fallback detail=tools_requested")
    assert fallback.body == [SAFETY_POLICY["PAIN_OR_INJURY"].fallback_reply]

    nothing = source_of(
        fake_provider(
            tool_turn(*(call(name) for name in READS), call("search_exercises", use="MAIN_WORKOUT")),
            tool_turn(propose(10, 11)),
            *[respond_turn(CLAIM, "WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER")] * 6,
        ),
        proposal_tools(MISSING_CORE),
        MESSAGE,
    )
    assert nothing.fields.startswith("source=generic_fallback detail=nothing_proposed")
    assert nothing.body == [PROPOSAL_NOT_MADE_REPLY]


def test_the_summary_says_how_the_turn_ended_with_its_tokens_and_time():
    provider = scripted()
    turns = list(provider.generate_turn.side_effect)
    usage = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
    provider.generate_turn.side_effect = [
        type(turn)(content=turn.content, tool_calls=turn.tool_calls, usage=usage, model="model-001")
        for turn in turns
    ]

    _, _, debugger = run_turn(provider, Tools(answers), "Does plan 12 fit my goal?", level="events")

    lines = lines_of(debugger)
    (summary,) = labelled(lines, "summary")
    assert "status=success termination=decision_accepted" in summary.fields
    assert "model_requests=2 tool_calls_requested=2 tool_calls_executed=2" in summary.fields
    assert "tokens_total=240 tokens_source=provider_reported" in summary.fields
    first = labelled(lines, "response")[0]
    assert "model_reported=model-001" in first.fields
    assert "tokens=input_tokens=100 output_tokens=20 total_tokens=120" in first.fields
    assert re.search(r"latency_turn_ms=\d+", summary.fields)


# --- nothing private is printed, at any level


CANARIES = (
    "GEMINI-KEY-CANARY-123456",
    "JWT-SECRET-CANARY-123456",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiI5OTkifQ.c2lnbmF0dXJlLWNhbmFyeQ",
    "canary.person@example.com",
    "+44 20 7946 0958",
    "555-123-4567",
    "Zainab-CANARY",
    "Qureshi-CANARY",
    "female-CANARY",
    "ACL-REHAB-CANARY",
    "KNEE-INJURY-NOTE-CANARY",
    "PLAN-NAME-CANARY",
    "MESSAGE-WORDS-CANARY",
    "HISTORY-WORDS-CANARY",
    "REPLY-WORDS-CANARY",
    "ARGUMENT-WORDS-CANARY",
    "RESULT-WORDS-CANARY",
    "0123456789abcdef0123456789abcdef",
    "987654321",
    "171.25",
)


def canary_turn(level, **sink_options):
    """A turn in which every kind of private value appears where it can: the message,
    the history, the model's reply and arguments, and what the tools return."""
    leaky = {
        "get_user_profile": PROFILE,
        "get_workout_plan": {
            "output": {
                **PLAN["output"],
                "free_text": "RESULT-WORDS-CANARY canary.person@example.com +44 20 7946 0958 555-123-4567",
                "proposal_id": "0123456789abcdef0123456789abcdef",
                "binding": "b" * 64,
                "token": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiI5OTkifQ.c2lnbmF0dXJlLWNhbmFyeQ",
            }
        },
    }
    provider = fake_provider(
        tool_turn(
            call("get_user_profile"),
            call("get_workout_plan", plan_id=12, note="ARGUMENT-WORDS-CANARY GEMINI-KEY-CANARY-123456"),
        ),
        respond_turn(
            "REPLY-WORDS-CANARY: Zainab-CANARY, plan 12 fits. JWT-SECRET-CANARY-123456 canary.person@example.com",
            "ADAPTATION",
            "RETRIEVE_THEN_ANSWER",
        ),
    )
    debugger = debugging(
        level, secrets=["GEMINI-KEY-CANARY-123456", "JWT-SECRET-CANARY-123456"], **sink_options
    )
    history = [
        ConversationTurn("user", "HISTORY-WORDS-CANARY my number is 555-123-4567"),
        ConversationTurn("coach", "Noted, Zainab-CANARY."),
    ]
    message = (
        "MESSAGE-WORDS-CANARY: does plan 12 fit my goal? my key is GEMINI-KEY-CANARY-123456, "
        "my token is eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiI5OTkifQ.c2lnbmF0dXJlLWNhbmFyeQ, "
        "write to canary.person@example.com or call +44 20 7946 0958"
    )
    run_turn(provider, Tools(lambda item: leaky.get(item.name, {"output": {}})), message, history, debugger=debugger)
    return debugger


@pytest.mark.parametrize("level", ["events", "content"])
def test_no_secret_identity_profile_value_note_or_contact_detail_is_ever_printed(level):
    debugger = canary_turn(level)

    output = debugger.stream.getvalue()
    for canary in CANARIES:
        assert canary not in output, canary
    # the user's own words, the model's and every private field are redacted, not omitted
    assert "<<redacted:" in output


def test_the_content_level_shows_the_safe_data_the_private_fields_sit_beside():
    output = canary_turn("content").stream.getvalue()

    for shown in ("plan_id: 12", 'status: "PLANNED"', 'exercise_name: "Goblet Squat"', "sets: 3", "reps: 10"):
        assert shown in output
    for redacted in ("field profile", "field weight_kg", "field notes", "field binding", "field proposal_id", "field token"):
        assert f"<<redacted: {redacted}," in output
    assert "text free_text" in output
    # the model's own extra argument is not in the tool's schema: its name is not said either
    assert "<<redacted: key, 4 chars>>: <<redacted: field, " in output


def test_a_failed_provider_call_prints_no_text_of_the_error_or_the_message():
    error = AIProviderError("the model request failed")
    error.__cause__ = httpx.ConnectError("GEMINI-KEY-CANARY-123456 canary.person@example.com")
    debugger = debugging("content", secrets=["GEMINI-KEY-CANARY-123456"])

    with pytest.raises(AIProviderError):
        run_turn(fake_provider(error), Tools(answers), "MESSAGE-WORDS-CANARY", debugger=debugger)

    output = debugger.stream.getvalue()
    assert "CANARY" not in output and "canary.person" not in output


# --- the turn is the same with the debug output off, at events and at content


@pytest.fixture
def seen_by_the_model(monkeypatch):
    """Everything each model request is given: its contents, instructions, tools
    and how it must call them, exactly."""
    seen = []
    original = ScenarioModel.generate_turn

    def recording(self, contents, **kwargs):
        seen.append(
            (repr(contents), kwargs["instructions"], repr(kwargs["tools"]), kwargs.get("required_tool_names"), sorted(kwargs))
        )
        return original(self, contents, **kwargs)

    monkeypatch.setattr(ScenarioModel, "generate_turn", recording)
    return seen


def run_scenario(name, tracer, seen):
    seen.clear()
    result = outcome(SCENARIOS[name], tracer=tracer)
    return result, list(seen)


@pytest.mark.parametrize("name", sorted(SCENARIOS))
@pytest.mark.parametrize("level", ["events", "content"])
def test_the_model_is_sent_exactly_the_same_and_the_turn_ends_the_same_with_debugging_on(
    name, level, seen_by_the_model
):
    off, off_seen = run_scenario(name, Tracer(), seen_by_the_model)

    on = debugging(level)
    shown, shown_seen = run_scenario(name, on.tracer, seen_by_the_model)

    assert on.stream.getvalue()  # it did print
    assert shown_seen == off_seen  # contents, instructions, tools, tool configuration
    assert shown == off  # the final state, the decision, the messages, what was sent


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_a_debug_output_that_fails_halfway_changes_nothing(name, seen_by_the_model):
    from tests.unit.test_agent_debug_sink import Flaky

    off, off_seen = run_scenario(name, Tracer(), seen_by_the_model)

    broken = Tracer(debug=DebugSink("content", Flaky(working=1)))
    broken_result, broken_seen = run_scenario(name, broken, seen_by_the_model)

    assert broken_seen == off_seen and broken_result == off


def normalized(text):
    """The text without the ids the fixtures count up from run to run."""
    return re.sub(r"(call|proposal)-\d+", r"\1-N", text)


def test_the_card_fallback_turn_is_the_same_with_debugging_on():
    def card_turn(tracer):
        provider = until_the_limit(CLAIM)
        with tracer.request("coach_request", request_id=uuid.uuid4().hex, user_id=USER) as trace:
            state = coach_graph.invoke(
                initial_state(MESSAGE),
                context=CoachContext(user_id=USER, provider=provider, tools=proposal_tools(PROPOSED_26), trace=trace),
            )
            trace.trajectory.finish("success")
        sent = [normalized(repr(c.args[0])) for c in provider.generate_turn.call_args_list]
        instructions = [c.kwargs["instructions"] for c in provider.generate_turn.call_args_list]
        return state["final_response"], state["decision"], sent, instructions, comparable(trace.trajectory.metadata())

    off = card_turn(Tracer(RecordingBackend()))
    for level in ("events", "content"):
        assert card_turn(debugging(level).tracer) == off


# --- Langfuse is still sent metadata only


def exported_to_langfuse(debug_on):
    """What the real Langfuse tracer exports for one turn, with the debug output on
    or not (it prints to its own stream either way)."""
    exporter = InMemorySpanExporter()
    configured = langfuse(exporter)
    debugger = debugging("content", secrets=["GEMINI-KEY-CANARY-123456"])
    tracer = Tracer(
        configured.backend,
        capture_content=configured.capture_content,
        debug=debugger.sink if debug_on else None,
    )
    provider = fake_provider(respond_turn("REPLY-WORDS-CANARY", "GENERAL_FITNESS", "ANSWER"))
    with tracer.request("coach_request", request_id=uuid.uuid4().hex, user_id=USER) as trace:
        coach_graph.invoke(
            initial_state("MESSAGE-WORDS-CANARY", [ConversationTurn("user", "HISTORY-WORDS-CANARY")]),
            context=CoachContext(user_id=USER, provider=provider, tools=Tools(answers), trace=trace),
        )
        trace.trajectory.finish("success")
    configured.backend.client.flush()
    spans = list(exporter.get_finished_spans())
    configured.shutdown()
    return spans, debugger, configured


def test_langfuse_still_receives_metadata_only_while_the_debug_output_prints_content():
    spans, debugger, configured = exported_to_langfuse(True)
    plain_spans, _, _ = exported_to_langfuse(False)

    assert debugger.stream.getvalue().count("<<redacted:") >= 3  # the debug output did print
    exported = json.dumps([dict(span.attributes) for span in spans], default=repr)
    for forbidden in (
        "MESSAGE-WORDS-CANARY", "HISTORY-WORDS-CANARY", "REPLY-WORDS-CANARY",
        "You are Formiq", "hmac", "agent turn", "<<redacted", "<<not captured",
    ):  # fmt: skip
        assert forbidden not in exported
    # no input or output of any step was exported: only metadata
    assert not [key for span in spans for key in span.attributes if key.rsplit(".", 1)[-1] in {"input", "output"}]
    # and what is exported has the same shape as without the debug output: the same spans,
    # carrying the same attributes
    shape = lambda found: sorted((span.name, tuple(sorted(span.attributes))) for span in found)  # noqa: E731
    assert shape(spans) == shape(plain_spans)
    assert configured.capture_content is False


def test_the_debug_output_does_not_turn_content_capture_on_for_any_backend():
    debugger = debugging("content")
    built = []

    with debugger.tracer.request("coach_request", request_id=REQUEST_ID, user_id=USER) as trace:
        trace.content(input=lambda: built.append("built"), output="MESSAGE-WORDS-CANARY")
        with trace.child("step") as step:
            step.content(input=lambda: built.append("built"))

    assert built == []  # nothing was built for a backend: capture is the tracer's own setting
    assert not [sent for sent in debugger.backend.sent if sent[0] == "content"]
    assert "MESSAGE-WORDS-CANARY" not in debugger.backend.everything()
    assert debugger.tracer.capture_content is False


def test_what_the_recording_backend_receives_is_the_same_with_the_debug_output_on():
    def spans(tracer, backend):
        with tracer.request("coach_request", request_id=uuid.uuid4().hex, user_id=USER) as trace:
            coach_graph.invoke(
                initial_state("Does plan 12 fit my goal?"),
                context=CoachContext(user_id=USER, provider=scripted(), tools=Tools(answers), trace=trace),
            )
            trace.trajectory.finish("success")
            trace.finish("success", **trace.trajectory.metadata())
        return [
            (node.name, node.kind, node.level, node.status_message, sorted(node.metadata))
            for node in backend.nodes
        ], comparable(backend.root.metadata)

    plain_backend = RecordingBackend()
    on = debugging("content")

    assert spans(on.tracer, on.backend) == spans(Tracer(plain_backend), plain_backend)
