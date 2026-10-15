"""The trajectory of one coach turn: how the agent reached its answer.

The trace tree (app.observability.tracing) says which steps ran. This module
says what happened across them, in order, in terms a reader can count and
compare: the model requests and what each cost, the tools requested, executed,
blocked and failed, why a proposal was refused, whether a retry round was used
and rescued the turn, and where the time went. The graph records into one
TurnRecorder per request (RunTrace.trajectory); at the end the recorder gives

- summary(): the machine-readable per-turn summary (SCHEMA), events included;
- metadata(): the same aggregates as flat, safe trace metadata, for the root of
  the Langfuse trace and the playground, with the events as short codes;
- aggregate(): medians, p90s and rates over many summaries, each with its
  denominator, for a QA pass.

Only safe fields are ever recorded: names, counts, categories, durations, token
counts and the model's name, never a message, an argument's value, a result, a
reply or a user. Recording never changes the turn: every method here is guarded,
so a failing recorder is logged by its type and the coach carries on.

Counting rules, which the summary states by name:

- requested: calls the model asked for (the respond call is a decision, not a
  tool call). executed: calls that reached a tool and ran, Formiq's own reads
  included (loaded). blocked: calls Formiq refused before they ran (a gate of
  the graph, or the per-turn limit). failed: executed calls whose result is an
  error. Never a blocked call among the executed.
- tokens are what Gemini reported for each request, never estimated; a total
  adds up only the requests that reported it, and says how many did.
"""

import json
import logging
import statistics
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from functools import wraps
from typing import Any, ParamSpec, TypeVar

logger = logging.getLogger(__name__)

SCHEMA = "formiq.turn_summary/1"
# events kept for one turn; a turn makes at most 7 model requests of at most 20
# calls, so this is never reached by a legal turn
MAX_EVENTS = 160
# the events a trace's metadata carries, as short codes (see Event.code)
MAX_TRAJECTORY_CODES = 64

# the proposal outcomes of a turn, from Formiq's own state
PROPOSAL_NOT_ATTEMPTED = "not_attempted"
PROPOSAL_CREATED = "created"
PROPOSAL_NOT_CREATED = "not_created"
# accepted by Formiq, but the turn did not end with an answer, so it was not kept or shown
PROPOSAL_DISCARDED = "discarded"
# no new proposal: the one awaiting approval was read and shown again
PROPOSAL_SHOWN_PENDING = "shown_pending"

# what a retry round ended with
RETRY_RECOVERED = "recovered"
RETRY_REJECTED_AGAIN = "rejected_again"
RETRY_DECIDED = "decided"


class EventType(StrEnum):
    TURN_STARTED = "turn_started"
    MODEL_REQUEST_STARTED = "model_request_started"
    MODEL_REQUEST_COMPLETED = "model_request_completed"
    TOOL_CALL_REQUESTED = "tool_call_requested"
    TOOL_CALL_EXECUTED = "tool_call_executed"
    TOOL_CALL_BLOCKED = "tool_call_blocked"
    TOOL_EXECUTION_FAILED = "tool_execution_failed"
    PROPOSAL_VALIDATION_REJECTED = "proposal_validation_rejected"
    RETRY_ROUND_STARTED = "retry_round_started"
    RETRY_ROUND_COMPLETED = "retry_round_completed"
    PROPOSAL_CREATED = "proposal_created"
    PROPOSAL_NOT_CREATED = "proposal_not_created"
    PROPOSAL_APPROVED = "proposal_approved"
    TURN_COMPLETED = "turn_completed"
    PROVIDER_ERROR = "provider_error"
    # beyond the list above: the checks of the model's decision and reply, each a
    # model request that may have to be made again
    DECISION_REJECTED = "decision_rejected"
    REPLY_REJECTED = "reply_rejected"


