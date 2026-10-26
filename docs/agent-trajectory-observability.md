# Agent trajectory observability

How to explain a coach turn: not only whether it succeeded, but which model requests ran and what
they cost, which tools were requested, executed, blocked or failed and why, whether a retry round
was used and rescued the turn, and where the time went. The code is `backend/app/observability/trajectory.py`;
the graph and `CoachService` record into it; `backend/tests/unit/test_coach_trajectory.py` and
`backend/tests/integration/test_coach_trajectory.py` prove it. The guarantees about what may be
recorded are in `docs/agent-production-contract.md` section 9.

## Where it appears

| Where | What | When |
|---|---|---|
| `TurnRecorder.summary()` | the full per-turn summary (`formiq.turn_summary/1`), events included | always: kept in memory for the turn, with tracing on or off |
| trace root (Langfuse, in memory in tests) | the same aggregates as flat metadata, the events as short codes | tracing on |
| one log line `coach_turn_summary {json}` (logger `app.observability.trajectory`, INFO) | the full summary | the playground prints it to its console; an application logs it at INFO |
| playground `X-Playground-Execution` header | the flat aggregates and the codes | the local playground |
| one log line `coach_event {json}` | `proposal_approved` | an approval that saved a plan |

No API response changes: a user is never shown any of this.

## Counting rules

- **requested**: calls the model asked for. The `respond` call is a decision, not a tool call.
- **executed**: calls that reached a tool and ran, and were not refused for the per-turn limit.
  Formiq's own reads (**loaded**, below) are included and tagged `origin: "formiq"`.
- **blocked**: calls Formiq refused before they ran: a gate of the graph (a duplicate, an id nobody
  gave, a write, a proposal before its reads) or the tools' per-turn limit. **Never a blocked call
  among the executed.** Requested + loaded = executed + blocked.
- **failed**: executed calls whose result is an error. A read of the user's own record that found
  none (no plan, no workout, no profile yet: the three reads of a proposal for a new user) is
  **empty**, not failed: the tool did its job.
- **tool success rate** = (executed - failed) / executed. The denominator is named in the summary
  (`success_rate_denominator`).
- A model request and a tool call are different counts: one request may carry several calls
  (`per_round` lists the calls requested in each round).

## Events

Each event has `seq` (from 1), `type`, `at` (UTC, ms), `t_ms` (since the turn began) and, where they
apply: `round`, `request`, `tool`, `origin` (`model` or `formiq`), `outcome`, `category`,
`duration_ms`, `repeat`.

| Type | Meaning |
|---|---|
| `turn_started` | the request began |
| `model_request_started` / `_completed` | one model request, its round, kind (`open`, `proposal_retry`, `decision`), tokens available |
| `tool_call_requested` | the model asked for the call (`repeat` says if it is a repeat) |
| `tool_call_executed` | it ran (`outcome` `ok`, or `empty`) |
| `tool_execution_failed` | it ran and returned an error (`category`) |
| `tool_call_blocked` | Formiq refused it before it ran (`category`) |
| `proposal_validation_rejected` | a proposal was refused, with its `category` |
| `retry_round_started` / `_completed` | the one extra round, and how it ended (`recovered`, `rejected_again`, `decided`) |
| `proposal_created` / `proposal_not_created` | from Formiq's state at the end: kept for approval and shown, or tried and not kept (`outcome` `not_created`, `discarded`) |
| `proposal_approved` | the user's approval saved a plan (its own log line: an approval is a separate request, joined to its turn by the 8-character `proposal_ref`) |
| `turn_completed` | status, termination, `completed` (the user got an answer) |
| `provider_error` | a model request failed (`category`: `provider_timeout`, `rate_limit`, `provider_error`, `model_output_invalid`, ...) |
| `decision_rejected`, `reply_rejected` | beyond the list the brief asked for: each is a model request that may have to be made again; `category` says why |

`repeat` is `none`, `unchanged` (an identical call ran and came back, or was refused before with
nothing since changing the evidence) or `evidence_changed` (it was refused before it ran, and a read
or an id has come since: the call is allowed to run).

### Categories (`Failure`, stable values)

