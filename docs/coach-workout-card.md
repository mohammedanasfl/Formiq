# The AI Coach's workout card: contract, lifecycle and limits

What the app's AI Coach screen shows when the coach proposes a workout (a new one, or a revision of a saved one), which
parts of the backend's contract that rests on, how the screen is connected to it, and what is still missing.

Checked 2026-10-22 against the backend as Phase 2.1 changed it: `backend/app/schemas/coach.py`, `api/routes/coach.py`
(`POST /coach/message`, `GET /coach/proposals/pending`, `POST /coach/proposals/{id}/approve` and `/reject`), and the
payloads that backend writes. This document says what the app relies on; the backend's own rules (how a proposal is
compared, what makes one approvable, the agent's handling of the target workout) are in
`docs/agent-production-contract.md`.

**Status.** The screen has two coaches behind one interface (`CoachGateway`): the backend's (`src/coach/apiGateway.ts`,
the default) and a made-up one for previews and tests (`src/mock/`, started with `EXPO_PUBLIC_COACH_MODE=mock`). The
connected path was verified in these ways, and none called Gemini or a database of the app's own: Jest, with the real
screen, gateway and API client over a scripted `fetch`; the app's strict readers run against JSON written by the
backend's own response models (`frontend/__tests__/fixtures/*.json`) and, in a one-off check that is not kept in the
repository, against answers the real routes wrote (a scripted model on the test database: a revision with a weight-only
change, a revision with added warm-up and cool-down walks, a new workout, the pending list with none, one and two
proposals, and an approval answered 201 and again 200 with the same body); and the real app on an Android emulator
against a throwaway stub that answers in those shapes. **What was not verified: the live coach.** Whether Gemini, given a
conversation and a target workout, proposes a revision of that workout is the backend's behaviour; the backend holds the
model to the target in code, and the scripted-model tests prove that enforcement, not how well a real model behaves.

## 1. The contract the card rests on

| Step | Route | Request | Answer | Notes |
| ---- | ----- | ------- | ------ | ----- |
| Ask the coach | `POST /coach/message` | `{ message, history[], workout_plan_id?, timezone? }`, nothing else (`extra="forbid"`) | `{ reply, proposal? }` | `message` 1 to 4000 characters, `history` at most 50 turns of at most 8000, `role` is `user` or `coach`. `workout_plan_id` is a strict positive integer, sent only when the conversation is about a saved workout. `timezone` is optional and must be a recognized IANA timezone such as `Asia/Kolkata`; an invalid value is 422. With a valid timezone, coach dates use the user's local calendar day; when omitted, they use UTC. Before any model request the backend checks the plan: 404 when there is no such plan for this user (another user's included), 409 when it is not PLANNED, 422 when malformed. 502 when the model cannot answer, 503 when no key is configured. |
| List what waits | `GET /coach/proposals/pending` | none | `{ proposals[] }`, the most recently made first, each a proposal plus `created_at` | Only proposals that can still be approved: pending and unexpired, with valid records and a current revision target. Expired, applied, rejected, superseded, and stale proposals are omitted. `[]` when none. Reads only: nothing is proposed, applied or rejected by asking. |
| Apply | `POST /coach/proposals/{proposal_id}/approve` | `{ binding }`, 64 hex digits | 201 `WorkoutPlanResponse` (the saved plan); **200 with the same plan** when the same user asks again after an approval and the plan it saved is still as saved | The only route that saves a workout. 404 unknown or another user's proposal. 409: expired (30 minutes), a different version than shown, rejected, already approved but the saved plan changed since, the replaced plan changed or cancelled, no longer saveable. |
| Dismiss | `POST /coach/proposals/{proposal_id}/reject` | `{ binding }` | 204, no body | Idempotent: repeating it is 204, and so is a proposal that expired but is not cleared yet. 404: unknown, another user's, or cleared after it expired. 409: already approved, or a binding for another version. Saves nothing and changes no plan. |

`WorkoutPlanProposalResponse`: `proposal_id`, `binding`, `expires_at`, `name`, `scheduled_date`, `exercises[]`
(`exercise_order`, `section`, `exercise_id`, `exercise_name`, `equipment[]`, `sets`, `reps` or `duration_seconds`,
`rest_seconds`, `notes`), `warm_up_minutes`, `main_minutes`, `cool_down_minutes`, `estimated_minutes`, `coverage`
(`complete`, `focus`, regions, `limitations[]`), and the two that make a revision readable without a second request:

- `revision`: `replaces_plan_id`, `replaces_plan_name`, `kind`, `kept_exercises` and
  **`replaces_plan_estimated_minutes`**, how long the plan it replaces takes by the formula behind `estimated_minutes`
  (null when it could not be worked out). `null` for a new workout.
- **`changes`**: how the proposal differs from that plan, worked out by the backend (the comparison the coach itself is
  held to): `compared_with_plan_id`, `compared_with_plan_name`, `compared_with_scheduled_date`, `added[]`, `removed[]`,
  `changed[]` (each `{ section, exercise_name, before, after }`, a prescription being `{ sets, reps, duration_seconds,
  rest_seconds, weight_kg, summary }`), `unchanged[]` (names), `name_changed`, `scheduled_date_changed`, `identical`.
  Null for a new workout, and when the backend could not compare (the plan is not as it was when proposed). A weight the
  saved plan has and the proposal does not is a change: a proposal sets none.

Both are always present in an answer, null when they do not apply, so the app never infers either.

Lifecycle, as the backend keeps it and as the app relies on it:

- A proposal is PENDING until it is approved, rejected, superseded, or 30 minutes old. Nothing is saved by proposing.
- Approving saves a new PLANNED plan and, for a revision, cancels the replaced plan in the same transaction. The
  original is cancelled, never edited or deleted. Approving the same proposal again, with its binding, by its user, returns
  the plan that was saved (200) as long as that plan is still as saved: that is how an approval whose answer was lost is
  recovered, with no guessing. Otherwise 409.
- Rejecting makes it REJECTED: it is no longer listed, no longer offered to the coach, and cannot be approved (409).
  Rejecting an approved proposal is 409.
- A refinement registers a NEW proposal. During that registration transaction, older PENDING revisions for the same
  user, action, and saved plan are marked `SUPERSEDED`; they are no longer actionable, listed, or readable by the
  coach, and attempting to approve one returns a conflict. New-workout proposals and proposals for other plans are
  not superseded. Only the newest same-plan revision remains actionable.
- The coach refines the NEWEST proposal waiting for the user; the request carries no proposal.

## 2. What the app builds on it

`frontend/src/coach/`: the pure parts call nothing; only `apiGateway.ts` reaches the backend (through `src/api/coach.ts`):

- `proposalChanges.ts`: how the card WORDS the backend's `changes`. It decides nothing about what differs: it puts the
  backend's lists in the order a person reads a workout (warm-up, main workout, cool-down, then the length and the day),
  pairs a removed and an added exercise of one section as "Replaced A with B", and, for an exercise the backend lists as
  changed, says which of its numbers moved ("3 sets → 4 sets", "30 s → 40 s", "45 s rest → 60 s rest", "20 kg → no
  weight"; the backend's one-line `summary` of both when none of those numbers differs, so a change it listed is never
  dropped). The length is said to stay or change only when `replaces_plan_estimated_minutes` is known; the day only when
  `scheduled_date_changed`. The app has no comparison rules of its own: they were removed.
- `proposalCard.ts`: the card's content from a proposal alone. An exercise is marked New or Changed when the backend lists
  it as added or changed, by section and exact name.
- `chatState.ts`: one reducer for every state a card has (`ready`, `applying`, `applied`, `apply-failed`, `rejecting`,
  `rejected`, `reject-failed`, `expired`, `superseded`), a pending request, a failed one, the proposals found waiting,
  and the workout the conversation is about. `useCoachChat.ts` runs it against a `CoachGateway` (`gateway.ts`): `send`,
  `pending`, `approve`, `reject`.
- `WorkoutProposalCard.tsx`: the one card for every state. Labels: `New Workout`, `Updated Workout`, `Applied`,
  `Dismissed`, `No longer waiting`, `Older version`, loading ("Preparing your workout"), "Couldn't create the workout".
  Actions: `Apply This Workout` or `Apply Updated Workout`, `Ask for More Changes`, `Dismiss`, `Try Again`,
  `Dismiss Again`. `WaitingProposals.tsx`: the list to choose from, and the notice for a failed look.

How the screen is connected (`src/api/coach.ts`, `src/coach/apiGateway.ts`, `ConnectedCoachScreen.tsx`):