# short codes for the events, for the trace's list of strings
_CODES = {
    EventType.TURN_STARTED: "start",
    EventType.MODEL_REQUEST_STARTED: "req",
    EventType.MODEL_REQUEST_COMPLETED: "req_done",
    EventType.TOOL_CALL_REQUESTED: "call",
    EventType.TOOL_CALL_EXECUTED: "ran",
    EventType.TOOL_CALL_BLOCKED: "blocked",
    EventType.TOOL_EXECUTION_FAILED: "failed",
    EventType.PROPOSAL_VALIDATION_REJECTED: "prop_rejected",
    EventType.RETRY_ROUND_STARTED: "retry",
    EventType.RETRY_ROUND_COMPLETED: "retry_done",
    EventType.PROPOSAL_CREATED: "prop_created",
    EventType.PROPOSAL_NOT_CREATED: "prop_none",
    EventType.PROPOSAL_APPROVED: "prop_approved",
    EventType.TURN_COMPLETED: "done",
    EventType.PROVIDER_ERROR: "provider_error",
    EventType.DECISION_REJECTED: "decision_rejected",
    EventType.REPLY_REJECTED: "reply_rejected",
}

_P = ParamSpec("_P")
_R = TypeVar("_R")


def _guarded(method: Callable[_P, _R]) -> Callable[_P, _R | None]:
    """A recording method that cannot fail the turn: an exception is logged by
    its type (a message could hold data) and the method returns None."""

    @wraps(method)
    def guarded(*args: _P.args, **kwargs: _P.kwargs) -> _R | None:
        try:
            return method(*args, **kwargs)
        except Exception as error:  # noqa: BLE001 - observability must not fail the turn
            logger.warning(
                "Recording the turn's trajectory (%s) failed (%s); the turn goes on",
                method.__name__,
                type(error).__name__,
            )
            return None

    return guarded


def _ms(seconds: float | None) -> int | None:
    return None if seconds is None else round(seconds * 1000)


def _safe(value: Any) -> Any:
    """A value fit for an event: a primitive, a string cut short."""
    if isinstance(value, str):
        return value[:100]
    if value is None or isinstance(value, bool | int | float):
        return value
    return str(value)[:100]