`duplicate_call` (an unchanged duplicate), `id_not_grounded`, `tool_validation_error` (invalid
arguments), `missing_prerequisite`, `proposal_rejected_correctable`, `proposal_rejected_irrecoverable`,
`proposal_limit` (a second proposal in a turn, not run: not a rejection of the workout, and not
counted in `proposal.rejections`), `tool_limit_reached` and `budget_exhausted` (the budget), `provider_timeout`, `rate_limit`,
`provider_error`, `model_output_invalid`, `tool_error`, `ownership_failure` (not found, or another
user's: not told apart), `write_not_authorized` (policy), `decision_rejected`, `reply_rejected`.
`retry after changed evidence` is not a failure: it is the `repeat` value above.

## An example

A proposal made before the plan and the last workout were read (the live QA's failure), as the graph
records it with a scripted model (`1:start` is the first event; the model asked for four calls and
Formiq made two reads of its own):

```
1:start
2:req                                    request 1, round 0
3:req_done:ok:0ms
4:call:get_user_profile                  the model's calls
5:ran:get_user_profile:ok
6:call:search_exercises
7:ran:search_exercises:ok
8:req                                    request 2, round 1
9:req_done:ok:0ms
10:call:propose_workout_plan             a proposal before its reads
11:blocked:propose_workout_plan:missing_prerequisite
12:prop_rejected:missing_prerequisite:rejected
13:ran:get_current_workout_plan:ok       Formiq's own reads, handed to the model
14:ran:get_latest_workout_session:ok
15:req                                   request 3, round 2
16:req_done:ok:0ms
17:call:propose_workout_plan             the same proposal again: the evidence changed
18:ran:propose_workout_plan:ok
19:req                                   request 4: the answer
20:req_done:ok:0ms
21:done:success:12ms
```

and the summary's counts for it: `tool_calls.requested` 4, `executed` 5, `blocked` 1, `formiq_loaded` 2,
`retries_after_changed_evidence` 1, `proposal.rejections` 1, `proposal.missing_prerequisites` 1,
`failure_reasons` `["missing_prerequisite"]`. In a coach turn the service then adds
`proposal_created` (with the proposal's 8-character reference and whether it is complete) once the
proposal is kept in PostgreSQL.

What it answers: *why was the proposal rejected* (event 12, `missing_prerequisite`); *was the retry
allowed because the evidence changed* (event 17, `repeat: evidence_changed`); *which request took
longest* (`latency_ms.slowest_request`); *how many calls were blocked* (`tool_calls.blocked`); *what
the successful proposal cost* (`tokens.through_proposal_total`, and the turn's `tokens.total`);
*did the answer reflect the kept proposal* (`proposal.outcome` is set by the service from the
persisted proposal: `created`, `not_created`, `discarded`, `shown_pending`, `not_attempted`);
*was the budget appropriate* (`budget`, `retry_round`).

## Flat trace metadata

The trace root carries these (and the older `model_requests`, `tool_calls_requested`, `status`, ...):
`model`, `models_reported`, `request_completed`, `tool_calls_{requested,executed,blocked,failed,empty,loaded}`,
`tool_success_rate`, `tool_success_denominator`, `tool_counts` (`name:requested/executed/blocked/failed`),
`tool_calls_per_round`, `duplicate_calls_blocked`, `repeated_lookups`, `retries_after_changed_evidence`,
`proposal_outcome`, `proposal_attempts`, `proposal_rejections`, `missing_prerequisites`,
`proposal_complete`, `retry_rounds_entered`, `retry_rounds_recovered`, `retry_round_outcome`,
`budget_exhausted`, `budget_reason`, `failure_reasons`, `tokens_{input,output,cached_input,reasoning,total}`,
`tokens_source`, `tokens_requests_reporting`, `tokens_through_proposal`, `latency_{turn,model,tool}_ms`,
`latency_decision_reply_validation_ms`, `latency_retry_round_ms`, `latency_slowest_request`,
`model_request_ms`, `trajectory` (codes, at most 64), `trajectory_events`.

## Gemini token usage

What the installed SDK (`google-genai` 2.30.0) exposes in `usage_metadata`, and how Formiq records it
per model request (`ModelTurn.usage`, `app.ai.gemini.token_usage`):

| SDK field | Formiq field | Notes |
|---|---|---|
| `prompt_token_count` | `input_tokens` | includes the cached part |
| `cached_content_token_count` | `cached_input_tokens` | only when Gemini reports it |
| `candidates_token_count` | `output_tokens` | excludes the thinking |
| `thoughts_token_count` | `reasoning_tokens` | only for models that think |
| `tool_use_prompt_token_count` | `tool_use_input_tokens` | server-side tools only; a function-calling request, as Formiq's, normally has none |
| `total_token_count` | `total_tokens` | Gemini's own: it also holds the thinking and any tool-use input |
| `model_version` (on the response) | `ModelTurn.model` | the model that answered, which can be more specific than the one asked for |

Rules: measured, never estimated (`tokens.estimated` is always `false`); a field Gemini did not report
is left out, never zero; a request without usage is `available: false`, and the turn's `tokens.source` is
`provider_reported` (all requests reported), `partial` or `unavailable`; the turn's totals sum only the
requests that reported the field and say how many did (`requests_reporting` of `requests_total`);
**`total` is the sum of Gemini's totals, never input + output**, which would miss the thinking; each
request's own counts stay in `tokens_per_request` so any total can be audited; `through_proposal_total`
is the tokens of the requests up to and including the one that made the accepted proposal, or null if
any of them did not report. Not available, and why: the per-modality breakdowns
(`*_tokens_details`: Formiq sends text only), `traffic_type` (billing tier, not usage), and any field
a given model does not report.

`model` in the summary is the model the provider was configured with: `GEMINI_MODEL` in the process
environment wins over `backend/.env`, so a running playground's model is the one its environment gave
it, and `models_reported` is what Gemini says answered.

## Latency

All durations are measured, in milliseconds, around the thing itself, never inferred from the turn:

- `turn`: from the request's start (the trace's creation) to its end.
- `model_requests`: around each provider call; `model_total` sums them; `slowest_request` names the longest.
- `tool_calls`: each executed call, as `FormiqTools.run` timed it (`last_durations_ms`); `tool_batches`:
  each run of the tools, measured by the graph; `tool_total` sums the batches (Formiq's own reads included).
- `proposal_validation`: the duration of the executed `propose_workout_plan` calls (the validation is
  inside the tool).
- `decision_reply_validation`: the decision and reply checks together.
- `retry_round`: from the retry round's request to its end (null if none).
- `provider_retries` and `provider_backoff`: always 0: each model request is attempted once, with no
  retry and no backoff.

## Aggregating a QA pass

`aggregate(summaries)` (`app.observability.trajectory`) and `playground/qa_metrics.py` give, with sample
counts and what each rate is a rate of: median, p90 (nearest rank) and max of turn latency, model-request
latency and tool-execution time; model requests, tool calls and tokens per turn; tokens per kept
proposal; proposal success (of the turns that asked for a proposal); retry-round use (of all turns) and
success (of the turns that entered it); the share of turns with a blocked duplicate or a validation
rejection; tool success (of executed calls); and the failure reasons. Turns of different models are
listed together and must not be compared; `qa_metrics.py` refuses a log that holds several models unless
one is chosen.

## What changed in existing fields (2026-10-16)

- `tool_calls_executed` no longer counts a call the tools refused for their per-turn limit
  (`TOOL_LIMIT_REACHED`): it is blocked. It counts Formiq's own reads (`tool_calls_loaded` is the part
  of it that is Formiq's).
- `tool_calls_blocked`, `tool_calls_failed`, `tool_calls_empty` are new counters.
- A tool span gained `origin` and `repeat`. `PROPOSAL_REFUSED` now maps to
  `proposal_rejected_irrecoverable` (it was `tool_error`), `CONTEXT_MISSING` to `missing_prerequisite`,
  and a proposal's `INVALID_INPUT` to `proposal_rejected_correctable`.
- `ModelTurn` gained `model` (observability only); the contract test pins it.
- (2026-10-17) A second proposal in a turn (one is accepted, or one runs in the same round) is
  `PROPOSAL_LIMIT` and `proposal_limit`, not `PROPOSAL_REFUSED` and
  `proposal_rejected_irrecoverable`; it is no longer counted in `proposal.rejections` and records
  no `proposal_validation_rejected` event. `proposal_rejected_irrecoverable` is left for what
  proposing again cannot fix (no profile, a failed read). A reply rejected for giving the workout
  a length the proposal does not have is a `reply_rejected` with category `duration_mismatch`.
- Metadata lists may hold 64 items (they held 25), for the event codes.

## Not recorded, by design

The message, the history, the instructions, reasoning, tool arguments' values, results, profile and
workout data, replies, keys, passwords, tokens, exception text, and the user id. A debugging case that
needs content is reported as a limitation: `LANGFUSE_CAPTURE_CONTENT` stays off, and nothing here reads
it. A recording that fails is logged by the exception's type only, and the turn goes on.
