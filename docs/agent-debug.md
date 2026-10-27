# Debugging the coach locally (`AGENT_DEBUG`)

How to watch one coach turn in the terminal while developing: which prompt the model was sent,
what its request held, what it returned, which tools ran or were refused and why, which guard
rejected a decision or a reply, whether the turn was retried or stopped at a limit, and who wrote
the reply the user got. The code is `backend/app/observability/debug.py` (the sink),
`backend/app/agent/debug_view.py` (what the coach tells it) and the hooks in the graph, the
recorder and `CoachService`. `backend/tests/unit/test_agent_debug_sink.py`,
`test_agent_debug_turns.py` and `backend/tests/integration/test_agent_debug.py` prove it. The
guarantees are in `docs/agent-production-contract.md`, section 9.

It is a developer's tool, off by default. It changes nothing a turn does: not the prompt, the
context, the tools, the limits, the decisions, the API's answer, or what Langfuse receives.

## Turning it on

```bash
cd backend
AGENT_DEBUG=events  .venv/bin/python ../playground/server.py     # the timeline, no content
AGENT_DEBUG=content .venv/bin/python ../playground/server.py     # and the prompt, the tools, the safe data
```

or, for the API itself, `AGENT_DEBUG=content uvicorn app.main:app --reload`. Put the setting in
your own `.env` if you like (never commit it); `.env.example` shows it as `off`.

| Value | What is printed |
|---|---|
| `off` (default) | nothing; nothing is built |
| `events` | the turn's ordered events and safe metadata: the prompt's identity (variant, size, hash), the declarations' identity, the roles, parts and sizes of every message sent, each call's argument names, each outcome and guard verdict, the reply's source. **No text of any prompt or conversation.** |
| `content` | all of that, plus the text of Formiq's own constants (the system prompt, the tool declarations, the replies Formiq itself writes, why a decision or reply was rejected) and the tool data that is safe to show (below) |

The value is case-insensitive; an empty `AGENT_DEBUG=` is `off`; any other value is refused.

**It is refused, not ignored, where it must not run.** With `events` or `content` the settings do
not load unless `APP_ENV` is `development` or `test` **and is set**: the default of `APP_ENV` is
`development`, which says nothing about where the application runs, so a deployment that forgot
it is never taken for a development machine. The error names `APP_ENV` and shows no other setting.
`build_debug_sink` checks again, in case the settings were changed after they loaded. If your
`.env` has no `APP_ENV`, add `APP_ENV=development` yourself.

## What it looks like

Every line starts with the turn's short id, a sequence number that only grows and the milliseconds
since the turn began, so turns running at once can be told apart and each read in order. A line's
continuation (a prompt, the rows of a request) repeats the id and the number.