class TurnRecorder:
    """The ordered, safe record of one coach turn (see the module docstring)."""

    def __init__(self, turn_id: str) -> None:
        self.turn_id = turn_id
        self._clock = time.perf_counter
        self._began = self._clock()
        self.began_at = datetime.now(UTC)
        self.events: list[dict[str, Any]] = []
        self.dropped_events = 0
        self.model: str | None = None
        self.requests: list[dict[str, Any]] = []
        self.calls: list[dict[str, Any]] = []
        self.batches: list[dict[str, Any]] = []
        self.validations: list[dict[str, Any]] = []
        self.rounds: dict[int, str] = {}
        self.retry: dict[str, Any] | None = None
        self.proposal_attempts = 0
        self.proposal_rejections = 0
        self.missing_prerequisites = 0
        self.proposal_accepted_request: int | None = None
        self.proposal_outcome = PROPOSAL_NOT_ATTEMPTED
        self.proposal_ref: str | None = None
        self.complete: bool | None = None
        self.failures: list[str] = []
        self.status: str | None = None
        self.termination: str | None = None
        self.intent: str | None = None
        self.decision: str | None = None
        self.turn_ms: int | None = None
        self.event(EventType.TURN_STARTED)

    # --- events

    def _elapsed_ms(self) -> int:
        return round((self._clock() - self._began) * 1000)

    @_guarded
    def event(self, type: EventType, **fields: Any) -> None:
        """Appends one event: its sequence number, timestamp and the safe fields."""
        if len(self.events) >= MAX_EVENTS:
            self.dropped_events += 1
            return
        event: dict[str, Any] = {
            "seq": len(self.events) + 1,
            "type": str(type),
            "at": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "t_ms": self._elapsed_ms(),
        }
        event.update({name: _safe(value) for name, value in fields.items() if value is not None})
        self.events.append(event)

    def fail(self, category: str) -> None:
        """A normalized reason the turn went less well (kept once, in order)."""
        category = str(category)
        if category not in self.failures:
            self.failures.append(category)

    # --- the model's requests

    @_guarded
    def model_request_started(
        self, *, round: int, kind: str, offered: int, model: str | None = None
    ) -> int:
        """A model request begins; its number (from 1)."""
        self.model = self.model or model
        self.rounds.setdefault(round, kind)
        self.requests.append(
            {"round": round, "kind": kind, "offered_tools": offered, "usage": None,
             "model_reported": None, "duration_ms": None, "status": "started"}
        )  # fmt: skip
        number = len(self.requests)
        self.event(
            EventType.MODEL_REQUEST_STARTED, round=round, request=number, kind=kind, offered_tools=offered
        )
        return number

    @_guarded
    def model_request_completed(
        self,
        number: int,
        *,
        duration_ms: int,
        usage: Mapping[str, int] | None,
        model_reported: str | None,
        requested_calls: int,
        responded: bool,
    ) -> None:
        record = self.requests[number - 1]
        counts = {k: v for k, v in (usage or {}).items() if isinstance(v, int) and v >= 0}
        record.update(
            usage=counts or None, model_reported=model_reported, duration_ms=duration_ms,
            status="completed", requested_calls=requested_calls, responded=responded,
        )  # fmt: skip
        self.event(
            EventType.MODEL_REQUEST_COMPLETED,
            round=record["round"], request=number, duration_ms=duration_ms,
            outcome="ok", requested_calls=requested_calls, responded=responded,
            usage_available=bool(counts), tokens_total=counts.get("total_tokens"),
        )  # fmt: skip

    @_guarded
    def provider_error(self, number: int | None, *, category: str, duration_ms: int) -> None:
        """A model request failed: the provider's error or its broken output, by category."""
        if number is not None:
            self.requests[number - 1].update(duration_ms=duration_ms, status="failed")
        self.fail(category)
        self.event(
            EventType.PROVIDER_ERROR,
            round=None if number is None else self.requests[number - 1]["round"],
            request=number, duration_ms=duration_ms, outcome="error", category=category,
        )  # fmt: skip

    # --- retry rounds

    @_guarded
    def retry_round_started(self, *, round: int, request: int | None) -> None:
        self.retry = {"round": round, "outcome": None, "started": self._clock()}
        self.event(EventType.RETRY_ROUND_STARTED, round=round, request=request)

    @_guarded
    def retry_round_completed(self, *, round: int, outcome: str) -> None:
        if self.retry is None or self.retry["outcome"] is not None:
            return
        self.retry["outcome"] = outcome
        self.retry["duration_ms"] = _ms(self._clock() - self.retry.pop("started"))
        self.event(
            EventType.RETRY_ROUND_COMPLETED, round=round, outcome=outcome,
            duration_ms=self.retry["duration_ms"],
        )  # fmt: skip

    # --- tools

    @_guarded
    def tool_batch(self, *, round: int, duration_ms: int, calls: int, origin: str = "model") -> None:
        """One run of the tools: how long it took, in all (the tools time each
        call too, when they say so)."""
        self.batches.append({"round": round, "duration_ms": duration_ms, "calls": calls, "origin": origin})

    @_guarded
    def tool_call(
        self,
        *,
        round: int,
        tool: str,
        origin: str,
        repeat: str,
        executed: bool,
        error_code: str | None,
        category: str | None,
        duration_ms: int | None,
        request: int | None = None,
        accepted_proposal: bool = False,
    ) -> None:
        """One tool call, as it ended. Always a requested event (the model's own
        calls), then exactly one of executed, failed or blocked: never a blocked
        call among the executed."""
        failed = executed and error_code is not None
        blocked = not executed
        self.calls.append(
            {"round": round, "tool": tool, "origin": origin, "repeat": repeat, "executed": executed,
             "failed": failed, "blocked": blocked, "category": category,
             "duration_ms": duration_ms, "proposal": tool == "propose_workout_plan"}
        )  # fmt: skip
        if origin == "model":
            self.event(
                EventType.TOOL_CALL_REQUESTED, round=round, request=request, tool=tool,
                origin=origin, repeat=repeat if repeat != "none" else None,
            )  # fmt: skip
        outcome = "blocked" if blocked else "error" if failed else "ok"
        kind = (
            EventType.TOOL_CALL_BLOCKED if blocked
            else EventType.TOOL_EXECUTION_FAILED if failed
            else EventType.TOOL_CALL_EXECUTED
        )  # fmt: skip
        self.event(
            kind, round=round, tool=tool, origin=origin, outcome=outcome, category=category,
            duration_ms=duration_ms, repeat=repeat if repeat != "none" else None,
        )  # fmt: skip
        if category:
            self.fail(category)
        if tool == "propose_workout_plan":
            self.proposal_attempts += origin == "model"
            if accepted_proposal and self.proposal_accepted_request is None:
                self.proposal_accepted_request = request
            elif category:
                self.proposal_rejections += 1
                self.missing_prerequisites += category == "missing_prerequisite"
                self.event(
                    EventType.PROPOSAL_VALIDATION_REJECTED, round=round, category=category,
                    outcome="rejected", repeat=repeat if repeat != "none" else None,
                )  # fmt: skip

    # --- the checks of the model's decision and reply

    @_guarded
    def validation(
        self, kind: str, *, round: int, accepted: bool, reason: str | None, duration_ms: int
    ) -> None:
        """A decision or reply check (kind "decision" or "reply"), and its cost."""
        self.validations.append({"kind": kind, "round": round, "accepted": accepted, "duration_ms": duration_ms})
        if not accepted:
            self.event(
                EventType.DECISION_REJECTED if kind == "decision" else EventType.REPLY_REJECTED,
                round=round, outcome="rejected", category=reason, duration_ms=duration_ms,
            )  # fmt: skip
            self.fail(f"{kind}_rejected")

    # --- the end

    @_guarded
    def proposal(
        self,
        outcome: str,
        *,
        proposal_ref: str | None = None,
        complete: bool | None = None,
        missing_regions: Sequence[str] = (),
    ) -> None:
        """The turn's proposal outcome, from Formiq's state at its end: created
        (kept for the user's approval and shown), not created (tried, none
        accepted), discarded (accepted, but not shown), shown pending (the one
        awaiting approval, again), or not attempted."""
        self.proposal_outcome = outcome
        self.proposal_ref = proposal_ref
        self.complete = complete
        if outcome == PROPOSAL_CREATED:
            self.event(
                EventType.PROPOSAL_CREATED, proposal_ref=proposal_ref, complete=complete,
                missing_regions=",".join(missing_regions)[:100] or None,
            )  # fmt: skip
        elif outcome in (PROPOSAL_NOT_CREATED, PROPOSAL_DISCARDED):
            self.event(EventType.PROPOSAL_NOT_CREATED, outcome=outcome)

    @_guarded
    def finish(
        self, status: str, *, termination: str | None = None, intent: str | None = None,
        decision: str | None = None,
    ) -> None:  # fmt: skip
        """The turn ends: its status and how it ended."""
        self.status = status
        self.termination = termination or self.termination
        self.intent = intent or self.intent
        self.decision = decision or self.decision
        self.turn_ms = self._elapsed_ms()
        self.event(
            EventType.TURN_COMPLETED, outcome=status, termination=self.termination,
            duration_ms=self.turn_ms, completed=self.completed,
        )  # fmt: skip

    @property
    def completed(self) -> bool:
        """Whether the user got an answer: a success, or a question, not a failure
        or a "cannot answer"."""
        return self.status in ("success", "clarification")

    # --- reading it

    def _tokens(self) -> dict[str, Any]:
        """The turn's tokens, summed over the requests that reported them (each
        request's own counts stay in the summary, so the total can be audited)."""
        fields = {
            "input": "input_tokens", "output": "output_tokens", "cached_input": "cached_input_tokens",
            "reasoning": "reasoning_tokens", "tool_use_input": "tool_use_input_tokens",
            "total": "total_tokens",
        }  # fmt: skip
        reported = [r for r in self.requests if r["usage"]]
        totals = {
            name: (sum(r["usage"][key] for r in reported if key in r["usage"])
                   if any(key in r["usage"] for r in reported) else None)
            for name, key in fields.items()
        }  # fmt: skip
        source = (
            "unavailable" if not reported
            else "provider_reported" if len(reported) == len(self.requests)
            else "partial"
        )  # fmt: skip
        through = None
        if self.proposal_accepted_request is not None:
            upto = self.requests[: self.proposal_accepted_request]
            through_totals = [r["usage"]["total_tokens"] for r in upto if r["usage"] and "total_tokens" in r["usage"]]
            through = sum(through_totals) if len(through_totals) == len(upto) else None
        return {
            **totals, "source": source, "requests_reporting": len(reported),
            "requests_total": len(self.requests), "through_proposal_total": through,
            "estimated": False,
        }  # fmt: skip

    def _tool_counts(self) -> dict[str, Any]:
        model = [c for c in self.calls if c["origin"] == "model"]
        executed = [c for c in self.calls if c["executed"]]
        by_tool: dict[str, dict[str, int]] = {}
        for call in self.calls:
            row = by_tool.setdefault(call["tool"], {"requested": 0, "executed": 0, "blocked": 0, "failed": 0})
            row["requested"] += call["origin"] == "model"
            row["executed"] += call["executed"]
            row["blocked"] += call["blocked"]
            row["failed"] += call["failed"]
        lookups = [c for c in model if c["tool"] in ("search_exercises", "get_exercise")]
        per_round = Counter(c["round"] for c in model)
        failed = sum(c["failed"] for c in executed)
        return {
            "requested": len(model),
            "executed": len(executed),
            "blocked": sum(c["blocked"] for c in self.calls),
            "failed": failed,
            "formiq_loaded": sum(c["origin"] == "formiq" for c in self.calls),
            "by_tool": by_tool,
            "per_round": [per_round.get(r, 0) for r in sorted(self.rounds)],
            "duplicates_blocked": sum(c["category"] == "duplicate_call" for c in model),
            "repeated_lookups": sum(c["repeat"] != "none" for c in lookups),
            "retries_after_changed_evidence": sum(
                c["repeat"] == "evidence_changed" and c["executed"] for c in model
            ),
            "success_rate": None if not executed else round((len(executed) - failed) / len(executed), 4),
            "success_rate_denominator": "executed",
        }

    def _latency(self) -> dict[str, Any]:
        measured = [c["duration_ms"] for c in self.calls if c["executed"] and c["duration_ms"] is not None]
        batch_ms = sum(b["duration_ms"] for b in self.batches)
        asked = [(r["duration_ms"], n) for n, r in enumerate(self.requests, 1) if r["duration_ms"] is not None]
        slowest = max(asked, default=None)
        proposals = [c["duration_ms"] for c in self.calls if c["proposal"] and c["executed"] and c["duration_ms"] is not None]
        return {
            "turn": self.turn_ms if self.turn_ms is not None else self._elapsed_ms(),
            "model_requests": [r["duration_ms"] for r in self.requests],
            "model_total": sum(d for d, _ in asked),
            "slowest_request": None if slowest is None else slowest[1],
            "slowest_request_ms": None if slowest is None else slowest[0],
            "tool_calls": measured,
            "tool_batches": [b["duration_ms"] for b in self.batches],
            "tool_total": batch_ms,
            "proposal_validation": proposals,
            "decision_reply_validation": sum(v["duration_ms"] for v in self.validations),
            "retry_round": None if self.retry is None else self.retry.get("duration_ms"),
            # Each model request is attempted once: no automatic retry, no backoff.
            "provider_retries": 0,
            "provider_backoff": 0,
        }

    def _budget(self) -> dict[str, Any]:
        limited = any(c["category"] == "tool_limit_reached" for c in self.calls)
        out_of_rounds = self.termination in (
            "retry_limit_reached", "context_budget_exceeded", "compaction_limit_exceeded"
        )
        reason = (
            "tool_limit" if limited else self.termination if out_of_rounds else None
        )
        return {
            "exhausted": limited or out_of_rounds,
            "reason": reason,
            "rounds_used": len(self.rounds),
            "model_requests": len(self.requests),
        }

    def summary(self) -> dict[str, Any]:
        """The per-turn summary (SCHEMA): everything above, as plain data."""
        tokens = self._tokens()
        retry = self.retry or {}
        return {
            "schema": SCHEMA,
            "turn_id": self.turn_id,
            "started_at": self.began_at.isoformat(timespec="milliseconds"),
            "model": self.model,
            "models_reported": sorted({r["model_reported"] for r in self.requests if r["model_reported"]}),
            "status": self.status,
            "request_completed": self.completed,
            "termination": self.termination,
            "intent": self.intent,
            "decision": self.decision,
            "proposal": {
                "outcome": self.proposal_outcome,
                "attempts": self.proposal_attempts,
                "rejections": self.proposal_rejections,
                "missing_prerequisites": self.missing_prerequisites,
                "accepted_in_request": self.proposal_accepted_request,
                "complete": self.complete,
                "proposal_ref": self.proposal_ref,
            },
            "model_requests": len(self.requests),
            "tool_calls": self._tool_counts(),
            "validation": {
                "decision_rejections": sum(v["kind"] == "decision" and not v["accepted"] for v in self.validations),
                "reply_rejections": sum(v["kind"] == "reply" and not v["accepted"] for v in self.validations),
            },
            "retry_round": {
                "entered": self.retry is not None,
                "outcome": retry.get("outcome") if self.retry else None,
                "recovered": None if self.retry is None else retry.get("outcome") == RETRY_RECOVERED,
            },
            "budget": self._budget(),
            "failure_reasons": list(self.failures),
            "tokens": tokens,
            "tokens_per_request": [
                {"request": n, "round": r["round"], "model_reported": r["model_reported"],
                 "available": bool(r["usage"]), **(r["usage"] or {})}
                for n, r in enumerate(self.requests, 1)
            ],
            "latency_ms": self._latency(),
            "events": list(self.events),
            "events_dropped": self.dropped_events,
        }  # fmt: skip

    def codes(self) -> list[str]:
        """The events as short strings, in order: "seq:code:tool:category:ms"."""
        codes = []
        for event in self.events[:MAX_TRAJECTORY_CODES]:
            parts = [str(event["seq"]), _CODES[EventType(event["type"])]]
            parts += [str(event[k]) for k in ("tool", "category", "outcome") if event.get(k)][:2]
            if event.get("duration_ms") is not None:
                parts.append(f"{event['duration_ms']}ms")
            codes.append(":".join(parts))
        return codes

    def metadata(self) -> dict[str, Any]:
        """The summary's aggregates as flat, safe trace metadata (primitives and
        short lists of them): the same numbers, none of the events but their codes."""
        summary = self.summary()
        calls, tokens, latency = summary["tool_calls"], summary["tokens"], summary["latency_ms"]
        proposal, retry, budget = summary["proposal"], summary["retry_round"], summary["budget"]
        return {
            "summary_schema": SCHEMA,
            "model": summary["model"],
            "models_reported": summary["models_reported"],
            "request_completed": summary["request_completed"],
            "tool_calls_requested": calls["requested"],
            "tool_calls_executed": calls["executed"],
            "tool_calls_blocked": calls["blocked"],
            "tool_calls_failed": calls["failed"],
            "tool_calls_loaded": calls["formiq_loaded"],
            "tool_success_rate": calls["success_rate"],
            "tool_success_denominator": calls["success_rate_denominator"],
            "tool_counts": [
                f"{name}:{row['requested']}/{row['executed']}/{row['blocked']}/{row['failed']}"
                for name, row in sorted(calls["by_tool"].items())
            ],
            "tool_calls_per_round": calls["per_round"],
            "duplicate_calls_blocked": calls["duplicates_blocked"],
            "repeated_lookups": calls["repeated_lookups"],
            "retries_after_changed_evidence": calls["retries_after_changed_evidence"],
            "proposal_outcome": proposal["outcome"],
            "proposal_attempts": proposal["attempts"],
            "proposal_rejections": proposal["rejections"],
            "missing_prerequisites": proposal["missing_prerequisites"],
            "proposal_complete": proposal["complete"],
            "retry_rounds_entered": int(retry["entered"]),
            "retry_rounds_recovered": int(bool(retry["recovered"])),
            "retry_round_outcome": retry["outcome"],
            "budget_exhausted": budget["exhausted"],
            "budget_reason": budget["reason"],
            "failure_reasons": summary["failure_reasons"],
            "tokens_input": tokens["input"],
            "tokens_output": tokens["output"],
            "tokens_cached_input": tokens["cached_input"],
            "tokens_reasoning": tokens["reasoning"],
            "tokens_total": tokens["total"],
            "tokens_source": tokens["source"],
            "tokens_requests_reporting": tokens["requests_reporting"],
            "tokens_through_proposal": tokens["through_proposal_total"],
            "latency_turn_ms": latency["turn"],
            "latency_model_ms": latency["model_total"],
            "latency_tool_ms": latency["tool_total"],
            "latency_decision_reply_validation_ms": latency["decision_reply_validation"],
            "latency_retry_round_ms": latency["retry_round"],
            "latency_slowest_request": latency["slowest_request"],
            "model_request_ms": [d if d is not None else -1 for d in latency["model_requests"]],
            "trajectory": self.codes(),
            "trajectory_events": len(self.events) + self.dropped_events,
        }

    def log_summary(self) -> None:
        """The summary as one structured log line (the log is the QA's record
        when Langfuse is off): only safe fields, so nothing here is private."""
        try:
            logger.info("coach_turn_summary %s", json.dumps(self.summary(), separators=(",", ":")))
        except Exception as error:  # noqa: BLE001 - observability must not fail the turn
            logger.warning("Logging the turn summary failed (%s)", type(error).__name__)


