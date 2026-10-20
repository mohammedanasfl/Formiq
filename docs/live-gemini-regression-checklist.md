# Live Gemini regression checklist

A repeatable pass against live Gemini through the local playground, which measures reliability, cost
and latency from safe trajectory telemetry (`docs/agent-trajectory-observability.md`). Scripted-model
tests prove what Formiq enforces; this pass is the only evidence of how a real model behaves. It
needs the user's go-ahead before it starts (live requests cost quota and a restart changes a running
service).

## Before the first request

1. `git status`, HEAD and branch recorded; no commit, push, stash or reset during the pass.
2. Who owns port 2001 (and 2002): `lsof -nP -iTCP:2001 -sTCP:LISTEN`, then its start command. A
   playground started before the latest code still serves old code: restart only the process you own
   (or with the owner's permission), with the same command.
3. The model: **the running playground's environment wins over `backend/.env`** (`GEMINI_MODEL`).
   Record the configured model (`summary.model`) and the one Gemini reports (`models_reported`). Keep
   the model of the baseline for a like-for-like comparison, or say plainly that it differs.
4. DB `formiq` at the Alembic head (`alembic current`), `alembic check` clean: no migration is needed
   unless a change adds one.
5. Langfuse: content capture **off** (`LANGFUSE_CAPTURE_CONTENT` unset); read metadata only. Never
   print keys.
6. Start the playground with its console saved to a file (it prints one `coach_turn_summary` line per
   turn). Space requests about 10 s apart. A provider 5xx is retried after a wait and reported as a
   provider failure, never hidden.
7. Fresh accounts only, `qa-<pass>-<alias>-<stamp>-<hex>@formiq-qa.invalid`, registered through
   `POST /auth/register`; never delete or change existing QA accounts, plans, sessions or proposals.
   Approve a proposal only where a scenario says to.

## Per request, capture

`X-Playground-Request-Id` (the turn's `turn_id`), HTTP status, wall latency, and from the summary:
the trajectory codes, `tool_calls` (requested / executed / blocked / failed / empty / loaded, per tool),
`proposal` (outcome, attempts, rejections, `missing_prerequisites`), `retry_round`, `budget`,
`failure_reasons`, `tokens` (source, input, output, cached, reasoning, total), `latency_ms`, and the
Langfuse trace for the request id (trace id = first 16 bytes of `sha256(request_id)` as hex; use the
`/api/public/v2/observations` endpoint, metadata fields only).

## Scenarios

Counts are per independent attempt; a fresh account (and a fresh seeded plan) for each attempt that
asks for a rewrite.

| # | Scenario | Attempts | Say what you see |
|---|---|---|---|
| 1 | Registration and authentication: register (any email case), login with another case, wrong password and unknown email (same 401), duplicate registration (409), no `POST /users` | 1 run | status codes; one row per email |
| 2 | Equipment aliases: "I only have dumbbells and resistance bands. Make me a 20-minute upper-body workout." and a pull-up bar / kettlebell / cable variant | 3+ | proposal equipment is only what they named; no round lost to equipment names or ids (`id_not_grounded` calls on `equipment_id` must be 0) |
| 3 | No equipment: "I don't have any equipment." then "Make me a 20-minute full-body workout." | 2 conversations | bodyweight only; in scope; honest about catalog gaps |
| 4 | Neck workout request | 2 | fitness, never the off-topic reply; declined or alternatives, no false catalog claim |
| 5 | "Rewrite this plan with different ab exercises." from the same 2-turn history and a core plan | **at least 8** fresh accounts | proposals / attempts; for each non-proposal: category (`failure_reasons`), `missing_prerequisites`, `retries_after_changed_evidence`, retry round used and recovered |
| 6 | Pending-proposal follow-ups after a kept proposal: "Why did you choose these?", "Explain the second exercise.", "Show me the final proposal.", "What changed from my current plan?"; then approve once, and a second approval | 1 run, 4 follow-ups | same card (id and binding) each time; `reply_rejections` per follow-up (the baseline's 3 of 4); a second approval is 409; then, with a proposal pending, a statement that calls for a change ("I don't have a bench by the way, so nothing that needs one."): no reply may say the workout was updated while no `propose_workout_plan` call ran (the 2026-10-16 B5 failure), and the card stays the pending one |
| 7 | Several saved plans: "Show me my saved plans.", "Change my workout." | 2 | all plans listed; the clarification names them |
| 8 | Grounding: a rewrite that cannot be done ("every main exercise uses the rowing machine") makes no false claim; "What did I do in my last workout?" and "Did I complete <an exercise the session has no set of>?"; a plan comparison | 4 | no "I rewrote..." claim; history exact; comparison accurate |
| 9 | Budget and provider errors: any turn with `budget.exhausted`; a turn with a provider failure | as they occur | `budget.reason`, rounds used, `provider_error` category; honest final message |
| 10 | A first workout for a new user with no plan (2026-10-16 B2): "Build me an upper-body workout for 40 minutes." from a fresh account, 8 attempts, whatever intent the model ends with | 8 fresh accounts | a proposal each, 3 model requests; `validation.decision_rejections` 0; no turn ends `cannot_answer` with `proposal.outcome` `discarded`; a second proposal, if any, is `proposal_limit`, never a rejection |
| 11 | Equipment over a long conversation (2026-10-16 B4): "I work out at home and all I have is a pair of dumbbells and a resistance band.", then 4 or more exchanges that do not mention equipment, then "I really dislike glute bridges." and "Give me a chest workout." | 2 | the coach does not ask again what equipment the user has; a workout search excludes what they lack (`excluded_equipment`); no proposal needs it |
| 12 | The length of a workout (2026-10-16 B3): "Now give me a lower-body day with the same stuff." after "Build me an upper-body workout for 40 minutes." in the history; and "How long will the whole workout take?" | 4 | any length the reply gives matches the card's `estimated_minutes` (two minutes) or a section; `reply_rejections` with category `duration_mismatch` counted, and what a retry cost |
| 13 | Catalog scope (2026-10-16 B5): "Replace every main exercise with a rowing machine exercise." | 4 | no "the catalog has no rowing machine exercises" without saying it is for the main workout; Easy Rowing named for the warm-up or cool-down when it is mentioned at all; no proposal with it as a main exercise |
| 14 | A proposal claimed that was not made (2026-10-17, F1 residue): with a proposal awaiting approval, "Can you put Easy Rowing in my main workout?" and "Add the One-Arm Dumbbell Row to my main workout." | 6 | no reply says "I have proposed / I've proposed ... a new, updated or replacement workout" unless the turn's `proposal_outcome` is `created`; on `proposal_rejected_*` turns the final reply says nothing was changed; the card is the pending one |

Browser (headless Chromium from the cached Playwright, no download): sign-in (a sign-up control does
not exist in the page, as of this writing), the proposal card's content and coverage, follow-ups while
pending, the approve button and a double click (one approval), saved plans (list, select, refresh), Clear
conversation, sign-out, and no stale card shown as newly saved.

## Report

A table (scenario, attempts, passes/failures, latency, proposal outcome, retry-round use, request
ids), then separate sections: **confirmed defects**, **intermittent model behavior**, **catalog
limitations**, **tests not run**; median and p90 latency with sample counts (`qa_metrics.py LOG
--model <model>`); and a prioritized defect list. Tokens are measured by Gemini and are never
estimated; say how many turns reported them. Eight attempts cannot show an improvement by themselves:
state the counts, separate what was measured from what is a hypothesis, and name every difference in
conditions from the baseline.

## The baseline to compare with (2026-10-15, no code change during the run)

`gemini-3.5-flash-lite` through the playground's environment override; 30 API coach turns, 4 browser
turns, 25 browser checks; rewrite requests 2 proposals in 8 fresh-account attempts (an earlier run: 1
in 8, one reused account); answered-turn latency median 9.7 s, p90 23.5 s, max 61.9 s (34 turns);
proposal-seeking turns median 13.6 s, p90 26.7 s; 131 model requests, one 503, no 429. Its causes:
four of five "nothing was proposed" endings were the duplicate-call rule refusing a proposal whose
cause was gone; the required reads were skipped in 7 of 15 proposal turns; four equipment searches
used an id nothing could ground; three of four pending follow-ups were first rejected by the reply
check. Token counts were not recorded per turn then, so there is no token baseline.