- **The four calls.** `sendCoachMessage` (90 s timeout: one coach turn can take up to seven model requests),
  `getPendingProposals`, `approveProposal` and `rejectProposal` (15 s each). The user comes from the token. The id and
  binding of an approval or a rejection are checked (32 and 64 hex digits) before they are sent.
- **Answers are read in full or refused** (`ApiError` `invalid-response`). A proposal missing a required field, with an id
  that is not 32 hex digits, a binding that is not 64, an unknown section or focus, an exercise change with the wrong
  sides (an "added" one that has a `before`), or `changes` that are not of the plan the proposal replaces, never reaches a
  card; the whole pending list is refused if one item is damaged, since a missing one would be taken for one that is not
  waiting. What the backend legitimately sends as null (`proposal`, `revision`, `changes`, `reps`, `duration_seconds`,
  `rest_seconds`, `notes`, `replaces_plan_estimated_minutes`, `compared_with_scheduled_date`, `weight_kg`) reads as null.
  An answer with neither words nor a workout is an error, not an empty bubble.
- **How an edit finds its workout.** "Edit with AI" opens a conversation about a saved plan (`CoachContext.workoutId`, a
  numeric plan id). The id is sent as `workout_plan_id` with EVERY message of that conversation (a try again included,
  and a change to what came back), and the backend holds the coach to it: the proposal revises that plan and no other. The
  screen's own question ("What would you like to change in “…”?") is shown and is not sent as something said. A
  conversation about no workout, or about an example workout with no saved id, sends none. When a revision of the workout
  is applied the plan it replaced is cancelled, so the conversation moves to the plan the backend saved (its id and
  name) and the next change is to that; the "Opened from…" note goes then. A 404 or 409 to a message sent WITH a workout is
  the workout ("This workout can't be edited any more — it was replaced or cancelled. Start over to pick another."),
  told by what was sent, never by the wording of the backend's detail, with no Try Again. A card still says so when its
  proposal replaces another workout than the one the conversation is about ("This replaces “Leg Day”, not “Core & Abs
  Focus”, which you opened the coach from"): the backend enforces the target, and the card shows the rest rather than
  hiding it. Opening Edit with AI for another plan starts a new conversation; for the same plan (or the plan that replaced
  it) it carries on. A conversation opened from no workout (after a restart or a new sign-in, or Start over) is about none,
  and the app remembers none between conversations. It becomes about a saved plan (Phase 2.3) when the person asks for
  changes to a card that replaces one: `Ask for More Changes`, or a suggested change on that card. Its messages then name
  that plan like any other conversation's, the typed ones included, and the backend reads that plan's proposals only.
  Nothing else makes it about one: not a card being on the screen, not being the newest, not a list of waiting workouts, and
  a message with no change asked of a card names none. A card for another plan than the one being edited, or a new workout
  in a conversation about a plan, can only be applied or dismissed, and says so ("This isn't a change to “Core & Abs
  Focus”, which you're editing, so the coach can't change it here. …").
- **Refinement** is the same call with the whole conversation as history (what was said, as text; a card is not text and
  is not sent). The new proposal gets a new card, the old one becomes "Older version", and its Key Changes are the
  backend's comparison with the original saved workout. The app reads no saved plan at all.
- **Dismiss.** `Dismiss` is on a card wherever Apply is (ready, and after a failed apply or dismissal that can be tried
  again). It shows `Dismissing…` and is `Dismissed` only after the backend answered 204; "Nothing was saved, and “X” is as it
  was." A lost connection, a timeout or a 5xx keeps the card waiting with `Dismiss Again` (rejecting is idempotent, so
  trying again is safe); a 404 ends it as "No longer waiting" (it expired), never as dismissed. A 409 "already approved" (the
  answer to its approval was lost) is not reported either way: the app asks the approval again, which saves nothing and
  returns the plan it saved (the approval is safe to repeat), and the card becomes `Applied` with that plan and Home is
  told; only if that fails is it said ("already applied" for a plan changed since, a lost connection can be tried again).
  A 409 for another version of the proposal says it was already applied or changed, and is neither dismissed nor applied;
  an applied card is never turned into dismissed, expired or failed by a late answer. One dismissal at a time, no message or apply or Start over
  while one is under way, and one press sends one request.
- **Recovery.** Proposals that were waiting before the conversation, which the backend still has after the app is closed,
  the person signs out, the tab is left or the conversation is cleared, are fetched with the pending list when the
  connected AI Coach is first shown, each time it is shown again after another tab, after Start over, and on a retry.
  Never while a message, an apply or a dismissal is under way, one request at a time, a late answer dropped after Start
  over or when the screen is gone. One proposal is shown as its card after a line saying it was proposed earlier, with
  "Proposed 12 min ago"; several are listed to CHOOSE from (newest first; title, New or Updated, length, what it
  replaces, when it was proposed and when it expires, and `Review`), and `Review` puts that one's card in the conversation.
  Nothing is applied, dismissed or chosen for the person. A proposal that already has a card, in any state, is never added
  again, and one this screen applied or dismissed is never offered again, whatever a later list says. The list is the
  backend's truth: refreshed from it, what it no longer lists is no longer offered, and applying a revision takes the listed
  proposals for the same plan out. A failure to look is a notice with Try Again (never "none"); an expired session is said, with
  no retry. `Ask for More Changes` is offered only on the NEWEST waiting version of the workout the card is a version of,
  because that is the one the coach refines: the newest revision of the same saved plan (once asked, the conversation is
  about that plan and the backend reads that plan's proposals only, so a newer card for another plan does not stand in its
  way), or, for a new workout, which nothing binds the coach to, the newest of all. A card for an older one, or for a
  different workout than the one being edited, says so and offers Apply and Dismiss (newest = the one that expires last,
  which is the one made last, since every proposal waits 30 minutes; it takes the unreviewed listed ones into account, and
  a newer one that is dismissed stops standing in the way). One left in the list says "1 workout is waiting".
- **Retry.** A failed message can be tried again (network, timeout, unreadable answer, 502, 503) with the identical request,
  the message is not added twice, and the workout it names is the conversation's now; not after an expired session (401),
  a missing account (404, about no workout), a message the backend refuses (422) or a workout that cannot be edited. Only
  the latest failure can be tried again: an older failed bubble stays failed, and Try Again asks the latest request again
  and never replays an older bubble. A retry after a lost answer can make a second proposal on the backend that the
  app never saw: it is no longer lost, because the list finds it.
- **The conversation survives leaving the tab.** The shell mounts the coach the first time it is opened and keeps it
  mounted, hidden, under the other tabs, so a pending answer, a proposal and a workout being applied or dismissed all
  finish and are there when the person comes back; coming back looks for waiting proposals again. **Start over** goes back
  to the app's greeting and looks again: the backend still has what it had waiting.
- **After a workout is applied** the card shows what the backend answered with ("Replaced “Core & Abs Focus” with “Core
  Stability & Abs” for today."), and Home is told, whichever tab is showing: when Home is what the person is looking at it
  reads the plans again at once, and otherwise the next time it is shown. A read of the plans already on its way when the
  workout was applied is not taken as the answer, so it cannot put the old plan back.
- **Authentication.** A 401 on any call is said in words ("Your session has expired. Log in again.") without a retry; the
  app does not navigate to sign-in by itself (Home does not either).

Rules the screen keeps (each is a test, and the guards were checked by breaking them on purpose):

- A workout is `applied` only after the approval succeeded (201, or 200 for the same plan), and `rejected` only after the
  rejection answered 204. A failure leaves the proposal as it was and says why (`coachErrors.ts`); trying again is offered
  only where it can help.
- One request at a time: no message while the coach answers or a workout is applying or being dismissed; one apply or
  dismissal at a time; a second press sends nothing; a card that is applied, applying, rejected, replaced or refused for good
  cannot be applied or dismissed.
- A newer proposal ends the older versions of the same workout ("Older version"): the same saved plan, or new workouts among
  themselves. A waiting proposal for another saved plan, or a new workout beside a revision, is not an older version: the
  backend still has it waiting and it stays offered. Applying a revision ends the other cards for the same saved
  workout, which the backend would refuse (409, the plan was cancelled).
- Start over is refused while a workout is applying or being dismissed (the request cannot be called back). An answer that
  arrives after Start over, or after the screen closed, is dropped.
- A timed-out or unreadable approval says the workout "may not have been applied" and that trying again will tell: the
  backend answers the same plan (200) if it was. Dismissing it instead is reconciled the same way (see Dismiss).

## 3. What the card shows, and what it does not

Shown, each from the proposal: title, the focus and day (`coverage.focus`, `scheduled_date`), the length
(`estimated_minutes`), the number of exercises, each section's exercises and minutes, equipment (`equipment[]`, or
"Bodyweight"), the picture (the focus picks one of the app's eight local pictures), the coverage limitation when the
catalog could not cover the focus, and for a revision: what it replaces and keeps, the backend's Key Changes (including a
changed or dropped weight and, when the backend said how long the replaced plan takes, "Kept the same duration" or
"Duration changed from X to Y min"), and the day if it moved. For a workout waiting from before: when it was proposed.

Not shown, because the proposal does not carry it: a difficulty, a description, a picture or category, and any claim the
comparison cannot show ("knee friendly", "uses your equipment"). When the backend could not compare, the card says it
could not and lists no change and no length. The coach's own words are the message above the card.

## 4. Gaps

**Closed in Phase 2.1** (the gaps this document listed at the end of Phase 2, numbered as they were):

1. *The replaced plan's length was not exposed.* Closed: `revision.replaces_plan_estimated_minutes`.
2. *Formiq's own comparison was not in the response, and the app's copy of the rules had drifted* (it ignored a weight the
   plan has and a proposal drops). Closed: `changes`, computed by the backend; the app's comparison was deleted.
3. *No field named the workout a message is about.* Closed: `workout_plan_id`, checked before the model runs and enforced
   on the proposal.
4. *A pending proposal could not be retrieved.* Closed: `GET /coach/proposals/pending`, used on open, return, Start over and
   retry.
5. *No rejection.* Closed: `POST /coach/proposals/{id}/reject` and the `Dismiss` action. A later refinement also
   supersedes older pending revisions for the same saved plan, so only the newest version remains actionable.
6. *An approval whose answer was lost could not be resolved.* Closed: approving again returns the same plan (200).

Also closed, earlier: the conversation lost on leaving the tab, Home not refreshing after an apply, the 15 s timeout.

**Closed in Phase 2.3** (the defects the live pass of 2026-10-23 found in the app):

- *Try Again replayed the first failed bubble* instead of the latest request: it now asks the latest again.
- *Home was not reloaded when the apply finished while Home was the tab showing*, or while one of its own reads was on its
  way: it asks at once, and the answer to an older read is not taken as current.
- *A dismissal after a lost approval was reported as a failure* ("already applied or changed"): the approval is asked again
  and the card shows the saved plan as applied; an applied card is final.
- *A recovered conversation was about no workout*, so suggested changes and follow-ups named no plan and the coach read the
  newest waiting proposal of any: asking for changes to a card now names its plan from then on.
- *A newer proposal ended every older card*, including ones for other plans: only older versions of the same workout.
- *"1 workouts are waiting".*

**Open, in the app or by choice**

7. **A 401 does not end the session.** The app says so and offers no retry, but does not return to sign-in (nor does
   Home). A single handler for every call would, and would need to decide what happens to an unsent draft.
8. **"Today" is local when the coach receives a timezone.** The coach uses the valid IANA `timezone` sent in
   `POST /coach/message`; without it, the coach uses UTC. The card and Home independently use the device's local
   calendar day for display and plan reads, so a missing or different coach timezone can still produce a day mismatch.
9. **The proposal's expiry is not counted down.** `expires_at` is read (the list says "expires in 18 min"), but a card does
   not disable Apply when it passes: the backend is the authority and answers 409 "expired", which the card then says.
10. **"Updated" is a label, not a status.** The domain has DRAFT, PLANNED and CANCELLED: applying a revision gives a new
    PLANNED plan and a CANCELLED original, so the card says `Applied`.
11. **Only the newest waiting revision of a saved workout can be refined.** Registering that refinement supersedes older
    PENDING revisions for the same saved plan, so their cards are no longer actionable. Separate new-workout proposals and
    proposals for other saved plans remain independent. Whether "newest" is judged right rests on every proposal waiting the
    same 30 minutes (the app orders by `expires_at`); a different time to live would need `created_at` on every proposal.
12. **Waiting proposals are looked for when the screen opens or is shown again, not while it stays open.** One made on
    another device in the meantime is found at the next return, Start over or retry.
13. **Start over does not dismiss.** It clears the conversation; what the coach proposed is still waiting on the backend and
    is offered again, by design. Dismiss is the way to be rid of one.
14. **Older revisions of the same saved workout do not stay approvable.** A refinement supersedes them in the backend, and
    the pending list omits them. Two proposals for new workouts, or proposals for different saved plans, remain independently
    approvable because neither revises the other.
15. **A dismissed proposal's card stays in the conversation** (as "Dismissed") until Start over; there is no undo.
16. **A typed message names a plan only after a change was asked of a card.** A message typed with no change asked of the
    card on the screen names none, as in any conversation: the app does not guess that it is about the card, because a
    request for a new workout would then be refused for the plan. The backend then reads the latest proposal of any plan.
17. **Not run live.** Nothing here called Gemini: the conversation to proposal step is the backend's tested behaviour and the
    scripted model's imitation of it. Whether a real model keeps to the target workout in its words is not shown by any
    test; the backend refuses a proposal that revises another plan, so the worst case is a refusal and a retry inside the
    coach's own bounds.

## 5. Preview without the backend

`EXPO_PUBLIC_COACH_MODE=mock npx expo start` runs the AI Coach tab on the made-up gateway: its menu has "Preview card
states" (every state from fixtures, nothing sent), "Mock: next request fails", "Mock: next apply fails", "Mock: next dismiss
fails" (each failing once), and "Mock: a workout is waiting" and "Mock: two workouts are waiting" (then Start over: the
screen finds one proposal made 12 minutes ago, or two, as the backend's list would give them). In the conversation:
"Create a 25-minute upper-body workout" (a new workout), "Keep same duration" or "Suggest a different ab workout for today"
(an edit of the saved Core & Abs Focus), and then any message or "Ask for More Changes" (a refinement; "easier on my
knees" for the edit). The fixtures have the backend's shapes, the minutes the backend's own formula gives, and `changes`
as the backend's comparison would answer them (written in the mock layer only: no screen or reducer of the app compares
workouts). The mock keeps what it proposed until it is approved or rejected, as the backend does; approving twice returns
the same plan; a rejected proposal cannot be approved. In the connected app the same preview page is in the menu of a
development build only (`__DEV__`).

## 6. Frontend fixes of 2026-10-23 (after the Phase 2.4 verification)

Five app-side changes; nothing outside `frontend/` was touched. Each has tests in `frontend/__tests__/` that were
checked by breaking the fix on purpose.

1. **Expired session, no retry.** The coach already offered no Try Again for a 401 (`coachErrors.ts`: message, apply,
   dismiss and listing). Home's today's-workout card did: its error state now carries `retryable`
   (`isSessionExpired`, `src/api/messages.ts`), and a 401 reads "Your session has expired. Log in again." with no button.
   Every other failure keeps "Try again". The app still does not navigate to sign-in by itself (gap 7 stands: no
   clean sign-out action exists in either component tree).
2. **A failure is scrolled into view.** The typing dots and the failure that replaces them share one id on the page, and
   `CoachScreen` remembered the newest item it had scrolled to by id alone, so the taller failure (and its Try Again) was
   never scrolled to. The memory is now `kind:id`.
3. **Waiting proposals of one name are told apart.** `waitingDetails.ts`: only when two or more share a name (trimmed,
   case-insensitive) the list adds "For today / tomorrow / Thu, 22 Oct" from `scheduled_date`, and, for two on the same
   day, "Proposed at 9:12 am" from `created_at` (with seconds if they share a minute). A uniquely named workout is
   unchanged.
4. **One `GET /coach/proposals/pending` per opening.** Opening Edit with AI on a coach that was mounted with no workout
   shows the tab (`active`) and hands it the workout in one render. `useCoachChat` has an effect for being shown and one
   for a new conversation; the first asked, then the second restarted the conversation (making that answer stale) and
   asked again. The two effects were swapped, with a comment that the order is the fix.
5. **Weights.** `ProposedExercise.weight_kg: number | null` (kilograms; always sent, an older answer without it reads as
   null; a non-number refuses the answer). A row shows it after the target: "3 sets • 10 reps • 20 kg • 60 s rest"; none
   leaves the row as it was. `changes.identical` keeps its meaning (the exercises are prescribed alike): a day-only move or
   a rename arrives as `identical: true` with `scheduled_date_changed` or `name_changed`, so the card decides "nothing
   changed" from the added, removed and changed lists and both flags, never from `identical`. Key Changes now also says
   "Renamed from “A” to “B”" whenever `name_changed` is true (an earlier test said a changed name was no line: changed on
   purpose; it is the last line, so it never displaces an exercise or the day, though it can itself fall under "and N more"). A weight change reads
   "Goblet Squat: 15 kg → 20 kg", "no weight → 20 kg" or "15 kg → no weight"; a day-only move "Moved from Tue, 20 Oct to
   Wed, 21 Oct".
