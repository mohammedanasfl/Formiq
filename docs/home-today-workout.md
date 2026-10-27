# Home: today's workout

Phase A of connecting the app to the backend: Home's "Today's workout" card is read from the backend,
read-only. Nothing is generated, approved, rejected or started. The rest of Home (greeting name, nutrition,
progress, "Up next", recent activity) is still mock data (`frontend/src/mock/homeMock.ts`).

## What the app reads

Only these three requests, all `GET`, all for the signed-in user (the id in the path is the token's own;
the backend answers 404 for any other), all with `Authorization: Bearer <token>`. Verified from
`backend/app/api/routes/*.py`, the schemas and the backend's own tests.

| Request | Answer | Used for |
| --- | --- | --- |
| `GET /users/{id}/workout-plans?status=PLANNED&scheduled_date=YYYY-MM-DD` | 200 `list[WorkoutPlanResponse]`, latest scheduled date first, then most recently created | the plans for the device's calendar day |
| `GET /users/{id}/workout-sessions?status=IN_PROGRESS` | 200 `list[WorkoutSessionResponse]`, most recently started first | a session that is running |
| `GET /users/{id}/workout-sessions?status=COMPLETED` | same | a plan, or a day, that was done |

Fields read, from `WorkoutPlanResponse`: `id`, `name`, `description`, `status`, `scheduled_date`, and for each
exercise `id`, `exercise_order`, `section`, `sets`, `reps`, `duration_seconds`, `weight_kg`, `rest_seconds`,
`notes`, `exercise.{name, description, instructions}`. From `WorkoutSessionResponse`: `id`,
`workout_plan_id`, `status`, `started_at`, `completed_at`. Everything else is ignored.

An answer the app cannot read in full (a missing or mistyped field, an unknown status or section, a time that
is not a time, not a list) is refused as a whole, as `invalid-response`: a plan or session dropped from a list
would be taken for one that does not exist. If any one of the three reads fails, the whole load fails
(Home shows an error with "Try again"); a state worked out from two of three could say "start your workout"
while a session is running.

The plan's `scheduled_date` is a calendar day with no time zone. The app compares it with the **device's**
local day.

## The states

In this order (`deriveTodayWorkout`, `frontend/src/home/todayWorkout.ts`):

1. **In progress**: a session is `IN_PROGRESS` (whatever day it started). The card names the plan when the
   session was started from one of today's plans, says when it started, and offers nothing: the app cannot
   continue a session.
2. **Scheduled**: a `PLANNED` plan for today with no `COMPLETED` session started from it (`workout_plan_id` =
   the plan's id). The existing workout card ("Start Workout"). With several, the most recently created one
   not yet done is shown.
3. **Completed**: every plan for today has a `COMPLETED` session of its own; or, with no plan for today, a
   session was completed today (device day). The card says when. A manual workout does not finish a plan.
4. **No workout**: none of the above. "No workout planned today" with "Ask Formiq", as before.
5. **Loading** (nothing read yet) and **error** (any read failed or could not be read).

The card shows only what the plan carries: its name, description and number of exercises. A saved plan has no
length and no category, so the card has neither and uses the neutral picture. Opening it shows the workout
screen from the plan (`workoutDetailsFromPlan`): names, sections, sets, reps or seconds, rest, notes, the
catalog's description and steps; no length, muscles, equipment or pictures (the plan response has none).

## When it asks

When Home comes into focus: first shown, the Home tab selected again, a screen over it closed, or the app
returning to the foreground. Never twice at once (a focus while a request is out joins it); not again for 30
seconds after a good answer; always again when the calendar day has changed or the person presses "Try
again". The state lives in the app shell, so leaving Home and returning shows the last answer at once and
refreshes it with no flash of "loading". A failed refresh replaces the old answer with the error.

## What the Home screen cannot say yet

These states are not implemented in Home. The AI Coach already has a read-only pending-proposal route, but
Home does not call it, and the app still does not infer either state from missing plan data.

### 1. A pending proposal (not read by Home)

A coach proposal is kept in `workout_plan_proposals`. `GET /coach/proposals/pending` returns
`{ proposals: [...] }`, with the signed-in user's most recently made proposals first. The list contains only
proposals that are still actionable: pending, unexpired, still bound to the same records, and valid for approval;
expired, approved, rejected, superseded, or stale proposals are omitted. The route reads only: it does not run
the coach or create, approve, reject, or change a proposal. Each item carries the proposal and its `created_at`,
including its `proposal_id`, `binding`, expiry, workout details, coverage, revision, and comparison data where
applicable.

The connected AI Coach uses this route when it opens or returns to the screen. Home does not, so a pending
proposal is not currently a Home state. The AI Coach tab still owns proposal review.

### 2. A scheduled rest day (no weekdays stored)

The profile stores `training_frequency_per_week` (an integer, 0 or more) and nothing about which days:
`user_profiles` has no weekday column, `UserProfileResponse` has no such field, and the app's Training step asks
for a count only. A plan has no rest marker. A day with no plan is therefore "no workout planned", and the
app never works out a weekly schedule from a count (a test pins that the profile is not even read).

Smallest change, a product decision: a `training_weekdays` field (a list of 0 to 6) on the profile, with a new
Alembic migration, and the Training step asking for it. Or decide that a rest day is simply a day with no plan.

## Other gaps found

- **Whole history on every Home load.** `GET /workout-sessions` takes only `status`: no `limit`, no
  `workout_plan_id`, no date. Home must read every `COMPLETED` session, each with its exercises and sets, to
  know whether a plan was done. Fine for a new user; it grows with use. Smallest change: optional
  `workout_plan_id`, `completed_after` and `limit` filters (the repository's `find_by_user` already takes a
  `limit`).
- **Coach dates and Home dates use separate inputs.** `POST /coach/message` uses the user's local calendar day
  when the request supplies a valid IANA `timezone`; when it is omitted, the coach uses UTC and is told that it
  is doing so. Home's plan query and its comparison of date-only `scheduled_date` values use the device's local
  calendar day. The mobile client sends the device timezone to the coach, but Home does not send a timezone to
  the plan/session routes. A client that omits or misaligns the coach timezone can therefore create a proposal
  for a different calendar day than the one Home is currently displaying. This behavior is covered by scripted
  tests; live Gemini timezone behavior has not been verified here.
- **Several plans on one day** are allowed. Home shows one (see above); the others are not shown until
  "Up next" is connected.
- **An expired token** shows "Your session has expired. Log in again." on the card but does not sign the person
  out.
- **The workout cannot be started, continued or finished from the app yet** (that is session writes), so only
  a scheduled plan is pressable, and the workout screen's "Start Workout" still says it is not available.
