# Formiq Agent Production Contract

The AI coach's architectural guarantees: what the agent may do, what the model never controls, and
how the coach behaves when something fails. Read this before changing anything under
`backend/app/agent`, `backend/app/tools`, `backend/app/approvals`, `backend/app/observability`,
`backend/app/services/coach_service.py` or authentication.

This document describes the guarantees; the code enforces them and the tests prove them. It is not
a second schema: names and values here are illustrative, and the code is the source of truth. The
critical limits are pinned in `backend/tests/unit/test_agent_contract.py`, so changing one is a
deliberate, reviewed change.

**The coach is a request-scoped agent that reads and proposes, and never writes.** For each request
it runs a deterministic safety check, lets the model read the user's own Formiq data through
read-only tools within fixed limits, and accepts the model's reply only when the decision, the
evidence, the safety policy and the reply itself pass deterministic checks. It may propose a new
workout plan, which only the user's own approval, outside the coach, saves. It keeps no memory
between requests and never changes Formiq data itself.

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
  require a Bearer access token, a JWT issued by `POST /auth/login` (or by `POST /auth/register`,
  which creates a new account with its password and never gives an existing one a password; no
  other route creates a user, so no one can take an email before its owner signs up), signed with
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
  the model's classification; the redirect and safety's precedence are enforced in code, and so is
  one veto: a request that names fitness (a workout, an exercise, equipment, a muscle, nutrition),
  or, in a conversation, a short follow-up asking to change what was discussed ("make it
  shorter"), is never out of scope. Its OUT_OF_SCOPE decision goes back to the model, which
  answers it as what it is, says what Formiq cannot do, asks, or redirects it for safety.

## 4. Tool boundaries

- **The agent reaches data only through tools, and the tools only through the services.** Agent
  and model-provider code import no database, model, repository or service code.
- **The tools are Formiq's reads and one proposal, and nothing else.** A model's call can run only a
  read tool or `propose_workout_plan`, which writes nothing (section 8). Any other name is refused
  by the graph before it reaches the tools. The reads include the user's saved plans
  (`list_workout_plans`, and two plans compared by `get_workout_plan`), and the user's proposal
  awaiting approval (`get_pending_proposal`), from Formiq's records for the request's user only:
  never its id, and reading it approves nothing.
- **A turn does not repeat itself.** A catalog search or lookup, or a proposal, that the model
  already has the result of, word for word, is answered with `DUPLICATE_CALL` and not run (a read
  of the user's own data may be repeated, and a compacted result is not "had"). Only a call that
  ran and came back is a result "had": a call Formiq refused before it ran (a read not made yet,
  an id nobody had given yet) is not, so the same call may run once the evidence has changed. If
  it has not, the same gate refuses it again and nothing runs. (The live regression pass of
  2026-10-15 found the earlier rule, which counted such a refusal as a result, ending proposal
  turns with nothing.)
- **Equipment is named, never numbered.** A catalog search for the exercises that use one piece
  takes it by name (`equipment`: the catalog's name, its plural or a common name, read by
  `app/tools/equipment.py`), which Formiq resolves; no tool gives the model an equipment id, so an
  id could never be grounded. An unknown name is refused with the catalog's names, a name for no
  equipment points to `available_equipment: []`, and a piece the catalog has that no exercise
  needs is no error: the search finds nothing.
- **A search that finds nothing for its section does not say the catalog has nothing.** A search by
  use (`MAIN_WORKOUT`, `WARM_UP`, `COOL_DOWN`) that returns no exercise also names, apart from its
  results (`matches_for_other_uses`: a total and at most 3 exercises, each with its name, uses and
  equipment, and no id), exercises that match every other filter and that Formiq uses for another
  section, or for none. They are not results for that use and no proposal can be built from them:
  the catalog's one Rowing Machine exercise, Easy Rowing, is a warm-up and cool-down activity, and
  cardio is never a main exercise, so a main-workout search for it finds nothing and says so (live
  QA, 2026-10-16, B5: the coach said the catalog had no rowing machine exercises). The coach is told
  to scope a negative claim to what it searched. A search that finds something, or whose other
  filters match nothing at all, is as it was; the equipment the user said they lack is left out of
  the disclosure as of the results.
- **Inputs are validated, results are bounded.** Arguments are checked against strict schemas; an
  invalid call is refused with a description that never repeats its values. Results have limited
  lists and cut text.
- **Tool errors are controlled.** Each failure has a code and a plain message. An unexpected
  exception becomes a generic tool error; its cause goes to the server log only. A refused proposal
  names everything wrong with it at once, and may carry Formiq's `suggestions`: catalog exercises
  the user can do that would fix it, whose ids are then grounded for the turn.
- **Tool results are data.** Free text inside them (plan names, notes, descriptions) is never
  followed as an instruction.

## 5. Decision policy

The model ends every turn with one `respond` call carrying an intent, a decision and the reply.
Code checks it against what the turn actually retrieved.

- **Own-data answers need evidence from this turn.** An answer about the user's profile, plans,
  sessions or an adaptation must rest on data one of the intent's tools returned in this turn. For
  the plan intent (`WORKOUT_PLAN`) a proposal Formiq accepted in the turn is such data
  (`propose_workout_plan` is one of its tools): a user with no saved plan and nothing awaiting
  approval has no other evidence for the workout they are shown, since a proposal is kept only once
  the turn ends (live QA, 2026-10-16, B2: the decision was rejected, the model looked for the
  proposal with `get_pending_proposal`, found none, and the turn ended with the proposal discarded).
  A refused proposal is no evidence, and no other intent counts a proposal (a session history or a
  catalog answer is not made from it). A second proposal in a turn is not run (`PROPOSAL_LIMIT`,
  `proposal_limit` in the trajectory): the workout was not judged, so it is no rejection of it.
- **Missing, failed or compacted data is never evidence.** Calling the tool again restores it.
- **A recommendation for today checks before it answers.** It is accepted only once the user's
  profile, current plan and last workout were each read in this turn, returning data or
  confirming there is none. A failed read is not a check.
- **Ambiguous requests are clarified, not guessed.** A revision of one of several PLANNED plans
  is refused unless the conversation makes the plan clear (its id or name, today's or the next
  workout for the current plan, or the plan the proposal awaiting approval revises): the coach asks
  which.
- **Invalid decisions fail closed.** A malformed or disallowed decision goes back to the model,
  within the iteration limit. If no acceptable decision comes, the turn ends with Formiq's own
  "cannot answer" reply. A rejected decision never reaches the user.
- **Replies are checked.** A reply that repeats the coach's instructions, claims a change was made,
  or shows internal labels is rejected; so is one that says the coach made or changed a workout,
  or that a new version is ready or to be approved, when the turn made no proposal (every form of
  the making and changing verbs, `app.agent.trust`: "propose" is one of them, so "I have proposed
  an updated workout" and "a new workout has been proposed" are claims of a proposal made), and
  one that says the user did an exercise the workout session read in the turn shows no completed
  set of. "A proposal made" is only one Formiq accepted in the turn: a read of the proposal
  awaiting approval, or a proposal Formiq refused (however many), never backs it (live QA,
  2026-10-17: the coach tried twice, both were refused, and it said it had proposed an updated
  workout beside the unchanged card). Offers and negations ("I can propose a new version", "I
  haven't proposed anything new", "I tried to propose it, but Formiq refused") claim nothing.
  A refused reply never reaches the user, whatever the round: the model corrects it within the
  limits of section 6, and if it never does, the turn ends with Formiq's own reply, which with a
  proposal Formiq accepted in the turn is worked out from its card (section 6), and otherwise is
  the "nothing was proposed" or "could not answer" reply.
- **A reply that explains the proposal the user is shown is not a claim of a new one.** A turn
  that makes no proposal shows the user the proposal awaiting approval again, unchanged, with the
  reply, so the reply may then describe it ("below", "here is the proposal", how the coach
  designed it) when all of these hold: the turn read it in a form Formiq shows again (its coverage
  is recorded), the turn tried to make no proposal, the reply is an answer, and the user's own
  message asks about it (a question, or a request to explain or show: `asks_about_proposal`) and
  asks for no change and calls for none (`asks_for_change`, which includes what the user lacks,
  cannot do or wants left out: "I don't have a bench"). Still rejected, whatever the words: a new
  or changed workout said to be made now, a workout said to be saved or approved, a proposal when
  none awaits, an exercise said to be done that no session shows, and the coach saying it changed
  something (updated, swapped, replaced, added, removed) that the proposal does not record as
  changed. Only the proposal's own `changes` (Formiq's comparison with the saved plan) back such a
  sentence, by naming one of them; "I added a warm-up" says how it was put together and is no
  change. A message that is not an explanation, or that the words cannot place, gets the strict
  check, so a mistake of the words costs a model request and never a false claim. The authority
  for a completed change is only a proposal Formiq accepted in the turn; a proposal saves nothing,
  so even then "I've updated your workout" is refused as a claim that data changed.
- **A reply states the workout's length as the proposal does.** The user is shown the proposal's
  card with the reply, and its minutes are worked out in code. A reply that says how long the
  workout takes ("a 40-minute workout", "it takes about 20 minutes", "26 minutes in all") must
  give the proposal's `estimated_minutes` (within two minutes, for rounding) or a section's or a
  timed exercise's own minutes, else it is rejected (`duration_mismatch`) and the model corrects it
  in its retry, with the figures in the rejection. The time the user has ("within the 40 minutes
  you have"), a rest between sets and the rest of a reply are not claims about the length, and the
  user's own figure does not excuse calling a shorter workout that long (live QA, 2026-10-16, B3).
  Only an accepted proposal in the turn, or the one awaiting approval that the turn read, gives
  the figures; a reply shown with neither is not checked.

## 6. Resource limits

Every request is bounded. As of Phase 5:

| Limit | Value |
|---|---|
| Tool calls a model turn may request | 20 (more makes the turn invalid) |
| Tool calls run per turn | 8 (the rest are refused): the reads and searches a workout needs, together |
| Rounds of tool calls per request | 5, and 1 more only to correct a refused proposal (below), so at most 7 model requests |
| Proposals accepted per turn | 1 (another is refused) |
| Graph steps | 15, a backstop beyond the longest legal turn |
| Items in a result | 10 search results, 30 exercises, 15 sets, 12 instruction steps, 20 plans listed, 3 suggestions for each thing a refused proposal must correct; 500 characters of free text |
| Current message | 4,000 characters |
| Reply | 8,000 characters |
| A proposed plan | 1 to 10 main exercises of 1 to 10 sets of 1 to 30 reps, at most 300 s of rest, no weight; today to 14 days ahead |
| Its warm-up and cool-down | 1 to 5 activities each, of 1 to 3 sets of 1 to 20 reps or 10 to 600 s, no rest or weight; at most 15 minutes each, and a warm-up of at least 3 unless the session is short |
| Its completeness | at least 4 different main exercises of 2 or more sets for a full body, 3 for a focus, 2 when the user has under 30 minutes (a short session); every region its focus needs; at least half the user's stated time, up to 45 minutes |
| A proposal's approval | within 30 minutes |

The round beyond the five is given only when the turn's last proposal was refused for something a
corrected proposal fixes (`INVALID_INPUT`, an id it was not given, the reads it rests on, which
Formiq has loaded by then (`CONTEXT_MISSING`), or the per-turn limit), and no proposal was
accepted; in it the model may only propose again or decide. A turn that tried to
propose and ends with no acceptable decision says that nothing was proposed (never the model's
text). The live QA of 2026-10-15 found proposal turns ending with nothing after a refusal in the
last rounds: this is the bounded room to correct one, not a larger general budget.

**A proposal Formiq accepted is not lost to the model's wording.** A turn that ends at its limit
with a proposal Formiq accepted in the turn, where the last decision the model gave passed the
decision policy and is an answer and only its reply was refused (a claim of a change, an approval
or a proposal, a wrong length, an internal name: any of the reply checks of section 5), shows that
proposal, as any answer does (section 8), and the reply is Formiq's own, worked out from the
proposal's card and never the model's text: how long the workout takes (its minutes, as Formiq
worked them out, and each section's), how many main exercises it has, that it replaces a saved
workout only if the user approves this one (without naming it, a revision), that Formiq's catalog
could not cover its focus (an incomplete one), and that it is not saved and waits for the user's
approval. The decision stands as the model gave it, since it was checked. This changes nothing
else: no request is added (the limit was already reached), the proposal is kept for approval
exactly as any shown one, pending until the user approves it, and the trajectory still records
the turn as ended at its limit (`retry_limit_reached`) with its proposal created, so the QA can
count it. It applies only when all of these hold; otherwise the turn ends as before, with the
generic reply and no card, or with "nothing was proposed" when every proposal was refused:

- a proposal call was accepted by Formiq in the turn: a proposal it refused (however many), and a
  read of the proposal awaiting approval, show nothing;
- the last respond call was valid, its decision passed the decision policy and answers the user
  (`ANSWER` or `RETRIEVE_THEN_ANSWER`): a refused decision, a call that is no decision, a
  clarification and a "cannot answer" are not Formiq's to turn into an answer;
- the card carries the figures to say (its minutes and its main exercises): none is guessed.

The live QA of 2026-10-17 found 3 of 30 accepted proposals dropped this way, each after a refused
change claim, and the user got the generic reply for work Formiq had accepted.

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
- **A model request is at most 500,000 characters** (one round of the 8 largest results, and the
  rest). Over budget, the oldest tool results are compacted first; the latest round, errors and
  the current message never are. At most 7 requests per turn may be compacted, and compacted
  results are no evidence.
- **An accepted proposal supersedes its candidates.** Once Formiq has accepted a proposed workout,
  later requests in the turn send the catalog search results from the rounds before it as a short
  note, whatever the budget: the proposal lists the exercises chosen. Like compacted results, they
  are no evidence, and their ids stay grounded.
- **Context exhaustion fails closed.** A request that still does not fit is never sent: the turn
  ends with "cannot answer", or the fixed safe reply when flagged.

## 8. Write approval

- **The agent never writes.** No tool writes. The graph refuses every call outside the read tools
  and the proposal before it reaches the tools, records it by name only, and counts it. A reply
  claiming a change or an approval is rejected, and so is one asking the user to review or
  approve a proposal when there is none: none made in the turn, and none of theirs awaiting
  approval (pending and unexpired in PostgreSQL, read by the coach service when the request
  begins, never taken from the model or the history). A reply may point the user to such an
  earlier proposal, but not present a new or changed one unless the turn proposed it, nor say it
  created a workout or plan ("I've created a core workout for you") unless the turn proposed one.
- **The model may only propose a new workout plan** (`propose_workout_plan`), and only after the
  user's profile, current plan and last workout were checked in the turn, with a profile to build
  for. Each of the three is in one of four states in the turn: not loaded, loaded with data,
  loaded and empty (a new user has no plan or workout yet, which is a check like any other), or
  failed (never a check, and never taken for "none"). A proposal made while one is not loaded
  waits for the rest of its batch, and Formiq then reads, for the request's user, whichever
  neither an earlier round nor that batch read (at most once each in a turn), and returns the
  results to the model with the refusal (`CONTEXT_MISSING`, with `loaded`): they are evidence
  for the turn like any tool result, and the model proposes again if a new workout still
  suits the user. A failed read, or no profile, is a refusal proposing again cannot fix. Formiq builds the proposal: the trusted user, active catalog exercises whose ids a tool
  returned, bounded prescriptions, no weights, and the user's stated time and equipment (what
  they have, `[]` for none, or what they cannot use, by the catalog's name, its plural or a common
  other name, `app/tools/equipment.py`: an unknown name is refused, never ignored, and a name for
  what the user has that negates or doubts itself, "no dumbbells", is refused too). What the user
  wrote about their equipment in the conversation holds whatever the model gives, however long
  ago they wrote it: the coach service reads it from every user turn the client sent (never a turn
  from "coach"; the latest word replaces an earlier one; "I only have dumbbells" and "all I have
  is dumbbells" mean nothing else), once, for the tools and for a bounded note to the model
  (`EquipmentSaid`, in the catalog's own names, within the note's 400 characters and only when
  turns were left out; the six-turn window is unchanged). A piece they said they lack ("I don't
  have any equipment", "I only have dumbbells") is never in a proposal or a workout search, and
  `available_equipment` may name only what they said they have (mentioning a piece is not
  having it). It has
  three sections, each holding only exercises whose `uses` (Formiq's own classification of the
  catalog, kept apart from an imported exercise's upstream category) include it: a warm-up of
  light (BEGINNER) `WARM_UP` activities, the `MAIN_WORKOUT` exercises, and a cool-down of light
  `COOL_DOWN` activities; a warm-up or cool-down activity must work a muscle the main exercises
  train, unless it is easy CARDIO. The coach service keeps the proposal it shows the user in
  PostgreSQL (`workout_plan_proposals`, through `PlanProposalService`), with its binding, a digest
  of the exact proposal, every section included, and its focus, the user's time and how it
  revises a plan, so it can be read back; no tool stores anything. A flagged request runs no tool,
  so it gets no proposal. The same workout as the user's proposal awaiting approval (the same day,
  plan revised and prescription) is not proposed again.
- **A revision replaces a saved plan only on approval.** When the user asks to change, rewrite or
  replace one of their plans, the proposal names it (`revises_plan_id`, an id a tool returned in
  the turn, of the user's own PLANNED plan, which the conversation makes clear when they have
  several, section 5) and how (`revision`: `ADJUST`, the changes asked for,
  which must change something; or `ALTERNATIVE`, a different workout, which may keep a main
  exercise of the plan only when the catalog has no other the user can do for its part of the
  body: Formiq checks this, with no fixed share). The proposal records the plan's id and a digest
  of what it prescribes, and its response says what it keeps (`revision`). It changes nothing.
  Its approval saves the new plan and cancels the original in one transaction, with both rows
  locked, and only if the original is still PLANNED and unchanged: otherwise 409, nothing saved,
  and the proposal still pending. The original is cancelled, never edited or deleted.
- **A proposal is a complete session for its focus, judged in code** (`app/tools/completeness.py`).
  The model names the focus (full body by default, or upper body, lower body, push, pull or
  core); each main exercise belongs to the body regions of its primary muscles, and covers a
  region only when one of them is a main mover of it (never a secondary muscle, and never an
  accessory such as the forearms, biceps, triceps or calves). A full-body workout covers the
  lower body, an upper-body push and an upper-body pull, with enough different
  exercises (section 6); a short session needs fewer exercises, never fewer regions. A repeated
  exercise, one outside the focus, or an ADVANCED one for a beginner profile is refused. Where
  the catalog has what is missing, the proposal is refused with what to add; only where it has
  nothing the user can do is the proposal made incomplete, and then its coverage, in the API
  response, says so (`complete: false`, with each limitation), whatever the reply says. The
  rules are coaching defaults, not medical ones. The catalog's imported records are linked to
  the equipment their instructions need where the record says "body only" (a pull-up bar, a
  bench, bars), and an imported copy of one of Formiq's own exercises suits no section
  (`app/catalog/classification.py`). A refused proposal is never kept, and an
  incomplete one waits for the user's approval like any other.
- **Only the user's own approval saves it** (`POST /coach/proposals/{id}/approve`, outside the
  coach). The approval is for the signed-in user only (another user's proposal is not found), must
  carry the binding the user was shown, is used once and expires. The stored proposal must still
  match its binding, and its own text is checked by the safety backstop again. Its row is locked
  while it is approved, and the plan is created and the proposal used up in one transaction
  through `WorkoutPlanService`, with its rules, each exercise in its section: two approvals at
  once save one plan, and a failed one saves nothing and uses nothing up. Every check fails
  closed.
- **Nothing the model, history or a tool result says authorizes anything.** An `approved=true` in
  arguments, a model-supplied user, a claim of earlier permission, a forged system message or a
  "yes" in the conversation is refused, or is no approval.
- The agent reaches only the read/propose/write classification. The tools build proposals, but
  never store, record or use a decision. The facts about stored proposals the coach runs with are
  `CoachContext.proposal_awaiting_approval`, a plain bool `CoachService` reads before the run, for
  the reply check, and `CoachContext.pending_proposal`, plain numbers from the same records (how
  long the latest waits, and the plan it would replace) that the instructions state so the model
  reads it before answering about it: nothing to call, store or decide with. The model reads the
  proposal itself with `get_pending_proposal`, for the request's user only, never with its id;
  when the turn read it and answered, the response shows it to the user again, as it is kept,
  with its own binding (the same approval, once). A proposal outlives a restart and is shared by every
  worker process, since it is kept in the database; `app/approvals` itself holds only the rules
  and reaches no data.

## 9. Observability

- **Langfuse is non-authoritative.** Tracing never changes a decision, safety, tools, retries or the
  response, and never makes a request fail: every tracing call is guarded, export happens in the
  background, and nothing recorded is read back.
- **Only safe metadata is traced:** counts, sizes, names, statuses, categories, the model name,
  token counts, the trusted user id and the request id, with strings and lists kept short.
- **Every turn has a trajectory** (`app.observability.trajectory`, described in
  `docs/agent-trajectory-observability.md`): its model requests and what each cost in tokens and
  time, its tool calls requested, executed, blocked and failed (never a blocked call among the
  executed), why a proposal was refused, the retry round and whether it rescued the turn, and
  how it ended, from Formiq's own state. It is kept whether or not tracing is on, goes to the
  trace's root as flat aggregates and short event codes, to the log as one JSON line, and to the
  playground's execution header. Recording it never changes the turn.
- **Never traced:** the message, the history, the instructions, reasoning, tool arguments' values,
  tool results, profile, workout or nutrition data, keys, passwords, tokens, or exception text.
- **Except, for development, with `LANGFUSE_CAPTURE_CONTENT` on** (off by default): Langfuse then
  also receives the message and history, the reply, each model request's instructions and
  conversation and the model's turn, the tools' arguments and results (the user's data included),
  and the validations' rejections. Keys, passwords and tokens are still never traced. It is
  allowed only with `APP_ENV` `development` or `test`: with any other environment, production
  included, the settings refuse to load (and `get_tracer` refuses to build a tracer, should they
  be changed after loading), so the privacy mask always applies there.

## 10. Known limitations

What is **not** guaranteed today:

1. **Authentication is minimal.** A token cannot be revoked before it expires (30 minutes by
   default); there is no logout, refresh token, key rotation, rate limiting or lockout. An email
   is one account whatever its case: sign-up stores it in lower case and refuses it in any case,
   and login matches it so; accounts made earlier that differ only in case are kept apart, and
   only the exact email logs in to one of them. No database constraint holds the rule for those
   earlier accounts (only the exact-email one). A new account gets its password at sign-up; an existing
   account's password is set or changed with a command, not through the API. Sign-up says whether
   an email already has an account, and nothing limits how often it is tried.
2. **The safety rules are keyword and threshold guardrails, not a medical classifier.** Negation is
   not read, and subtle risks are left to the model and the decision policy. A follow-up message
   without its own risk signal is not flagged.
3. **The fitness-only boundary depends on the model's classification,** apart from the veto for
   requests that name fitness (section 3), whose word list is short and precise: a fitness
   request in other words can still get the redirect, and an unrelated one using a fitness word
   goes back to the model.
4. **A running turn cannot be cancelled,** because the endpoint is synchronous; its reply is
   dropped and it holds nothing once it ends.
5. **Tracing gaps:** an interrupted request's trace has no final status; rendering in a live
   Langfuse project has not been verified. (Tool timing is measured for each call, and the
   counters no longer count a call refused for the per-turn limit among the executed: both
   changed on 2026-10-16, see the trajectory document.) A proposal's approval is its own request
   and keeps no id of the turn that made it: the two are joined by the proposal's short
   reference in their log lines.
6. **Proposals wait 30 minutes, and cannot be rejected.** There is no rejection endpoint (an
   unapproved proposal expires; the user's expired ones are cleared when they get a new one), and
   approving a plan for a day that already has one does not cancel the other.
7. **Limitations beyond pain are the model's to respect.** A proposal fits the user's stated
   equipment and time in code, and pain or injury is redirected before any tool runs. Leaving out
   an activity that conflicts with another limitation the user states (no kneeling, no jumping)
   is the model's choice: the catalog does not record which activities need either.
8. **"Today" is Formiq's UTC date.** The user's time zone is not known, so near midnight the
   current plan and the days since the last workout can be a day off for them.
9. **Deterministic tests use scripted models.** They prove what Formiq enforces whatever the model
   does, not how well a real model behaves. The optional live smoke run
   (`tests/integration/test_agent_scenarios.py`) checks only the enforced guarantees.
10. **What the user said about their equipment is read by phrase rules, in English.** A piece
    counts as theirs only with words that say so ("I have", "my", "with", "only", a plain list);
    other phrasings are missed, so a proposal naming that piece is refused until the model leaves
    it out. Only the conversation the model sees (its last 6 turns) is read.
11. **The reply checks read claims by their wording.** A false claim in words outside the making
    and changing verbs, or in another language, can still pass (the verbs are read in the past
    tense with the coach as the subject: "I'm proposing" or "I propose the following workout",
    and a synonym such as "I've submitted", are not read); a comparison's differences are
    worked out by Formiq (`changes`), but the reply that describes them is the model's.
12. **Proposals made before the 2026-10-15 fix pass** record no focus or revision kind: they are
    read back without their coverage, and are not shown to the user again.
13. **The explanation of a shown proposal is judged by the turn, not by every word.** In a turn
    that read the proposal awaiting approval for a user who did not ask for a change, a
    first-person description of how the coach designed it ("I added a warm-up") is allowed, so
    the check cannot tell it from the same words said of a change made now, except by the user's
    own message and the markers in `app.agent.trust`. The user is shown the proposal as it is
    kept, with the reply.
14. **An accepted proposal is still lost when the model's decision, not its reply, is refused at the
    limit** (an intent or decision the policy rejects, a call that is no decision, a clarification
    or a "cannot answer"), or when its card lacks the figures to say (section 6): the turn ends with
    the generic reply and no card. Only a refused reply is replaced, because only the reply is
    Formiq's to replace; the decision is the model's, checked, and is never taken for it.

Changing a guarantee here is an architectural decision: it needs an explicit decision, an update to
this document, and tests. It is never a test to relax.
