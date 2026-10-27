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
  that names one is rejected. It may name a plan (`workout_plan_id`, section 8): Formiq checks it is
  the signed-in user's own before anything else runs, and it never changes whose data is read.
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
  call is refused before it runs. Ids in history are not grounded. The one other id the turn may
  use is the plan the request names (`workout_plan_id`): the client's, but checked by
  `CoachService` before the run to be the user's own and PLANNED (section 8), so it is as grounded
  as an id a tool returned. It makes no other id usable.

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
  awaiting approval (`get_pending_proposal`: one the user could still approve, section 8), from
  Formiq's records for the request's user only: never its id, and reading it approves nothing.
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
- **A search says when it is cut, ranks activities by the workout, finds an exercise by name, and
  leaves out hidden duplicates** (live QA, 2026-10-19; `docs/warm-up-cool-down.md`). When more
  exercises match than the 15 returned, the output's `note` says "Showing 15 of N" and that the list
  is not all of them. In a warm-up or cool-down search the activities that fit the workout come
  first (easy CARDIO, then one whose primary muscle the workout trains, then one that works any of
  its muscles, and last one no main exercise suits, which no proposal accepts); a muscle asked for
  still comes before that. The workout is the muscles the user's latest message names
  (`app/tools/muscles.py`: known words only, and a muscle named with a "no", "without", "hurts" or
  "yesterday" is left out), and when it names none, the muscles of the main exercises the request's
  searches found. This only orders a search: no proposal is refused for it. `name` finds exercises
  by the words of their names (`app/tools/exercise_names.py`: plural, hyphen and case tolerant,
  never a near match; the coach is told to search by name without a `use`, so the exercise is
  found whichever section it is for); the name of a hidden duplicate finds the exercise the catalog
  keeps in its place (`DUPLICATE_OF`), first, with a note saying so (also when it is found only for
  another section); a name nothing has says that is not the catalog lacking the exercise. Formiq's hidden duplicates (`HIDDEN_DUPLICATE_IDS`: imported
  records of an exercise the catalog keeps under another name) are never returned by a search, with
  or without a use, nor counted in `total_matches`: they are still read by id and in saved plans.
  A blank equipment name is dropped (`[""]` reads as `[]`); a call the 10-call limit did not run
  says to ask again in the next round, before proposing. The coach is told never to give a number
  of calories burned (Formiq has no sourced figure for a plan; a prompt rule, not a guarantee).
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
  is refused unless the request or the conversation makes the plan clear (the plan the request
  names, its id or name, today's or the next workout for the current plan, or the plan the proposal
  awaiting approval revises): the coach asks which.
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
- **A reply says where a workout stands as the records do** (Phase 2.5, after the Phase 2.4 live
  pass). The reply check is given the state, not only the words (`app.agent.trust.Lifecycle`): whether
  the turn tried to propose and Formiq accepted none (a refused call is no proposal, whatever the
  model then wrote), how many proposals of the user's await approval that the request does not read,
  the PLANNED plans the turn read, and the plans an approval of the user's saved (the proposal rows
  that are APPROVED). Four rules follow, each by `reply_problem`:
  1. *Nothing is applied, saved, updated, adjusted or approved without the records.* The coach
     itself never did any of it ("I've applied your plan", "I've adjusted your workout", "I've moved
     your workout to Friday": always refused). A workout said to have become so ("Your workout is
     saved", "the changes are applied") is refused in a turn that made a proposal (it is only
     proposed), and where a proposal awaits approval unless the turn read a plan that an approval
     saved; otherwise "saved" and "scheduled" are backed by a saved plan the turn read, and the
     other words only by a plan an approval saved. Said conditionally or negated ("once you approve
     it, it is saved", "it is not saved yet"), it is no claim.
  2. *"No proposal awaits approval" is said only when none does.* With one that the request reads, it
     is refused; with others the request does not read (a request about one plan reads only the
     proposals that revise it), it may be said only of this workout ("none for this workout"), and the
     tool's own answer says the others exist (`get_pending_proposal`). With none anywhere it is said
     plainly.
  3. *A refused proposal presents nothing.* When the turn tried to propose and Formiq refused, a
     reply that presents a workout, version or change ("Here is a slightly harder version of this
     workout"), points to a card, or asks the user to review, approve or apply anything is refused;
     an earlier proposal still awaiting approval may be pointed to. Saying what could not be done and
     asking for what is missing are never refused.
  4. *Weights are the user's* (below, section 8): a reply cannot promise one the proposal cannot
     carry, because the proposal is refused first.
  What this adds is a state-based check on top of the wording lists, which remain: it holds whatever
  words a model uses for a state of things the records contradict (limitation 11 still applies to the
  rest of the wording).

- **A reply's claims are read on a normalized text, and held to the records' evidence** (Phase 2.7, after
  the Phase 2.6 live pass). Three things the older rules left open:
  1. *A workout's name decides nothing.* The claim patterns read the words between "your" and "workout"
     and the verb before them, and a name with quotes, an ampersand, parentheses or three words defeated
     them: "I have adjusted your "Core & Abs Focus" workout" passed, and so did the same sentence with the
     unquoted name "Core Abs Focus" (the pattern allowed two words there). The claims are now classified on
     the reply with every workout name the turn knows (Formiq's records: saved plans, the proposal awaiting
     approval, the plan a proposal revises, and the name the model gave its own proposal, accepted or
     refused: `app.agent.policy.workout_names`), every quoted span and every capitalised name before
     "workout" or "plan" read as one word (`app.agent.trust.normalize_claims`); "&" is "and". The reply
     itself is never changed, and the checks of text (the instructions, internal names, durations, the
     exercises a session shows done) read it as it is. A name in lower case, of several words, that no
     tool result carries and that is not quoted is still not read (limitation 11).
  2. *A truthful reference to the pending proposal is not a claim of a new one.* Before Phase 2.8A,
     "The harder version I proposed is currently awaiting your approval" was refused as a claim of a new
     version, causing an unnecessary model request. It is now accepted only when the sentence describes a
     proposal that current lifecycle evidence supports as pending and the record supports the descriptor
     (`pending_descriptors`: the words of its name, what it is (a revision is an updated, revised, changed
     plan; a new workout a new one), and the direction of what its comparison with the saved plan records,
     only when everything that changed moved the same way: more sets and fewer reps support neither "harder"
     nor "easier"). A failed or refused attempt is not evidence that a proposal exists, and an approved,
     rejected, expired, superseded, stale, or otherwise non-pending proposal cannot justify saying that it is
     awaiting approval. The coach saying it made or changed one ("I created a new version", "I just updated
     it") is always a claim, in the same sentence as a true one or not.
  3. *A claim about a plan is held to that plan.* "Plan 6 has been updated" is backed only by an approval
     that saved plan 6, not by one that saved plan 5 while plan 6's revision still waits; "saved and
     applied" is both words, each backed. More wordings of a thing being in effect or placed ("the change went
     through", "it's now on your calendar", "I've put it on your calendar") are held to the same records, and
     more of what became of a proposal ("expired", "was rejected", "no longer available") is held to
     whether one still awaits approval; a truthful "that proposal has expired" is no presentation of one.
  4. *Hedges are read where they stand, and markdown is not a disguise* (added after an independent review).
     A hedge BEFORE a claim makes it conditional or negated ("once you approve it, it is saved", "no changes
     were made"); after it only a condition does ("it is saved if you approve"), so "Your workout has been saved,
     so you can start whenever you're ready" is a claim. Emphasis (`**Core & Abs Focus** is saved`, `I've **saved**
     it`) and single quotes are removed or read as quotes before the claims are classified. More shapes are
     held to the records: "Your workout for Friday has been saved", "your workout's been updated", "I've saved it
     for you", "I've gone ahead and approved it", "it's now live", "Saved!"; and, with no proposal made, "I swapped
     the squats for lunges", "I made it harder", "the squats were replaced" (the object must be something a
     workout is made of: "I removed the guesswork" is the coach talking about its own words).
  5. *Truthful talk about proposals is not a presentation of one.* With none awaiting approval, "Would you like me
     to make a new proposal?", "Formiq refused my proposal", "that proposal has expired", "you approve proposals in
     the app" and "your approved proposal is saved" present nothing; a negation in one clause of a sentence is not a
     denial in another ("Nothing has been saved yet, and your proposal is awaiting your approval"); a sentence that
     calls the saved plan "your current workout" may call it saved beside a proposal that waits; and after a refused
     proposal, asking a question, offering choices ("Here are two options") or "I couldn't change it" present nothing.
  What each decides is still a fact of Formiq's: a refused or failed proposal call is no proposal (a
  result with no output, whatever the error), the pending proposals are the ones `approvable` returns
  (expired, rejected, superseded and changed ones are none), the saved plans are the ones the turn read.

## 6. Resource limits

Every request is bounded. As of Phase 5:

| Limit | Value |
|---|---|
| Tool calls a model turn may request | 20 (more makes the turn invalid) |
| Tool calls run per turn | 10 (the rest are refused; 8 until 2026-10-20): the reads and searches a workout needs, together, with two to spare |
| Rounds of tool calls per request | 5, and 1 more only to correct a refused proposal (below), so at most 7 model requests |
| Proposals accepted per turn | 1 (another is refused) |
| Graph steps | 15, a backstop beyond the longest legal turn |
| Items in a result | 15 search results (10 until 2026-10-20), 30 exercises, 15 sets, 12 instruction steps, 20 plans listed, 3 suggestions for each thing a refused proposal must correct; 500 characters of free text |
| Current message | 4,000 characters |
| Reply | 8,000 characters |
| A proposed plan | 1 to 10 main exercises of 1 to 10 sets of 1 to 30 reps, at most 300 s of rest, a weight only from the saved plan or the user's words (at most 500 kg, a bound on what they can state); today to 14 days ahead |
| Its warm-up and cool-down | 1 to 5 activities each, of 1 to 3 sets of 1 to 20 reps or 10 to 600 s (a held stretch, 60 s at most a set), no rest, and no weight of the model's (a saved activity's weight is carried on); at most 15 minutes each, and a warm-up of at least 3 unless the session is short |
| Its completeness | at least 4 different main exercises of 2 or more sets for a full body or a core (abs) workout, 3 for another focus, 2 when the user has under 30 minutes (a short session); when the user said how long they have, one more for each 6 minutes beyond 10 (at least 4 from 34 minutes, 5 from 40, never more than 5); variations of one movement (several crunches) count once; every region its focus needs; at least half the user's stated time, up to 45 minutes (Bug 2, 2026-10-27) |
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
- **A model request is at most 600,000 characters** (one round of the 10 largest results, and the
  rest; 500,000 for 8 results, until 2026-10-20). Over budget, the oldest tool results are compacted first; the latest round, errors and
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
  returned, bounded prescriptions, weights only from the saved plan or the user's words (below), and the user's stated time and equipment (what
  they have, `[]` for none, or what they cannot use, by the catalog's name, its plural or a common
  other name, `app/tools/equipment.py`: an unknown name is refused, never ignored, and a name for
  what the user has that negates or doubts itself, "no dumbbells", is refused too). What the user
  wrote about their equipment in the conversation holds whatever the model gives, however long
  ago they wrote it: the coach service reads it from every user turn the client sent (never a turn
  from "coach"; the latest word replaces an earlier one; "I only have dumbbells" and "all I have
  is dumbbells" mean nothing else), once, for the tools and for a bounded note to the model
  (`EquipmentSaid`, in the catalog's own names, within the note's 400 characters and only when
  turns were left out; the six-turn window is unchanged). The reading starts from the equipment
  saved in the user's profile (`user_profile_equipment` and `user_profiles.no_equipment`, read by
  `UserProfileService.get_saved_equipment` in the same step, before any model request): the saved
  list is what they have and nothing else, `no_equipment` is none at all, and a profile that never
  said (no list, not none; a profile made before equipment was kept) adds nothing, so such a user is
  held to nothing, as before. A turn of theirs replaces it piece by piece ("I also have a bench",
  "no bench") or as a whole ("I only have dumbbells", "I don't have any equipment"); what they say
  never changes the profile. `get_user_profile` also gives the model what the profile says
  (`equipment`: `LISTED` with the names, `NONE`, or `NOT_SAVED`; names, never an id). A piece they
  said they lack ("I don't
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
  which must change something (a different set, rep, rest or weight, or **another day**: Phase 2.5,
  below); or `ALTERNATIVE`, a different workout, which may keep a main
  exercise of the plan only when the catalog has no other the user can do for its part of the
  body: Formiq checks this, with no fixed share). The proposal records the plan's id and a digest
  of what it prescribes, and its response says what it keeps (`revision`). It changes nothing.
  **A revision keeps the day of the plan it revises** (Phase 2.3). Formiq's "today" is UTC, and a
  revision once took it as its day, so editing a workout planned for Friday moved it to today and, for
  a user whose own day is behind or ahead of UTC, the applied plan could leave Home (live QA,
  2026-10-23). Now the proposal's day is the plan's own, whatever it is (before today in UTC, or past
  the 14 days a new workout may be planned for). Another day is a move, which the model may make with
  `scheduled_date` only within those 14 days and only to THE day the user asked for (Phase 2.7, below:
  their own words are resolved to dates by rules, and the model's date must be one of them), or to the
  day of the proposal awaiting approval that revises the plan (a refinement carries a move on); else it
  is refused and the coach corrects it or asks. A plan with no day has none to keep, so the model must
  give one. The proposal's day, its `changes` (`scheduled_date_changed`, and the plan's own day in
  `compared_with_scheduled_date`) and the plan its approval saves agree. A new workout is as it
  was: today by default, or a day within the window.
  **A move to another day is a change on its own** (Phase 2.5). An `ADJUST` whose exercises,
  sets, reps, rest and weights equal the plan's was refused as unchanged whatever its day, so "move
  it to Friday" (the same workout, another day) could not be proposed (Phase 2.4 live pass). It is now
  unchanged only when the day is the plan's own too: the same exercises with another day the user
  named, within the window, is a revision, shown with `scheduled_date_changed` true and nothing else
  changed (`changes.identical` keeps its meaning: the exercises are the same, name and day apart).
  Moving a workout to the day it is already on is refused as unchanged, and the refusal says the
  plan is already on that day; with no day named, the refusal tells the model to ask which. The
  window, the user's-words rule and the plan-with-no-day rule are unchanged, and a date that is not
  a date is a validation error.
  **A revision keeps the plan's weights, and the model never chooses a weight** (Phase 2.5). A
  proposal could carry none, so every revision dropped the plan's weights (Phase 2.4 live pass). Now
  a proposed exercise has `weight_kg` (kg, or null), stored with the proposal, bound by its digest,
  shown by the API and the coach's reads, compared (a weight that differs is a change: a weight-only
  revision is a revision) and saved by the approval exactly as proposed; no migration, the plan
  column already holds it. A revision carries on the weight the plan has for the same exercise (same
  section and name) whatever the model left out. The model may give `weight_kg` only when the user
  did (`app.tools.weights`: a figure of theirs in kg or lb, rounded for pounds, or the plan's weight
  moved by a figure they gave: "add 5 kg"), or `remove_weight` only when they asked for none ("no
  weights", "without the weight", "bodyweight"); anything else is refused and the refusal tells the
  model to ask how many kg. With no conversation nothing is set or removed. The user sees each weight
  before and after in the card's changes, and only their approval saves it.
  Its approval saves the new plan and cancels the original in one transaction, with both rows
  locked, and only if the original is still PLANNED and unchanged: otherwise 409, nothing saved,
  and the proposal still pending. The original is cancelled, never edited or deleted.
- **The coach's dates are the user's own, and resolved by rules** (Phase 2.7, after the Phase 2.6 live
  pass: "tomorrow" came out as the wrong date in two of three first drafts, because the model was never
  told the date and Formiq only checked that the user had named *some* day; "the weekend" was answered
  with a day nobody chose).
  - *The calendar.* The coach's day is the user's LOCAL day in the IANA time zone the app sends with each
    message (`timezone` in the body of `POST /coach/message`, e.g. `"Asia/Kolkata"`). The name is
    validated against the time zone database (`app.schemas.timezone`: spelled as the database spells
    it, so "asia/kolkata" is refused on every platform) and a name that is not one is a 422, never
    replaced by UTC unseen. When the request sends none the day is the UTC day, and the instructions
    say so. The date comes from Formiq's clock once per request (`app.tools.coach_calendar`), and every
    date the tools show, compare or refuse is in that zone: "today", `days_from_today`, the 14-day
    window, and "days ago" for the last workout (its completion time is read in the same zone: it used
    to be a UTC date set against a local today). The two are never mixed. The app sends the device's
    zone (`frontend/src/api/timeZone.ts`) and, if the backend's database does not know it (a device
    newer than the server's tzdata), asks once more without it, so the coach is never unreachable for it.
    The zone comes from the client, so a client can pick which date it calls "today" by up to a day
    either way: that is bounded by what a user can do to their own data, and authorizes nothing.
  - *What the model is told* (`CoachContext.dates`, plain values: a date, a zone name, two flags). The
    instructions begin with Formiq's calendar for the request, in Formiq's own words, never the user's: today's
    date and zone, the 15 days from today with their weekdays and which is tomorrow, that the model must
    use these dates and never work one out, and what Formiq refuses.
  - *What the tools check* (`app.tools.schedule.read_requested_day`, `FormiqTools._checked_day`). The user's own
    turns (never a turn marked "coach", which the client could have written) are resolved against the
    calendar's today. **What a day is said OF decides whether it is where the workout goes** (added after an
    independent review): it is not when the user says where the workout WAS or cannot go ("from Monday",
    "instead of Friday", "not Friday", "my Saturday workout"), that they cannot or did ("I can't make it Monday",
    "I'm busy Saturday", "Monday doesn't work", "I did legs on Monday"), or when it only bounds a range ("Monday
    to Friday"); it is where it goes after "to", "for", "make it", "how about", "can we do", "put it on", and
    when it corrects ("no wait, Sunday"; the correction wins over "to tomorrow"). The day offered after one
    refused ("Monday doesn't work but Tuesday does") is the one asked for. Only a message that is plainly a
    request counts (it holds a marked day, or says only days and neutral words, or has a word for moving):
    "I ran on Thursday" and "exams are next week" name days and ask for nothing. The newest such message
    decides, so an answer to the coach's question settles "the weekend"; a message that names no day
    leaves the earlier one standing, unless it takes that day back ("no, not Monday": nothing is asked for; "not
    Saturday" after "the weekend": Sunday). One day: the model's `scheduled_date` must be that day, else the
    refusal names it ("the user asked for 'tomorrow', which is Wednesday 2026-10-14, not Thursday 2026-10-15: give
    scheduled_date 2026-10-14"). Several days: nothing is proposed and the refusal lists them, so the coach asks
    (`ASK_CLARIFICATION`) instead of choosing: a period ("next week", "the weekend", "next month" always), a
    weekday said on that same weekday (today, or in a week?), "next Friday" said earlier in the same calendar
    week (this week's, or the one a week later?), "Friday or Saturday", "Monday to Friday", a day given relative
    to another ("after Friday", "the day before Saturday"), a weekday that is not the day of the date beside it
    ("Friday, Oct 28" when it is a Wednesday: asked about even when the window leaves only one of them), a
    qualified weekday and a different date ("this Friday, Oct 30"). A day outside the window is said so, and no
    other is chosen for the user. A slash date that could be either order ("03/04"), or that looks like a ratio
    ("16/8 fasting", "Tabata 20/10") and has nothing pointing at it, is no day at all: the coach is told none was
    named, and asks. A bare weekday is the next one after today; a date without a year the next one on or after
    today; "3 days from now" and "a week from Friday" are counted.
  - *Where it applies.* A revision that moves a plan (always), a new workout or a plan with no day when
    the model gives a day other than today (the day must be the one the user named, when they named
    one; with none named the model may still choose within the window, as before). A new workout
    left without `scheduled_date` is for today, the default, whatever the user said: the model is
    told to give the date they named, and the card and the reply show the day, but Formiq does not
    refuse a missing date. A refinement of a proposal that already moves the workout carries its day on
    when the words name none, or leave it open among days that include it.
- **A move that only names a day changes nothing else** (Phase 2.7: the live pass saw "move it to tomorrow"
  proposed with other exercises, and the reply did not say). When the user's newest message is made only of
  day words and neutral move words ("Can you reschedule it for Friday, please?", `is_date_only_request`:
  positive and conservative, any other word means it may ask for more) and no proposal for the plan waits, a
  proposal that moves the plan must prescribe exactly what the plan does: every exercise, set, rep, time,
  rest and weight (`prescribed`), else it is refused ("the user asked only to move workout plan N to
  Friday 2026-10-16: keep every exercise, set, rep, rest time and weight exactly as the plan has them"). A
  proposal waiting for the plan makes the message a refinement, which keeps the changes the user is looking at;
  an earlier request for changes that no proposal kept does not carry into a message that only moves it. The
  name is not held (a decoration is shown only when it is a different name), and a message with any other word
  is not held at all, as before.
- **A newer proposal for a saved plan supersedes the user's earlier pending ones for that plan** (Phase
  2.7, after the Phase 2.6 live pass: refining a pending date-only proposal left two pending cards for
  one workout, and approving one cancelled the plan the other revised). When a proposal that revises a
  saved plan is kept (`PlanProposalService.register`), the same user's PENDING proposals that revise
  that same plan become `SUPERSEDED` (a status of the existing text column: no migration). They are no
  longer listed or read by the coach, approving one is a 409 that says it was replaced, and rejecting
  one is a 204 that changes nothing. Only those: a new workout, another plan's proposal, another
  user's, and one already rejected or approved are untouched. Proposals are registered one at a time for
  each user (their row is locked, `FOR NO KEY UPDATE`, so their other rows can still be written), so two
  refinements at once leave one PENDING (the last kept), an approval that wins the race is never
  superseded, and nothing deadlocks. A superseded row expires and is cleared like a rejected one.
- **A request may name the plan the user is changing** (`workout_plan_id` in the body of `POST
  /coach/message`, null or left out for none). `CoachService` checks it before anything else runs,
  so before any model request and before the request is traced: the plan must be the user's own
  (another user's, or a missing one, is `WorkoutPlanNotFoundError`, a 404 that does not tell them
  apart) and PLANNED (`WorkoutPlanNotRevisableError`, a 409). It then reaches the run only as
  `CoachContext.target_plan_id`, a plain id outside the state, which the model can neither set nor
  change. The instructions say of it only its number (`target_note`: never its name, which is the
  user's text); it is an id the turn may use (section 2); and the tools hold the proposal to it:
  `propose_workout_plan` refuses a proposal whose `revises_plan_id` is anything else, or none, so
  the coach corrects it within the turn or proposes nothing. The conversation then does not have to
  name the plan (section 5). It authorizes nothing: the plan is still replaced only by the user's
  approval. It is also what the request's proposals are: the proposal the coach is told
  awaits approval, reads with `get_pending_proposal` and shows again is the latest one that revises
  the named plan (a newer version of its workout), never another plan's revision or a new workout,
  which the user may still approve themselves; with none, the read says there is none for that plan
  (Phase 2.3: before it, a request about plan A could be answered with plan B's proposal, live QA
  2026-10-23). A request that names no plan reads the latest of any. A flagged request is answered
  as any flagged request is: the note is not given and no tool runs.
- **A proposal's response says what it changes** (`changes`, `revision.replaces_plan_estimated_minutes`).
  Formiq compares the proposal with the plan it replaces, as that plan is now, by section and
  exercise (`app/tools/comparison.py`: the one comparison, which the coach's own `changes`
  (`get_pending_proposal`, `get_workout_plan` with a plan to compare with) are told from, so the
  coach is held to what the API shows). Each side's prescription is given as its numbers (sets,
  reps or seconds, rest, weight) and as one line; a weight that differs is a change (a proposal
  carries its plan's weights on, so one is dropped only when the user asked for none). The plan's length is worked out by the formula of a proposal's
  `estimated_minutes`: a plan stores none. A new workout has neither (null), and so does a revision
  whose plan is no longer as it was proposed against, since approving it would be refused: the
  response never compares with a plan the proposal was not made for. A proposal stored before
  Formiq recorded how it revises a plan has no revision to show.
- **The user can find the proposals still waiting** (`GET /coach/proposals/pending`): the
  signed-in user's proposals, the most recently made first, each as it was shown with the same
  binding, built from the stored values by the same view the coach reads (`app/tools/proposal_view.py`).
  Only the proposals `approve()` would not refuse for the proposal itself: PENDING, unexpired, as
  stored (its binding still matches), its text safe again, its exercises still active, and, for a
  revision, a plan still PLANNED and as proposed. It leaves out expired, approved, rejected and
  changed ones, and those made before 2026-10-15, which record no focus and so cannot be shown as
  they were. This is the one rule for what awaits approval (`PlanProposalService.approvable`): what
  the coach is told waits, what `get_pending_proposal` reads and shows again, and whether a reply may
  point the user to a proposal all use it, so the coach is never shown a proposal this list omits and
  a proposal whose plan changed is not shown again (Phase 2.3; before it the coach read any PENDING,
  unexpired one, and approving what it showed was then a 409). A stored proposal that cannot be read
  back is left out and logged by its short reference. Several can wait, each for its own saved plan or
  as a new workout (a refinement of a plan's proposal supersedes the older one: above); the
  list gives them all, and none is chosen. It reads only: nothing is proposed, approved, rejected
  or changed.
- **A proposal is a complete session for its focus, judged in code** (`app/tools/completeness.py`).
  The model names the focus (full body by default, or upper body, lower body, push, pull or
  core); each main exercise belongs to the body regions of its primary muscles, and covers a
  region only when one of them is a main mover of it (never a secondary muscle, and never an
  accessory such as the forearms, biceps, triceps or calves). A full-body workout covers the
  lower body, an upper-body push and an upper-body pull, with enough different
  exercises (section 6); a short session needs fewer exercises, never fewer regions. Different
  exercises means different movements (`completeness.movement_key`: the noun of the name and the
  primary muscles): a crunch, a reverse crunch and a cable crunch count once, so variations of one
  cannot make a core workout look complete, and a refusal for it names them. A repeated
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
- **An approval is safe to repeat.** The same user sending the binding of a proposal that was
  approved gets the plan that approval saved, with 200 where the first answer was 201 (ownership
  and the binding are checked first, as for any approval), so a client whose answer was lost learns
  what happened and never has to guess. Nothing is written and no second plan can be made, even by
  requests that race: they wait for the row. The plan is returned only while it is still the
  user's, PLANNED, and prescribing exactly what the proposal did (name, day, every exercise as
  prescribed, weights included); changed, cancelled or removed since, the answer is a 409 and not "done".
  It is not refused for being older than 30 minutes: the expiry limits accepting a proposal, not
  finding the plan it saved.
- **The user may reject a proposal** (`POST /coach/proposals/{id}/reject`, with the binding they
  were shown): it becomes REJECTED, under the row's lock, so it cannot be approved (409), is not
  listed, and is not seen by the coach (`get_pending_proposal`, `awaiting_approval` read PENDING
  only), and the same workout may be proposed again. Rejecting again is no error (204) for as long
  as its row is kept. Another user's proposal is not found (404), and neither is one that is not there:
  an expired proposal's row is cleared when its user next gets a new one (pending or rejected, never an
  approved one), and from then on rejecting or approving it is a 404, as for a proposal that never was.
  Another binding, or a proposal already approved, is a 409: an approved proposal's plan is saved. An
  approval and a rejection that race have one outcome. An expired proposal may be rejected while its
  row is kept. REJECTED is a status of the
  existing text column (no constraint names its values), so it needed no migration. The proposal's
  states: PENDING until approved, rejected, superseded or expired; APPROVED; REJECTED; SUPERSEDED
  (a newer proposal for the same saved plan replaced it: above).
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
  and reaches no data. The one other fact the coach runs with is `CoachContext.target_plan_id`, a
  plain id (or none) that `CoachService` checked from the request body: it reaches no approval
  either. The same holds for `CoachContext.dates` (Phase 2.7): a date, a time zone name and two
  flags, worked out by `CoachService` from Formiq's clock and the validated zone, never from the
  user's or the model's text.

## 9. Observability

- **Langfuse is non-authoritative.** Tracing never changes a decision, safety, tools, retries or the
  response, and never makes a request fail: every tracing call is guarded, export happens in the
  background, and nothing recorded is read back.
- **Only safe metadata is traced:** counts, sizes, names, statuses, categories, the model name,
  token counts, the trusted user id (the trace's user, `user.id`; the trajectory's summary, events
  and log lines carry none) and the request id, with strings and lists kept short.
- **Every turn has a trajectory** (`app.observability.trajectory`, described in
  `docs/agent-trajectory-observability.md`): its model requests and what each cost in tokens and
  time, its tool calls requested, executed, blocked and failed (never a blocked call among the
  executed), why a proposal was refused, the retry round and whether it rescued the turn, and
  how it ended, from Formiq's own state. It is kept whether or not tracing is on, goes to the
  trace's root as flat aggregates and short event codes, to the log as one JSON line, and to the
  playground's execution header. Recording it never changes the turn.
- **Never traced:** the message, the history, the instructions, reasoning, tool arguments' values,
  tool results, profile, workout or nutrition data, keys, passwords, tokens, or exception text.
- **Local debugging is a sink of its own** (`AGENT_DEBUG`: `off` by default, `events`, `content`;
  `docs/agent-debug.md`). It prints a turn to the developer's terminal (stderr), never to Langfuse,
  a file or a service, and never through `LANGFUSE_CAPTURE_CONTENT`, which it neither sets nor reads:
  a tracer that has it keeps the backend and the capture setting it was configured with. The
  settings refuse it, rather than ignore it, outside `APP_ENV` `development` or `test`, and when
  `APP_ENV` is not set at all (its default, `development`, says nothing of where the application
  runs); building it checks again. It is written to and never read back, and a failure in it
  (a stream, a builder) is logged by its type and changes nothing: not the model's input, the
  tools, the limits, the decisions, the API's answer or the approval of a proposal. What it prints
  is decided by allowlist: Formiq's own constants and replies, the declared names and values the
  model used, and numbers, ids, dates and catalog data; the user's message and history, the model's
  text and reply, plan names, notes, tool error messages, profile and identity fields, and any
  other string are only a role, a size and (at `content`) a hash keyed for the process; the full
  proposal id, its binding, exception text, keys, passwords and tokens are never printed. Its
  output is bounded and says, with a marker, when something is not captured, unavailable,
  redacted or truncated. Its defaults and refusals, and its independence from the tracing
  backends, are pinned in `test_agent_contract.py`.
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
6. **Proposals wait 30 minutes; only a newer revision of the same plan supersedes one.** The user may
   reject one (section 8), and an unapproved proposal expires (the user's expired ones, rejected,
   superseded or not, are cleared when they get a new one). A proposal that revises a saved plan
   supersedes the user's earlier pending ones for that plan (section 8, Phase 2.7); a new workout has no
   plan and supersedes nothing, so two proposals for new workouts can both be approved, and approving a
   plan for a day that already has one does not cancel the other. A user who approves an older card on
   a screen that has not refreshed gets a 409 that says it was replaced. A rejection records no time
   (`REJECTED` is a status only; the table has no `rejected_at`).
7. **Limitations beyond pain are the model's to respect.** A proposal fits the user's stated
   equipment and time in code, and pain or injury is redirected before any tool runs. Leaving out
   an activity that conflicts with another limitation the user states (no kneeling, no jumping)
   is the model's choice: the catalog does not record which activities need either.
8. **The coach's "today" is the user's day only when the app says where the user is** (Phase 2.7,
   section 8). It is the local day in the IANA zone the app sends with a coach message; without one it
   is the UTC day, which can be a day off for the user, and the coach is told so. The zone is the
   client's word (bounded to a day either way, for the user's own data). Only the coach uses it: other
   endpoints (the plan and session routes, the recovery summary, the app's own Home) keep the dates they
   had. The backend's time zone database must know the device's zone (an older tzdata refuses a newer
   zone with a 422; the app then sends the message without it). A user who travels across zones in a
   conversation gets the zone of each message.
9. **Deterministic tests use scripted models.** They prove what Formiq enforces whatever the model
   does, not how well a real model behaves. The optional live smoke run
   (`tests/integration/test_agent_scenarios.py`) checks only the enforced guarantees.
10. **What the user said about their equipment is read by phrase rules, in English.** A piece
    counts as theirs only with words that say so ("I have", "my", "with", "only", a plain list);
    other phrasings are missed, so a proposal naming that piece is refused until the model leaves
    it out. Only the conversation the model sees (its last 6 turns) is read. The equipment saved in
    the profile is read as the whole list the user chose: a piece they did not choose is taken as one
    they lack until they say they have it, so a user who forgot a piece is offered fewer exercises,
    never one they cannot do. The app has no screen to change the saved equipment after setup yet.
11. **The reply checks read claims by their wording.** A name in quotes, with punctuation or of several
    words is one word to the claims (Phase 2.7), but a name that is in lower case, of several words, in
    no tool result and not quoted ("your push pull legs workout") can still slip between "your" and
    "workout". Refused on purpose, at the cost of a retry and never a false claim (older tests and live incidents
    pin them): "I've created / set / added ... your workout" after a proposal; a first-person "I added Bird Dog
    because it needs no bench" about a pending card the record does not show changed; an unsupported statement
    that a harder version is awaiting approval; "Done! ..."; "your profile has been
    updated". A false claim in words outside the making
    and changing verbs, or in another language, can still pass (the verbs are read in the past
    tense with the coach as the subject: "I'm proposing" or "I propose the following workout",
    and a synonym such as "I've submitted", are not read); a comparison's differences are
    worked out by Formiq (`changes`), but the reply that describes them is the model's.
12. **Proposals made before the 2026-10-15 fix pass** record no focus or revision kind: they are
    read back without their coverage, and are not shown to the user again, nor listed by `GET
    /coach/proposals/pending`, nor read by the coach as awaiting approval (they can still be approved
    with the binding they were shown).
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

15. **The local debug output is a developer's tool, not a safeguard.** Its allowlist is strict but it
    shows what the tools return that is not private (numbers, ids, exercise names, the structure of a
    workout), its patterns for emails, phone numbers and ids are best-effort and apply only to what
    is shown, a terminal that blocks blocks the turn writing to it, and rendering adds to the time
    of the turn (not to the model's measured time). The settings keep it out of any environment that
    sets `APP_ENV` to anything but `development` or `test`; that depends on `APP_ENV` being set
    correctly, as `LANGFUSE_CAPTURE_CONTENT` does. Nothing here lets a developer see a turn's exact
    unredacted words: that would be a separate, approved design.

16. **A request that names no plan is not bound to a proposal.** The coach reads the latest proposal
    awaiting approval of any plan, or of none, and which of several the user means is the model's to
    ask about (the app lets the user choose one and asks for changes to it, which names its plan from
    then on). A request that names a plan reads only proposals that revise it (section 8). Which plan
    the model reads or describes beyond that is the model's, checked only by the id rules of section 2.

17. **An approval repeated after the saved plan was edited is a 409, not the plan.** A user who
    approves, changes the saved plan, and then retries a lost answer is told the proposal was
    already approved and the plan changed; the plan is theirs to find in their plans.

18. **A move to another day rests on the user's words, read by phrase rules** (Phase 2.7 changed what is
    checked: the model's date must be the day those words name, not merely follow a day word; an independent
    review of about 330 phrasings, 97,000 date checks and 180,000 fuzzed inputs found the date arithmetic sound
    and the reading of what is said of a day wanting, which section 8 now describes). English only, known words
    and forms; what the rules do not read leaves the workout on its day, or asks, which is the safe way to be
    wrong. Known limits: "a day later", "push it back a day", "the next day" and "a couple of days" are relative
    to the plan's own day or vague, and name none; "from tomorrow make it shorter" reads "from" as where it
    leaves; a day named for another reason ("I have a race on Saturday, can you make it lighter?") is a day
    named for the move only if a word marks it ("to", "for", "make it ..."), and the workout is otherwise
    asked about or left; a ratio of the form "30/10 intervals" is read as a date only when a word points at it
    ("on 30/10") or nothing else is said; a bare weekday said on that weekday, "next <weekday>" within the same
    week and every period ask even when the user would not have minded; a new workout left without
    `scheduled_date` is for today whatever they said (the card and the reply show the day); and a day that is
    the plan's own is no move and is never checked.
19. **Weights rest on the user's words, read by phrase rules** (Phase 2.5). Digits and the units kg
    and lb only, in English ("twenty kilos" is not read); a figure is not tied to an exercise, so a
    figure the user gave for one exercise explains the same weight on another, and the card's
    changes are what the user checks. The coach sets a weight on main exercises only (a saved
    warm-up or cool-down activity's weight is carried on, never set), and a weight of at most 500 kg.
    A phrasing the rules miss leaves the plan's weight as it is, which is the safe way to be wrong.
20. **A move of a saved plan is a complete proposal.** There is no coach tool that edits a plan's day:
    the move is proposed as the whole workout again, so it passes every completeness check a new
    proposal does (a plan saved some other way, such as a warm-up under three minutes, can be
    refused for that until it is changed with the day), and approving it still saves a new plan and
    cancels the old one.
21. **The reply's state checks are judged by the records and by wording** (Phase 2.5). What a
    reply may say is saved or applied is decided from the proposals and plans Formiq holds, but
    the claims are found by phrase rules in English (section 5): a state said in words they do not
    know can pass (limitation 11). The coach cannot see an approval happen, only the plan it saved,
    so it may say "applied" or "updated" only of a plan an approval saved that the turn read, and a
    plan the user changed after approving it is still "saved" by that rule.

22. **What the record supports calling the pending proposal is its name and the direction of its
    changes** (Phase 2.7, section 5). A sentence that says the proposal awaits approval may call it "the
    harder version" when its name carries the word (the model chose that name, so it is the card's own
    title) or everything that changed moved up. It does not check a word the record cannot show
    ("a more fun version"), the size of a change, or that every word of a long sentence is true; the card
    the user is shown with the reply is what they check. A word in the same sentence that no record
    supports ("the easier version") is refused, and the coach saying it made one is always refused.
23. **What became of a proposal is backed only for the cases that bar a claim.** A reply may not present
    a proposal that expired, was rejected or was superseded as awaiting approval (`awaiting_approval` is
    false for them), and may not deny one that waits. A reply that says a proposal "expired" or "was
    replaced" when none ever existed is not refused: the records the reply check holds are the pending
    ones and the approved plans, not a history of every proposal.

24. **"Only a move" is decided by a short list of neutral words** (Phase 2.7). A message of the form "move it
    to Friday" holds the proposal to the plan's exercises; one that adds any word outside the list ("and use
    my dumbbells", "I'm tired") is not held, and then an unrequested change can still be proposed (the card's
    changes show it). A user who asked for changes earlier and now only moves the day, with no proposal
    waiting, gets the plan as saved, moved.

25. **A workout's quantity is judged in code; its prescription and cues are the model's** (Bug 2,
    2026-10-27). How many different exercises a proposal needs follows its focus and the time the user
    said they have (section 6), capped by what the catalog has for their equipment and experience,
    and a catalog with fewer makes an incomplete proposal that says so. Rest and notes stay optional
    in a proposal, and the instructions ask the model for both: a proposal with none is accepted,
    and a cue (notes) is the model's own text, never checked against the exercise's catalog steps.
    A main exercise has reps, not a time, so a plank is prescribed as reps (a timed main exercise
    needs the schema to change). Whether a model does as the instructions ask (propose the
    workout it was asked for instead of listing exercises, aim above the minimum, give rest and
    cues) is not enforced and was not verified live. "Different movements" is a heuristic of the
    exercise's name and primary muscles: it can merge two exercises a coach would tell apart (a
    lateral and a front raise) and miss two that are one (an exercise with another noun); it only
    decides how many count, never whether an exercise suits the user.

Changing a guarantee here is an architectural decision: it needs an explicit decision, an update to
this document, and tests. It is never a test to relax.
