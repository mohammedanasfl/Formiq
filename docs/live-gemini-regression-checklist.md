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
| 6 | Pending-proposal follow-ups after a kept proposal: "Why did you choose these?", "Explain the second exercise.", "Show me the final proposal.", "What changed from my current plan?"; then approve once, and a second approval | 1 run, 4 follow-ups | same card (id and binding) each time; `reply_rejections` per follow-up (the baseline's 3 of 4); a second approval with the same binding is 200 with the same plan the first one saved (no second plan; 409 only if that plan was changed, cancelled or removed since, or the binding is another); then, with a proposal pending, a statement that calls for a change ("I don't have a bench by the way, so nothing that needs one."): no reply may say the workout was updated while no `propose_workout_plan` call ran (the 2026-10-16 B5 failure), and the card stays the pending one |
| 7 | Several saved plans: "Show me my saved plans.", "Change my workout." | 2 | all plans listed; the clarification names them |
| 8 | Grounding: a rewrite that cannot be done ("every main exercise uses the rowing machine") makes no false claim; "What did I do in my last workout?" and "Did I complete <an exercise the session has no set of>?"; a plan comparison | 4 | no "I rewrote..." claim; history exact; comparison accurate |
| 9 | Budget and provider errors: any turn with `budget.exhausted`; a turn with a provider failure | as they occur | `budget.reason`, rounds used, `provider_error` category; honest final message |
| 10 | A first workout for a new user with no plan (2026-10-16 B2): "Build me an upper-body workout for 40 minutes." from a fresh account, 8 attempts, whatever intent the model ends with | 8 fresh accounts | a proposal each, 3 model requests; `validation.decision_rejections` 0; no turn ends `cannot_answer` with `proposal.outcome` `discarded`; a second proposal, if any, is `proposal_limit`, never a rejection |
| 11 | Equipment over a long conversation (2026-10-16 B4): "I work out at home and all I have is a pair of dumbbells and a resistance band.", then 4 or more exchanges that do not mention equipment, then "I really dislike glute bridges." and "Give me a chest workout." | 2 | the coach does not ask again what equipment the user has; a workout search excludes what they lack (`excluded_equipment`); no proposal needs it |
| 12 | The length of a workout (2026-10-16 B3): "Now give me a lower-body day with the same stuff." after "Build me an upper-body workout for 40 minutes." in the history; and "How long will the whole workout take?" | 4 | any length the reply gives matches the card's `estimated_minutes` (two minutes) or a section; `reply_rejections` with category `duration_mismatch` counted, and what a retry cost |
| 13 | Catalog scope (2026-10-16 B5): "Replace every main exercise with a rowing machine exercise." | 4 | no "the catalog has no rowing machine exercises" without saying it is for the main workout; Easy Rowing named for the warm-up or cool-down when it is mentioned at all; no proposal with it as a main exercise |
| 14 | A proposal claimed that was not made (2026-10-17, F1 residue): with a proposal awaiting approval, "Can you put Easy Rowing in my main workout?" and "Add the One-Arm Dumbbell Row to my main workout." | 6 | no reply says "I have proposed / I've proposed ... a new, updated or replacement workout" unless the turn's `proposal_outcome` is `created`; on `proposal_rejected_*` turns the final reply says nothing was changed; the card is the pending one |
| 15 | A revision keeps its plan's day (Phase 2.3, **not yet run live**): with a plan for a day other than today (UTC), `workout_plan_id` set, "Make it a little harder." and "Rewrite this plan with different ab exercises." | 4 | the proposal's `scheduled_date` is the plan's own and `changes.scheduled_date_changed` is false; no `propose_workout_plan` call is refused for a day the user did not name (`INVALID_INPUT`, "did not name a day"), or, if the model does give a day, it is corrected within the turn; with "move it to tomorrow", the day is tomorrow and `scheduled_date_changed` is true |
| 16 | A request about plan A is not answered with plan B's proposal (Phase 2.3, **not yet run live**): a pending proposal for plan B, then a request with `workout_plan_id` A: "What did you propose?" and "Make it shorter." | 4 | `get_pending_proposal` finds nothing for A (`RESOURCE_NOT_FOUND`, "for workout plan A"); the response shows no card for B (`proposal_outcome` is not `shown_pending`); a proposal, if made, revises A |
| 17 | A date-only move (Phase 2.5; **run live 2026-10-23, Phase 2.6**: 11 turns, see the note under the table): a plan for a day other than today, `workout_plan_id` set, "Move it to Friday." (a date in the next 14 days), "Reschedule it." and "Move it to the day it is already on." | 3 | the first: a proposal with the plan's exercises and the named day (`scheduled_date_changed` true, nothing else in `changes`), not "nothing was proposed"; the second: a question (ASK_CLARIFICATION), no proposal, no invented day; the third: no proposal, a reply that it is already on that day; no reply says the workout was moved or updated |
| 18 | Weights (Phase 2.5; **run live 2026-10-23, Phase 2.6**: 10 turns, see the note under the table): a plan with a weight on one exercise, "Make it a little harder." / "Make the woodchop 20 kg." / "Make it heavier." / "Do it without the weight." | 4 | the first: the weights carried on (no `15 kg → no weight` in the card's changes); the second: that exercise 20 kg and a weight-only change; the third: no weight chosen, a question for how many kg (refusals "never choose one" counted); the fourth: the weight removed and shown as removed; no reply promises a weight it did not propose |
| 19 | The reply states where a workout stands (Phase 2.5; **run live 2026-10-23, Phase 2.6**: 7 turns, see the note under the table): after a proposal, "Did it save?"; with a proposal pending for plan B and a request about plan A, "Is anything waiting for my approval?"; after approving, "Did that save?" | 3 | no reply says a pending or just-proposed workout is saved, updated, adjusted or applied (`applied_claim` counted); no reply tells a user with plan B's proposal waiting that they have none (`pending_denied_elsewhere`); after a real approval the reply may say the plan is saved |
| 20 | Relative dates are the calendar's (Phase 2.7, **not yet run live**): a plan for a day at least 3 days ahead, `workout_plan_id` set, `timezone` sent (`Asia/Kolkata`, and for contrast `America/Los_Angeles`; at 20:30 to 23:30 UTC the two are on different days), "Move it to tomorrow.", "Move it to Friday.", "Move it to Saturday 31 October.", "Move it to the 28th." | 3 per phrasing and zone | the card's day is the calendar's day (first draft, or after Formiq's refusal with the right date); **count first drafts right vs corrected by the refusal vs a wrong day on a final card (must be 0)**; the reply states the date |
| 21 | An open request is asked about, never guessed (Phase 2.7, **not yet run live**): "Move it to the weekend.", "Push it to next week.", "Move it to Friday." on a Friday, "Move it to tomorrow or Saturday." | 3 each | no proposal; the reply asks which day and names the options; then "Saturday" gives the card for that day; **count turns where the model chose a day without asking (must be 0)**, model requests, refusals |
| 22 | Outside the window, or no day (Phase 2.7, **not yet run live**): "Move it to 1 January 2027.", "in three weeks", "Reschedule it.", "Move it to 03/04." | 3 each | no proposal; the reply says it plans only the next 14 days, or asks which day; no other day chosen for the user |
| 23 | Refining a date-only proposal (Phase 2.7, **not yet run live**): "Move it to Saturday." then "Make it a little harder." (once with the first turn in `history`, once without) and "Make it a little harder." again | 3 | `GET /coach/proposals/pending` lists **one** card (the newest); approving the older card is a 409 that says it was replaced; the second card keeps Saturday and shows both changes; a request that names another plan leaves that plan's card pending |
| 24 | The reply says what the records back (Phase 2.7, **not yet run live**): with a pending card "Did it save?" and "What did you propose?"; a plan named with `&`, quotes or three words ("Core & Abs Focus"); after approving, "Is it saved?"; after rejecting, "Is it still waiting?" | 6 | **false positives** (a truthful reply rejected: an extra model request, read from `reply_rejected_categories`), true positives, and **any claim that passed: read every reply**; whether `applied_claim`, `pending_denied`, `pending_denied_elsewhere` or `refused_proposal_presented` fired live for the first time |

**Phase 2.6 live run of rows 17 to 19** (2026-10-23, `gemini-3.5-flash-lite` by environment override, because the
configured `gemini-3.8-flash` returned 504 on its single probe; 30 turns, 106 model requests, 0 provider failures, no 429;
a scripted-model run is not live evidence, this one is). What it showed:

- Date-only moves: a named date (30 Oct, 28 Oct) gave a proposal with the plan's exercises and weights and only the day
  changed, nothing saved before approval, and approval saved the day (201, then 200, original CANCELLED). "Reschedule it."
  asked which day. A date outside the window and the plan's own day were refused by Formiq and the replies said so.
  **Model weak spots (Formiq cannot check them, it only checks that the user named *a* day):** "tomorrow" was resolved to the
  plan's day plus one (27 Oct, not 24 Oct) in 2 of 3 first drafts and in 1 of 3 final cards, and "the weekend" was answered
  with Sunday 1 Nov without asking. The model is never told today's date directly.
- Weights: the model sometimes copies a weight from another plan or exercise; Formiq refused every ungrounded one
  ("you never choose one") and carried the plan's weights on when the model left them out. kg, "add 5 kg" and "without the
  weight" worked and were saved exactly; "45 lb" was sent as 45 kg (refused, the model asked), "44 pounds" was converted and
  saved as 19.96 kg; "heavier" got a question. 600 kg and 550 kg were turned away by the model's own safety redirect, so the
  500 kg cap was **not reached live**.
- Replies: every reply after a proposal said it was proposed and to approve it, but "I have adjusted your \"<name>\"
  workout..." (a quoted name) was not caught by the change-claim check (D1, D6). `new_proposal_claim` rejected three truthful
  descriptions of a pending card ("the harder version I proposed...") and twice rejected a reply made before the proposal
  had been accepted, correctly. No `applied_claim`, `pending_denied`, `pending_denied_elsewhere` or
  `refused_proposal_presented` was triggered, so those four checks are enforced by scripted tests only.

## Phase 2.7 follow-up pass: the plan (not run; it needs the user's go-ahead)

What Phase 2.7 changed is proved by scripted tests only (they show what Formiq enforces, not how Gemini
behaves). This pass is the evidence, and it is separate from the Android pass: say which one an observation
came from.

- **Isolation first.** The backend tests now run in `formiq_pytest`, never `formiq_test` or the development
  database. The pass uses fresh `qa-live27-*@formiq-qa.invalid` accounts in the development database (as the
  previous passes did) or in `formiq_test` (as the Android passes did); it deletes nothing. Do not run the
  backend suite during the pass: it touches neither, but it competes for the machine and its timing.
- **Budget and model discipline, as in Phase 2.6.** A hard request budget (150) stated before the first request,
  counted per model request, with the counter written down as it goes; a stop on a per-day 429, on three
  consecutive provider failures and on six in total. Probe the default model once, and if it fails use
  `gemini-3.5-flash-lite` explicitly (an environment override of the process you own; no `.env` change, no
  persisted override), recording the model Gemini reports for every turn.
- **Order, cheapest evidence first:** row 20 (3 phrasings x 3, in `Asia/Kolkata`), row 21 (4 x 3), row 22 (4 x 3), row
  23 (3), row 24 (6 in all); about 60 turns and, at 2 to 4 model requests a turn, about 150 requests: run rows 20
  and 21 first, and spend what is left on 23 and 24. Row 20's contrast case (`America/Los_Angeles` at the same
  hour) is one phrasing, 3 turns.
- **Send the zone yourself.** The playground page does not send `timezone` yet (the coach is told it is using UTC dates);
  drive `POST /coach/message` directly with the zone, as the Phase 2.6 harness did, or say the pass ran in UTC.
- **Record per turn:** the zone sent, the date Formiq worked as today, the card's day, the number of model
  requests, every reply rejection with its category (`coach_turn_summary`), and for the dates whether the
  first `scheduled_date` the model gave was right.
- **Go / no-go evidence for unattended daily generation.** All of: zero wrong days on a final card across rows 20 to 23;
  zero turns where the model chose a day from an open request (row 21); one pending card after every refinement
  (row 23); every reply read by hand, no false claim passed (row 24); at most one extra model request per
  truthful pending statement. Anything less is reported as a number, not a verdict.

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