```
=== agent turn 3f9a1c2b4d5e6f708192a3b4c5d6e7f8 | user 7 | AGENT_DEBUG=content ===
[3f9a1c2b #001 +00001ms] turn_started ev=1
[3f9a1c2b #002 +00001ms] input message=<<redacted: user message, 38 chars, hmac 775120d5faa6>> history_turns=2 roles=[user,coach]
[3f9a1c2b #003 +00005ms] safety_check flagged=false category=SAFE rule=- tool_calls_allowed=true allowed_decisions=[]
[3f9a1c2b #004 +00005ms] context_fit chars_before=16252 chars_after=16252 budget=500000 compacted_results=0 ... fits=true
[3f9a1c2b #005 +00006ms] model_request_started ev=2 round=0 request=1 kind=open offered_tools=3
[3f9a1c2b #006 +00040ms] request n=1 round=0 kind=open model=... messages=1 context_chars=16252 ...
[3f9a1c2b #007 +00040ms] system_prompt variant=base chars=15723 sha256=5602b7b3e0f6 text=below
[3f9a1c2b #007]   You are Formiq, an adaptive AI fitness coach. ...
[3f9a1c2b #008 +00040ms] tool_declarations n=3 names=[get_user_profile,get_workout_plan,respond] ...
[3f9a1c2b #009 +00040ms] model_config function_calling_mode=ANY allowed_function_names=[...] automatic_function_calling=disabled ... generation_settings="none set: the model's defaults apply"
[3f9a1c2b #010 +00040ms] context[0] role=user parts=2
[3f9a1c2b #010]   part 0 history: <<redacted: history block, 431 chars, hmac 48481600cf38>> turns=[user,coach] omitted=0
[3f9a1c2b #010]   part 1 user_message: <<redacted: user message, 38 chars, hmac 775120d5faa6>>
[3f9a1c2b #012 +00040ms] response request=1 model_reported=- calls=2 text=- thinking=<<unavailable: not requested>> tokens=...
[3f9a1c2b #012]   call[0] name=get_user_profile id=call-1 args={}
[3f9a1c2b #012]   call[1] name=get_workout_plan id=call-2 args={plan_id: 12}
[3f9a1c2b #015 +00041ms] tool_result name=get_user_profile origin=model outcome=ok ... id=call-1
[3f9a1c2b #015]   result={output: {user_id: <<redacted: field user_id, ...>>, profile: <<redacted: field profile, 134 chars, hmac ...>>}}
...
[3f9a1c2b #030 +00043ms] decision_validation accepted=true iteration=1 intent=ADAPTATION decision=RETRIEVE_THEN_ANSWER
[3f9a1c2b #033 +00044ms] response_source source=model detail=decision_accepted reply=<<redacted: model reply, 59 chars, hmac ...>>
[3f9a1c2b #034 +00044ms] turn_completed ev=10 outcome=success termination=decision_accepted duration_ms=44 completed=true
[3f9a1c2b #035 +00044ms] summary status=success termination=decision_accepted ... model_requests=2 tokens_total=...
[3f9a1c2b #036 +00044ms] end
```

The lines:

- **The trajectory's own events** (`turn_started`, `model_request_started`/`_completed`,
  `tool_call_requested`/`_executed`/`_blocked`, `tool_execution_failed`, `proposal_created`,
  `retry_round_*`, `decision_rejected`, `reply_rejected`, `provider_error`, `turn_completed`, ...)
  are printed from the same recorder, in the same order, with `ev=` the event's number in
  `docs/agent-trajectory-observability.md`: the debug timeline cannot disagree with the trajectory.
- **`input`**: what the client sent, as roles and sizes.
- **`safety_check`**, **`context_fit`** (the size before and after fitting to the budget, how many
  results were compacted or superseded, whether it fits), **`termination`** (how the turn ended).
- **`request`**, **`system_prompt`**, **`tool_declarations`**, **`model_config`**, **`context[i]`**:
  the model request about to be made, before it is sent (so a request that hangs is visible).
  The prompt is shown **apart from the context**; the context is one row per message, with its role,
  and one line per part, so **the earlier conversation and the current message are separate parts**,
  never merged. A call or a result carries the id it is sent with (made from its name and position,
  and marked `(synthesized)`, when the provider gave none). A result the budget replaced with a note
  is shown as `status=compacted` (or `superseded`) with the size of what it replaced, apart from the
  originals (`status=original`).
- **`system_prompt variant=`**: `base`, `pending-note` (the base with the note of a proposal
  awaiting approval) or `safety/<category>` (a flagged request), with the text's size and its
  SHA-256 (first 12 hex digits, the same in every process). At the `content` level the text is
  printed **once per process for each hash**, exactly as the model was sent it; later requests say
  `text=<<printed earlier in this process>>`. The tool declarations are handled the same way.
- **`model_config`**: how the model may call tools, read from the configuration the provider
  actually sends. Formiq sets **no** generation setting (temperature, thinking, output limits): the
  line says so. The model's thinking is never requested, so `thinking=<<unavailable: not requested>>`.
