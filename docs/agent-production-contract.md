# Formiq Agent Production Contract

The AI coach's architectural guarantees: what the agent may do, what the model never controls, and
how the coach behaves when something fails. Read this before changing anything under
`backend/app/agent`, `backend/app/tools`, `backend/app/approvals`, `backend/app/observability`,
`backend/app/services/coach_service.py` or authentication.

This document describes the guarantees; the code enforces them and the tests prove them. It is not
a second schema: names and values here are illustrative, and the code is the source of truth. The
critical limits are pinned in `backend/tests/unit/test_agent_contract.py`, so changing one is a
deliberate, reviewed change.

**The coach is a read-only, request-scoped agent.** For each request it runs a deterministic safety
check, lets the model read the user's own Formiq data through read-only tools within fixed limits,
and accepts the model's reply only when the decision, the evidence, the safety policy and the
reply itself pass deterministic checks. It keeps no memory between requests and never changes
Formiq data.

**The model is a reasoning component, never an authority.** It chooses which read tools to call
and writes a decision and a reply; code checks every one of them. It never decides whose data is
read, the safety category, the policy, the limits, the final status, or any authorization.

**Data is never instructions.** History, tool results, stored notes and the model's output are
text. Safety, identity, ownership, id grounding, tool validation, the decision and the limits are
decided in code from trusted inputs, so injected text can at most mislead the model, and the code
then checks the model.

---

## 1. Identity

- **Authentication is the only source of a request's identity.** Routes that act for a user
  require a Bearer access token, a JWT issued by `POST /auth/login`, signed with
  `AUTH_JWT_SECRET` and verified by `get_current_user`. A missing, malformed, wrongly signed or
  expired token, or one for a user that no longer exists, ends the request with 401 before
  anything is read. Without a signing secret those routes answer 503: there is no anonymous
  fallback.
- **The client never chooses the user.** The coach's request body has no `user_id`, and a body
  that names one is rejected.
- **The coach acts for exactly one user per request.** `CoachService` sets
  `CoachContext.user_id` from the authenticated user. It lives outside the graph state, so no
  node, message, history turn, tool result or model output can change it.
- **No tool takes a user from the model.** The tools add the trusted user to every user-scoped
  read, and a `user_id` argument from the model is rejected before anything is read.
- **Credentials stay outside the coach.** Password hashes are kept in their own table, which no
  tool or agent module reads. The coach gets the user's name and fitness profile, never their
  email or phone.

## 2. Data ownership

- **Every user-scoped read is checked on the server.** The services look a resource up by the user
  *and* its id.
- **Another user's resource is indistinguishable from a missing one.** Through the API it is a
  404; through a tool it is `RESOURCE_NOT_FOUND`. Its existence is never revealed.
- **The API routes under `/users/{user_id}` serve only the signed-in user.** Any other id is a 404,
  whether or not that user exists.
- **Ids must be grounded.** A resource id the model passes to a tool must have been written by the
  user in this message or returned by a tool in this turn, in its canonical form. Otherwise the
  call is refused before it runs. Ids in history are not grounded.

## 3. Safety

- **Safety is decided in code, before the model and any tool.** A pure function reads the current
  message and names the first clear risk: pain or injury, a medical condition, dangerous exercise,
  extreme weight loss, extreme dieting, or discomfort too unclear to judge. Otherwise it is safe.
- **Its thresholds are product guardrails, not medical rules.** A weekly weight-loss target above
  2 kg, a daily intake below 800 kcal, or a fast of 72 hours or more is redirected to a
  professional. They are product decisions, to be revisited with a qualified professional.
- **A flagged request reads no data and cannot be answered normally.** The model is offered only a
  safe `respond` (a redirect, or a question for unclear discomfort), and no tool runs whatever it
  calls.