# --- events outside a turn

def log_proposal_approved(*, proposal_ref: str, plan_id: int | None = None) -> None:
    """The user approved a proposal: a structured log line, not part of a coach
    turn (the approval is its own request, and keeps no turn id)."""
    try:
        logger.info(
            "coach_event %s",
            json.dumps(
                {
                    "schema": "formiq.event/1",
                    "type": str(EventType.PROPOSAL_APPROVED),
                    "at": datetime.now(UTC).isoformat(timespec="milliseconds"),
                    "proposal_ref": proposal_ref[:8],
                    "plan_saved": plan_id is not None,
                },
                separators=(",", ":"),
            ),
        )
    except Exception as error:  # noqa: BLE001 - observability must not fail an approval
        logger.warning("Logging the approval failed (%s)", type(error).__name__)


# --- many turns

def percentile(values: Iterable[float], p: float) -> float | None:
    """The p-th percentile by the nearest-rank method (the smallest value with at
    least p percent of the values at or below it); None for no values."""
    ordered = sorted(values)
    if not ordered:
        return None
    rank = max(1, -(-len(ordered) * p // 100))
    return ordered[int(rank) - 1]


def _stats(values: Sequence[float]) -> dict[str, Any]:
    return {
        "n": len(values),
        "median": statistics.median(values) if values else None,
        "p90": percentile(values, 90),
        "max": max(values, default=None),
    }


def _rate(hits: int, total: int, denominator: str) -> dict[str, Any]:
    return {"n": hits, "of": total, "rate": None if not total else round(hits / total, 4), "denominator": denominator}


def aggregate(summaries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Medians, p90s and rates over many turn summaries, each with its sample
    count and what it is a rate of. Turns of different models are reported
    together but flagged (models): do not compare across them."""
    turns = list(summaries)
    sought = [t for t in turns if t["proposal"]["attempts"] > 0]
    made = [t for t in sought if t["proposal"]["outcome"] == PROPOSAL_CREATED]
    entered = [t for t in turns if t["retry_round"]["entered"]]
    requests = [ms for t in turns for ms in t["latency_ms"]["model_requests"] if ms is not None]
    tools = [ms for t in turns for ms in t["latency_ms"]["tool_calls"]]
    per_turn = lambda getter: [v for t in turns if (v := getter(t)) is not None]  # noqa: E731
    reported = [t for t in turns if t["tokens"]["source"] != "unavailable"]
    return {
        "turns": len(turns),
        "models": sorted({m for t in turns for m in ([t["model"]] if t["model"] else [])}),
        "models_reported": sorted({m for t in turns for m in t["models_reported"]}),
        "latency_ms": {
            "turn": _stats(per_turn(lambda t: t["latency_ms"]["turn"])),
            "model_request": _stats(requests),
            "tool_execution": _stats(tools),
        },
        "per_turn": {
            "model_requests": _stats(per_turn(lambda t: t["model_requests"])),
            "tool_calls_requested": _stats(per_turn(lambda t: t["tool_calls"]["requested"])),
            "tool_calls_executed": _stats(per_turn(lambda t: t["tool_calls"]["executed"])),
            "tool_calls_blocked": _stats(per_turn(lambda t: t["tool_calls"]["blocked"])),
            "tokens_input": _stats(per_turn(lambda t: t["tokens"]["input"])),
            "tokens_output": _stats(per_turn(lambda t: t["tokens"]["output"])),
            "tokens_total": _stats(per_turn(lambda t: t["tokens"]["total"])),
        },
        "tokens": {
            "turns_reporting": len(reported),
            "of": len(turns),
            "estimated": False,
            "total_per_created_proposal": _stats(
                per_turn(lambda t: t["tokens"]["total"] if t in made else None)
            ),
            "total_through_proposal": _stats(
                per_turn(lambda t: t["tokens"]["through_proposal_total"] if t in made else None)
            ),
        },
        "proposal_success": _rate(len(made), len(sought), "turns that asked for a proposal"),
        "retry_round_use": _rate(len(entered), len(turns), "all turns"),
        "retry_round_success": _rate(
            sum(bool(t["retry_round"]["recovered"]) for t in entered),
            len(entered),
            "turns that entered the retry round",
        ),
        "duplicate_calls": _rate(
            sum(t["tool_calls"]["duplicates_blocked"] > 0 for t in turns), len(turns), "all turns"
        ),
        "validation_rejections": _rate(
            sum(
                t["proposal"]["rejections"] + t["validation"]["decision_rejections"]
                + t["validation"]["reply_rejections"] > 0
                for t in turns
            ),
            len(turns),
            "all turns",
        ),
        "tool_success": _rate(
            sum(t["tool_calls"]["executed"] - t["tool_calls"]["failed"] for t in turns),
            sum(t["tool_calls"]["executed"] for t in turns),
            "executed tool calls",
        ),
        "request_completed": _rate(sum(t["request_completed"] for t in turns), len(turns), "all turns"),
        "failure_reasons": dict(Counter(r for t in turns for r in t["failure_reasons"])),
    }
