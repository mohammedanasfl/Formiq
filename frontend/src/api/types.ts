// The parts of the backend contract the app uses. Mirrors backend/app/schemas/auth.py,
// user_profile.py and equipment.py: change them together.

export type Credentials = { email: string; password: string };

// Who is signed in: the access token, and the user id it was issued for (its `sub` claim).
export type Session = { token: string; userId: number };

// UserProfileCreate without its optional target_weight_kg, goal_period_weeks and
// dietary_preference, which the app does not ask for yet.
export type ProfileCreate = {
  first_name: string;
  last_name?: string;
  age: number;
  height_cm: number;
  weight_kg: number;
  gender: string;
  fitness_experience: string;
  goal: string;
  training_frequency_per_week: number;
  training_location: string;
  activity_level: string;
  sleep_hours: number;
  // the catalog equipment the person chose (Equipment.id, from GET /equipment), each once; empty when they
  // chose none or have none
  equipment_ids: number[];
  // they said they have no equipment (bodyweight only): never with equipment_ids. With neither, they did not say.
  no_equipment: boolean;
};

export type Equipment = { id: number; name: string };

// What the backend keeps of a person's equipment (UserProfileResponse.equipment and no_equipment): the catalog
// pieces they have, or that they have none (equipment is then empty). With neither, they never said.
export type SavedEquipment = { equipment: Equipment[]; noEquipment: boolean };

// UserProfileUpdate's equipment fields: replace the selection (PATCH /users/{id}/profile). The same pair as
// ProfileCreate carries, and the same rule: no_equipment never with equipment_ids.
export type EquipmentChoice = { equipment_ids: number[]; no_equipment: boolean };

// What the app reads of a workout plan and a workout session. Mirror backend/app/schemas/workout_plan.py
// (WorkoutPlanResponse) and workout_session.py (WorkoutSessionResponse), keeping only the fields the app
// uses: change them together. The names stay the backend's own.
export type PlanStatus = 'DRAFT' | 'PLANNED' | 'CANCELLED';
export type PlanSectionName = 'WARM_UP' | 'MAIN_WORKOUT' | 'COOL_DOWN';

export type PlanExercise = {
  // WorkoutPlanExerciseResponse.id: the row's own id, not the catalog exercise's
  id: number;
  exercise_order: number;
  section: PlanSectionName;
  sets: number;
  // one of the two is given per set: reps, or seconds for a timed activity
  reps: number | null;
  duration_seconds: number | null;
  weight_kg: number | null;
  rest_seconds: number | null;
  notes: string | null;
  // PlannedExerciseDetailsResponse: what the catalog says about the exercise
  exercise: { name: string; description: string | null; instructions: string[] };
};

export type WorkoutPlan = {
  id: number;
  name: string;
  description: string | null;
  status: PlanStatus;
  // "YYYY-MM-DD", a calendar day with no time zone; null for an undated plan
  scheduled_date: string | null;
  exercises: PlanExercise[];
};

export type SessionStatus = 'IN_PROGRESS' | 'COMPLETED' | 'CANCELLED';

export type WorkoutSession = {
  id: number;
  // the plan the session was started from; null for a manual workout
  workout_plan_id: number | null;
  status: SessionStatus;
  // ISO 8601 times with an offset
  started_at: string;
  completed_at: string | null;
};

// What the app reads of the coach's answer and of a workout plan it proposes. Mirror backend/app/schemas/coach.py
// (CoachMessageResponse, WorkoutPlanProposalResponse, PendingProposalsResponse and what they hold), as Phase 2.1
// changed it: change them together. The names stay the backend's own, and every field is the backend's, none is added.
//
// What a proposal does NOT carry, so no screen may show it as the proposal's: a description, a difficulty, or a
// picture or category. How long the plan it revises takes, and how it differs from that plan, ARE carried
// (`revision.replaces_plan_estimated_minutes`, `changes`), worked out by the backend: the app never works them out.
// See docs/coach-workout-card.md.

// What a proposed workout trains (SessionFocus) and the parts of the body its main exercises train (BodyRegion).
export type SessionFocus = 'FULL_BODY' | 'UPPER_BODY' | 'LOWER_BODY' | 'PUSH' | 'PULL' | 'CORE';
export type BodyRegion = 'LOWER_BODY' | 'UPPER_PUSH' | 'UPPER_PULL' | 'CORE';

export type RevisionKind = 'ADJUST' | 'ALTERNATIVE';

// The saved plan a proposal revises: approving the proposal saves a new plan and cancels that one.
export type ProposalRevision = {
  replaces_plan_id: number;
  replaces_plan_name: string;
  kind: RevisionKind;
  // the main exercises it keeps from that plan, by name
  kept_exercises: string[];
  // How long the plan it replaces takes, by the formula behind the proposal's own estimated_minutes (a plan stores
  // no length); null when the backend could not work it out as the plan was proposed against
  replaces_plan_estimated_minutes: number | null;
};