- **`response`**: what the model returned, its calls with their ids, the token counts the provider
  reported (or `<<unavailable: the provider reported none>>`).
- **`tool_result`**: a call's outcome (`ok`, `empty`, `error`, `blocked`), its category and error
  code, whether it repeated an earlier call, how long it took, and at the `content` level its result.
- **`decision_validation`**, **`reply_validation`**: a guard's verdict. A rejection says who
  refused (`by=decision_policy`, `safety_policy`, `invalid_call`) or the reason (`reason=change_claim`),
  and at the `content` level Formiq's own words for it. **`rejection_returned_to_model`** says the
  rejection went back to the model, which round it was, the limit, and whether the model is asked
  again (`model_asked_again=true`) or the turn ends (`false`).
- **`response_source`**: who wrote the reply the user gets.

| `source` | `detail` | Meaning |
|---|---|---|
| `model` | `decision_accepted` | the model's reply, accepted (shown only as a size and a hash) |
| `safety_fallback` | `tools_requested`, `decision_rejected`, `no_model_turn` | Formiq's fixed safe reply for a flagged request |
| `generic_fallback` | `retry_limit`, `nothing_proposed`, `context_budget`, `out_of_scope_redirect` | Formiq's own "could not answer", "nothing was proposed" or redirect |
| `card_fallback` | `accepted_proposal` | the proposal Formiq accepted is shown with Formiq's own reply, worked out from its card, because the model's reply was refused until the limit |

Formiq's own replies are printed (they are its words); the model's is never.

- **`summary`** and **`end`**: the turn's outcome, requests, tool counts, proposal outcome and its
  8-character reference, tokens and time, from the trajectory's summary.

## Four markers say why something is not shown

| Marker | Means |
|---|---|
| `<<not captured: ...>>` | the level (`events`) or a cap left it out |
| `<<unavailable: ...>>` | there is nothing to show: the provider gave none, or the model's thinking was not requested |
| `<<redacted: ...>>` | it is private: its role and size are given, and at the `content` level a keyed hash |
| `<<truncated: +N ...>>` | it was cut to its bound (a message, a list, a turn's content, a constant) |

## What is private, and how

**What is safe to show is decided by allowlist, never by guessing at what looks sensitive**, because
no pattern finds every sensitive value (a name, an injury in a note, a goal written as a sentence).

- **Private, by default:** the user's message and history, the model's text and reply, plan names,
  notes, tool error messages, and any string a tool returned that is not on the lists below. They
  are shown as `<<redacted: role, N chars, hmac H>>`. The hash is an HMAC with a key made for this
  process, so a short value (a gender, an age) cannot be recovered by trying candidates, the same
  value has the same hash within a run (so you can see a value repeated) and the hash means nothing
  in another run.
- **Redacted by name, whatever the type:** the user's identity and profile (`first_name`,
  `last_name`, `email`, `phone`, `user_id`, `age`, `gender`, `goal`, the whole `profile`, and any name
  holding `weight`, `height`, `note`, `injur`, `medical`, `goal`, `sleep`, `diet`, `allerg`, ...),
  credentials (`token`, `secret`, `password`, `authorization`) and what approves a proposal
  (`binding`, `proposal_id`): `SENSITIVE_KEYS` and `SENSITIVE_PARTS` in `debug.py`.
- **Shown:** numbers, booleans, ids, dates, the exercise catalog's own data, and a short list of
  Formiq's result fields (`exercise_name`, `section`, `status`, `equipment`, `focus`, `category`,
  ...). That includes the equipment names a search filtered out because the user said they lack
  them (`excluded_equipment`): they are the catalog's names, Formiq's reading of the conversation,
  and what an equipment defect needs; they are not identity, profile, health or free text. **What the model chose** (a tool name, an argument name, an argument value) is shown only
  where it is Formiq's own vocabulary: a tool Formiq knows or offered, an argument name its schema
  declares, a value its schema allows. Anything else the model wrote, however much it looks like a
  name or a word, is private.