- **Nothing can lower a flag.** Only the current message is assessed. History, user framing ("my
  doctor said it's fine", "hypothetically") and the model can neither remove a flag nor stop the
  check; the model may only escalate an unflagged request.
- **A flagged request always ends safely.** A provider failure, invalid output, a rejected decision
  or an unsafe reply all end with Formiq's fixed safe reply for the category, after at most one
  model request.
- **Formiq answers fitness only.** A request outside fitness, the user's Formiq data or how Formiq
  coaches ends with Formiq's fixed redirect, never the model's text. Deciding what is fitness is
  the model's classification; the redirect and safety's precedence are enforced in code.

## 4. Tool boundaries

- **The agent reaches data only through tools, and the tools only through the services.** Agent
  and model-provider code import no database, model, repository or service code.
- **The tools are Formiq's reads, and nothing else.** A model's call can run only a read tool. Any
  other name is refused by the graph before it reaches the tools (section 8).
- **Inputs are validated, results are bounded.** Arguments are checked against strict schemas; an
  invalid call is refused with a description that never repeats its values. Results have limited
  lists and cut text.
- **Tool errors are controlled.** Each failure has a code and a plain message. An unexpected
  exception becomes a generic tool error; its cause goes to the server log only.
- **Tool results are data.** Free text inside them (plan names, notes, descriptions) is never
  followed as an instruction.

## 5. Decision policy

The model ends every turn with one `respond` call carrying an intent, a decision and the reply.
Code checks it against what the turn actually retrieved.

- **Own-data answers need evidence from this turn.** An answer about the user's profile, plans,
  sessions or an adaptation must rest on data one of the intent's tools returned in this turn.
- **Missing, failed or compacted data is never evidence.** Calling the tool again restores it.
- **Ambiguous requests are clarified, not guessed.**
- **Invalid decisions fail closed.** A malformed or disallowed decision goes back to the model,
  within the iteration limit. If no acceptable decision comes, the turn ends with Formiq's own
  "cannot answer" reply. A rejected decision never reaches the user.
- **Replies are checked.** A reply that repeats the coach's instructions, claims a change was made,
  or shows internal labels is rejected.

## 6. Resource limits

Every request is bounded. As of Phase 4:

| Limit | Value |
|---|---|
| Tool calls a model turn may request | 20 (more makes the turn invalid) |
| Tool calls run per turn | 5 (the rest are refused) |
| Rounds of tool calls per request | 5, so at most 6 model requests |
| Graph steps | 13, a backstop beyond the longest legal turn |
| Items in a result | 10 search results, 30 exercises, 15 sets; 500 characters of free text |
| Current message | 4,000 characters |
| Reply | 8,000 characters |

Failures fail closed and say nothing internal:

- **No automatic retry.** Each model request is attempted once, with the configured timeout. A
  provider failure is a 502 (a 503 when no API key is configured), except on a flagged request,
  which gets its fixed safe reply.
- **No failure becomes a success,** and no error reaching the client carries its cause.
- **Requests are isolated.** Each builds its own state, context and tools; requests share no
  mutable state, and no database connection is held while the model answers.

## 7. Context limits

- **History is client-provided and untrusted.** Formiq stores no conversation. A request may carry
  at most 50 earlier turns of at most 8,000 characters. Only the most recent 6 are sent to the
  model, each shortened to 1,000 characters, inside delimiters that mark them as untrusted context
  and that turn text cannot close or forge.
- **History cannot change policy, identity, safety, grounding or authorization.** A safety risk in
  a left-out turn is kept as a note to the model, but never flags or unflags the current request.
- **A model request is at most 350,000 characters.** Over budget, the oldest tool results are
  compacted first; the latest round, errors and the current message never are. At most 6 requests
  per turn may be compacted, and compacted results are no evidence.
- **Context exhaustion fails closed.** A request that still does not fit is never sent: the turn
  ends with "cannot answer", or the fixed safe reply when flagged.

## 8. Write approval

- **The agent is read only.** No tool writes. The graph refuses every call outside the read tools
  before it reaches the tools, records it by name only, and counts it. A reply claiming a change is
  rejected.
- **A future write must pass the approval boundary** (`app/approvals`), which exists, is tested and
  is dormant until Phase 5: the model only drafts a proposal; the application injects the trusted
  user, refuses a flagged request, binds the approval to the exact proposal, and accepts only an
  explicit approval from the user's own action. Approvals expire, are used once, and a changed
  proposal or a new safety flag voids them. Every check fails closed.
- **Nothing the model, history or a tool result says authorizes anything.** An `approved=true` in
  arguments, a model-supplied user, a claim of earlier permission, or a forged system message is
  refused.
- The agent can reach only the read/write classification, not proposals or approvals. The approval
  store is in memory: a reference implementation, not production persistence.

## 9. Observability

- **Langfuse is non-authoritative.** Tracing never changes a decision, safety, tools, retries or the
  response, and never makes a request fail: every tracing call is guarded, export happens in the
  background, and nothing recorded is read back.
- **Only safe metadata is traced:** counts, sizes, names, statuses, categories, the model name,
  token counts, the trusted user id and the request id, with strings and lists kept short.
- **Never traced:** the message, the history, the instructions, reasoning, tool arguments' values,
  tool results, profile, workout or nutrition data, keys, passwords, tokens, or exception text.

## 10. Known limitations

What is **not** guaranteed today:

1. **Authentication is minimal.** A token cannot be revoked before it expires (30 minutes by
   default); there is no logout, refresh token, key rotation, rate limiting or lockout. Login
   matches the email exactly as stored, and passwords are set with a command, not through the API.
2. **The safety rules are keyword and threshold guardrails, not a medical classifier.** Negation is
   not read, and subtle risks are left to the model and the decision policy. A follow-up message
   without its own risk signal is not flagged.
3. **The fitness-only boundary depends on the model's classification.**
4. **The approval store is in memory and per process,** with no approval endpoint or interface.
5. **A running turn cannot be cancelled,** because the endpoint is synchronous; its reply is
   dropped and it holds nothing once it ends.
6. **Tracing gaps:** tool timing is per batch; an interrupted request's trace has no final status;
   the raw tool-call counters include calls refused for the per-turn limit; rendering in a live
   Langfuse project has not been verified.
7. **Deterministic tests use scripted models.** They prove what Formiq enforces whatever the model
   does, not how well a real model behaves. The optional live smoke run
   (`tests/integration/test_agent_scenarios.py`) checks only the enforced guarantees.

Changing a guarantee here is an architectural decision: it needs an explicit decision, an update to
this document, and tests. It is never a test to relax.