// What a workout asks of one exercise (backend Prescription): `summary` is the backend's own one-line wording
// ("3 sets of 10 reps at 20 kg, 60 s rest"), shown as it is and never read for logic.
export type Prescription = {
  sets: number;
  reps: number | null;
  duration_seconds: number | null;
  rest_seconds: number | null;
  // a saved plan may carry a weight; a proposal sets none
  weight_kg: number | null;
  summary: string;
};

// An exercise one workout has and the other has not (the other side is null), or has with another prescription
// (both sides). `added` items have only `after`, `removed` only `before`, `changed` both.
export type ExerciseChange = {
  section: PlanSectionName;
  exercise_name: string;
  before: Prescription | null;
  after: Prescription | null;
};

// How a proposal differs from the saved plan it replaces, as the backend worked it out (app/tools/comparison.py):
// the one comparison the coach itself is held to. A weight that the saved plan has and the proposal does not is a
// change. The app presents it and does not compare anything itself.
export type ProposalChanges = {
  compared_with_plan_id: number;
  compared_with_plan_name: string;
  // the day the saved plan is scheduled for (the proposal's own day is in the proposal)
  compared_with_scheduled_date: string | null;
  added: ExerciseChange[];
  removed: ExerciseChange[];
  changed: ExerciseChange[];
  // the exercises both have, prescribed alike, by name
  unchanged: string[];
  name_changed: boolean;
  scheduled_date_changed: boolean;
  // true when the exercises are prescribed alike. It says nothing of the name or the day, which `name_changed` and
  // `scheduled_date_changed` carry: a workout moved to another day, or renamed, with every exercise kept, is `identical`
  // and still changed. Nothing here decides "nothing changed" from this alone.
  identical: boolean;
};

export type CoverageLimitation = {
  code: 'NO_SUITABLE_EXERCISE' | 'TOO_FEW_SUITABLE_EXERCISES';
  region: BodyRegion | null;
  message: string;
};

// How completely the main exercises fulfil the focus. `complete: false` means Formiq's catalog left no choice.
export type ProposalCoverage = {
  complete: boolean;
  focus: SessionFocus;
  trained_regions: BodyRegion[];
  missing_regions: BodyRegion[];
  main_exercises_counted: number;
  main_exercises_required: number;
  limitations: CoverageLimitation[];
};

export type ProposedExercise = {
  exercise_order: number;
  section: PlanSectionName;
  exercise_id: number;
  exercise_name: string;
  // what the exercise needs, from the catalog; empty when nothing
  equipment: string[];
  sets: number;
  // each set's target: reps, or seconds (one of them)
  reps: number | null;
  duration_seconds: number | null;
  rest_seconds: number | null;
  // the weight in kilograms the exercise is prescribed at; null when it has none. Always sent by the backend; an answer
  // from before the field existed reads as null (readProposedExercise).
  weight_kg: number | null;
  notes: string | null;
};

// A workout the coach proposed. It is NOT saved: only POST /coach/proposals/{proposal_id}/approve, with `binding`,
// saves it (as a PLANNED plan, cancelling the plan it revises, if any).
export type WorkoutProposal = {
  proposal_id: string;
  // the digest of this exact proposal: an approval must carry it
  binding: string;
  // ISO 8601 time with an offset: the proposal can be approved until then (30 minutes after it was made)
  expires_at: string;
  name: string;
  // "YYYY-MM-DD"
  scheduled_date: string;
  exercises: ProposedExercise[];
  // Formiq's estimate of each section and of the whole workout
  warm_up_minutes: number;
  main_minutes: number;
  cool_down_minutes: number;
  estimated_minutes: number;
  coverage: ProposalCoverage;
  // the saved plan it would replace; null for a new workout
  revision: ProposalRevision | null;
  // How it differs from that plan, as the plan is now. Null for a new workout, and when the backend could not compare
  // (the plan is not as it was when proposed): the card then lists no changes, and says it could not compare.
  changes: ProposalChanges | null;
};

// A proposal still waiting for the person's approval, as GET /coach/proposals/pending lists it: the same card and
// the same binding as when it was shown, and when it was made.
export type PendingProposal = WorkoutProposal & {
  // ISO 8601 time with an offset
  created_at: string;
};

// CoachMessageResponse: `proposal` is null when the coach proposed nothing in this reply (the backend leaves it out).
export type CoachReply = {
  reply: string;
  proposal: WorkoutProposal | null;
};

// CoachHistoryTurn: an earlier turn the client sends for context. The coach's own turns are "coach".
export type CoachHistoryTurn = {
  role: 'user' | 'coach';
  text: string;
};