- **Tool errors:** the code and category are shown; the message is private (a tool's message can
  quote what the model sent), except the names of the fields it complains about, when Formiq
  declared them.
- **Scrubbed from everything shown:** the configured secrets by value (the Gemini key, the JWT
  secret, the Langfuse keys, the database passwords), and by pattern JWTs, `Bearer` tokens, API
  keys, `secret=`/`password=` values, credentials in URLs, emails, phone numbers and 32-character
  ids. This is a second line of defence. Control characters are escaped, so no value can drive your
  terminal.
- **Never printed:** the full proposal id or its binding, exception text (a provider failure shows
  its category, such as `provider_timeout`), keys, passwords and tokens.

**Bounds**, with a marker whenever they apply: a message to 2,000 characters, a turn's content to
40,000, Formiq's constants (the prompt, the declarations) to 40,000 each and only once per process
per hash, a list to 12 items, a result to 40 keys and 6 levels.

## Safe local use

- It is for your own machine and your own test data. The header names the user id, and the
  `content` level shows the numbers, ids, exercise names and workout structure of what the tools
  returned. It never shows profile values or the user's words, but it is still a record of a user's
  training: do not run it against real users' data, and do not share the terminal.
- **Do not redirect it to a file or a log aggregator** (`2>&1 | tee`, a process manager): it writes to
  stderr only on purpose, and keeps no file, so nothing persists. The settings refuse it outside
  development and test, so it cannot be left on by mistake in a deployment that sets `APP_ENV`.
- Several turns at once interleave by line: filter by the turn's id (`grep '\[3f9a1c2b '`).
- A line is written synchronously: a terminal that blocks (paused output) blocks the turn that is
  writing to it.
- **Rendering costs time**, so with the debug output on a turn takes longer. The request is rendered
  before the model's clock starts, so the model's measured time is not inflated by it.
- The application's usual INFO logs, such as `coach_turn_summary`, are separate: they are shown only
  where a log handler is configured (the playground prints that one line). The debug output does
  not use the logging system.
- If you need the exact, unredacted words of a turn, this tool will not give them: that needs a
  separate, narrowly scoped design, approved on its own.

## Why Langfuse still receives metadata only

The debug output is a sink of its own: it never touches a tracing backend and never sets or reads
`LANGFUSE_CAPTURE_CONTENT`, which stays off by default, allowed only in development and test, and
unchanged. A tracer given a debug output keeps the backend and the capture setting it was
configured with, so enabling `AGENT_DEBUG` cannot make Langfuse receive anything more. Tests hold
this with the real Langfuse SDK exporting to memory: with the debug output on at `content`, no
exported span carries a message, a reply, a prompt, a hash or any input or output, and the spans
are the same as without it.

## What it does not change

The model is sent exactly the same contents, instructions, tools and tool configuration, and the
turn ends the same, with the debug output off, at `events` and at `content`: the five reliability
scenarios (a rejected decision, a compacted run to the limit, a flagged request whose model fails,
an invalid output, refused calls) and the accepted-proposal fallback are compared field by field. A
debug output that fails halfway (a stream that raises, a builder that raises) changes nothing; it is
logged once by its type. The API's response is the same, and approving a proposal made under it
works as before.

## Limits

- Redaction by allowlist is strict, so a field that should be visible may be redacted; extend
  `RESULT_STRING_KEYS` in `debug.py` deliberately, with a test, never by loosening a pattern.
- The scrubber's patterns (emails, phone numbers, ids) are best-effort and apply only to what is
  shown, which is already limited to Formiq's own text, the catalog's data and the allowlisted
  fields.
- The 8-character `proposal_ref` of a proposal is printed (it is in the trajectory too); it cannot
  approve anything.
- The hash of a private value is per process: it cannot be compared across runs.
