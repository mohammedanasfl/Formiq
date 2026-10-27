import { apiRequest, ApiError, isRecord } from './client';
import {
  invalid,
  isInteger,
  isIntegerOrNull,
  isNumberOrNull,
  isSection,
  isText,
  isTextOrNull,
  isTime,
} from './readers';
import type {
  BodyRegion,
  CoachHistoryTurn,
  CoachReply,
  CoverageLimitation,
  ExerciseChange,
  PendingProposal,
  Prescription,
  ProposalChanges,
  ProposalCoverage,
  ProposalRevision,
  ProposedExercise,
  RevisionKind,
  Session,
  SessionFocus,
  WorkoutPlan,
  WorkoutProposal,
} from './types';
import { readPlan } from './workouts';

// The coach: its message route, the routes that list, save and dismiss what it proposes. Contracts as Phase 2.1 made
// them (backend/app/api/routes/coach.py, app/schemas/coach.py); docs/coach-workout-card.md has the table.
//
// Nothing here saves anything by itself: POST /coach/message only answers (and may propose), listing the pending
// proposals only reads, and only the approval saves a plan. Rejecting one only stops it being offered.

// One coach turn can take several model requests (the backend allows five rounds of tool calls and one more to
// correct a refused proposal), so it gets far longer than the 15 s of a plain read. Approving and reading a plan
// are database work and keep the default.
export const COACH_TIMEOUT_MS = 90_000;

// The most a saved plan's id can be (the backend's columns' own limit).
const MAX_PLAN_ID = 2_147_483_647;

// POST /coach/message {message, history, workout_plan_id?, timezone?}: 200 {reply, proposal?}. `history` is the earlier turns,
// oldest first (the backend keeps the most recent 50, each up to 8000 characters); the request carries no user (the
// token's is used). `workoutPlanId` is the saved workout the conversation is about, sent only when there is one: the
// backend checks, before it asks the model anything, that it is the user's and PLANNED (404 when it is not found or
// not theirs, 409 when it is not PLANNED), and then lets the proposal revise that plan and no other. `timeZone` is the
// device's IANA time zone (src/api/timeZone.ts), sent only when the caller has one: "today" and "tomorrow" are the user's
// own days in it. A zone the backend's database does not have is refused with a 422 about the time zone; the message
// is then sent once more without it (the backend uses the UTC day and tells the coach so) rather than leave the coach
// unreachable for a device whose zone is newer than the server's tzdata. Any other failure is thrown as it is. The answer
// is read in full or refused (an ApiError 'invalid-response'): see readCoachReply.
export async function sendCoachMessage(
  session: Session,
  request: { message: string; history: readonly CoachHistoryTurn[]; workoutPlanId?: number; timeZone?: string },
): Promise<CoachReply> {
  const target = request.workoutPlanId;
  // an id goes into the body: checked again, so nothing malformed is ever sent for one
  if (target !== undefined && !(Number.isInteger(target) && target >= 1 && target <= MAX_PLAN_ID)) {
    throw new ApiError('http', 422, 'invalid workout plan');
  }
  const send = (timeZone: string | undefined) =>
    apiRequest('/coach/message', {
      method: 'POST',
      token: session.token,
      timeoutMs: COACH_TIMEOUT_MS,
      body: {
        message: request.message,
        history: request.history,
        ...(target === undefined ? {} : { workout_plan_id: target }),
        ...(timeZone === undefined ? {} : { timezone: timeZone }),
      },
    });
  let data: unknown;
  try {
    data = await send(request.timeZone);
  } catch (error) {
    const refusedZone =
      request.timeZone !== undefined &&
      error instanceof ApiError &&
      error.status === 422 &&
      /time ?zone/i.test(error.detail ?? '');
    if (!refusedZone) throw error;
    data = await send(undefined);
  }
  return readCoachReply(data);
}

// GET /coach/proposals/pending: 200 {proposals: [...]}, the user's proposals that can still be approved, the most
// recently made first (an empty list when there is none). Expired, applied, rejected and stale ones (a plan they
// replace changed) are not listed. It only reads: nothing is proposed, applied or dismissed by asking.
export async function getPendingProposals(session: Session): Promise<PendingProposal[]> {
  const data = await apiRequest('/coach/proposals/pending', { token: session.token });
  return readPendingProposals(data);
}

// POST /coach/proposals/{proposal_id}/reject {binding}: 204 once the proposal is rejected (repeating it is 204 too, for as
// long as the backend keeps it: once an expired one is cleared it is a 404).
// 404: no such proposal for this user (or it expired and was cleared); 409: it was already approved, or the binding
// is for a different version. Each of those throws an ApiError, so a caller can only call it dismissed after the
// backend said so.
export async function rejectProposal(
  session: Session,
  proposal: { proposalId: string; binding: string },
): Promise<void> {
  if (!PROPOSAL_ID.test(proposal.proposalId) || !BINDING.test(proposal.binding)) {
    throw new ApiError('http', 422, 'invalid proposal');
  }
  await apiRequest(`/coach/proposals/${proposal.proposalId}/reject`, {
    method: 'POST',
    token: session.token,
    body: { binding: proposal.binding },
  });
}

// POST /coach/proposals/{proposal_id}/approve {binding}: 201 with the plan it saved (a PLANNED plan; the plan the
// proposal revises is cancelled in the same transaction), or 200 with the same plan when this user already approved
// this proposal and the plan it saved is still as saved (that is how an approval whose answer was lost is
// recovered). 404: no such proposal for this user; 409: expired, a different version than the one shown, rejected,
// already approved but the saved plan has changed since, the replaced plan changed or cancelled, or no longer
// saveable. Each of those throws an ApiError, so a caller can only go on after the backend said yes.
export async function approveProposal(
  session: Session,
  proposal: { proposalId: string; binding: string },
): Promise<WorkoutPlan> {
  // read from an answer that was checked, but the id goes into a path and the digest into a body: checked again
  if (!PROPOSAL_ID.test(proposal.proposalId) || !BINDING.test(proposal.binding)) {
    throw new ApiError('http', 422, 'invalid proposal');
  }
  const data = await apiRequest(`/coach/proposals/${proposal.proposalId}/approve`, {
    method: 'POST',
    token: session.token,
    body: { binding: proposal.binding },
  });
  return readPlan(data);
}

const PROPOSAL_ID = /^[0-9a-f]{32}$/;
const BINDING = /^[0-9a-f]{64}$/;

const FOCUSES: readonly string[] = ['FULL_BODY', 'UPPER_BODY', 'LOWER_BODY', 'PUSH', 'PULL', 'CORE'] satisfies SessionFocus[];
const REGIONS: readonly string[] = ['LOWER_BODY', 'UPPER_PUSH', 'UPPER_PULL', 'CORE'] satisfies BodyRegion[];
const REVISION_KINDS: readonly string[] = ['ADJUST', 'ALTERNATIVE'] satisfies RevisionKind[];
const LIMITATION_CODES: readonly string[] = ['NO_SUITABLE_EXERCISE', 'TOO_FEW_SUITABLE_EXERCISES'] satisfies CoverageLimitation['code'][];

// What the backend leaves out or sends as null (reps or duration, rest, a weight, notes, a revision, the proposal itself)
// reads as null; anything else of the wrong type refuses the whole answer.
const orNull = (value: unknown) => (value === undefined ? null : value);

// CoachMessageResponse: `reply` always; `proposal` only when the coach proposed a workout in this reply (the route
// leaves it out otherwise). A proposal that cannot be read in full is refused with the answer, never shown in part.
export function readCoachReply(data: unknown): CoachReply {
  if (!isRecord(data) || !isText(data.reply)) return invalid();
  const proposal = orNull(data.proposal);
  return { reply: data.reply, proposal: proposal === null ? null : readProposal(proposal) };
}

// PendingProposalsResponse: a list of proposals, each with the time it was made. Every one is read in full or the
// whole list is refused: a proposal missing from it would be taken for one that is not waiting.
export function readPendingProposals(data: unknown): PendingProposal[] {
  if (!isRecord(data) || !Array.isArray(data.proposals)) return invalid();
  return data.proposals.map((item) => {
    if (!isRecord(item) || !isTime(item.created_at)) return invalid();
    return { ...readProposal(item), created_at: item.created_at };
  });
}

function readProposal(item: unknown): WorkoutProposal {
  if (!isRecord(item)) return invalid();
  const {
    proposal_id,
    binding,
    expires_at,
    name,
    scheduled_date,
    exercises,
    warm_up_minutes,
    main_minutes,
    cool_down_minutes,
    estimated_minutes,
    coverage,
    revision,
  } = item;
  if (
    !isText(proposal_id) ||
    !PROPOSAL_ID.test(proposal_id) ||
    !isText(binding) ||
    !BINDING.test(binding) ||
    !isTime(expires_at) ||
    !isText(name) ||
    name.trim() === '' ||
    !isText(scheduled_date) ||
    !/^\d{4}-\d{2}-\d{2}$/.test(scheduled_date) ||
    !Array.isArray(exercises) ||
    !isInteger(warm_up_minutes) ||
    !isInteger(main_minutes) ||
    !isInteger(cool_down_minutes) ||
    !isInteger(estimated_minutes)
  ) {
    return invalid();
  }
  const read = {
    proposal_id,
    binding,
    expires_at,
    name,
    scheduled_date,
    exercises: exercises.map(readProposedExercise),
    warm_up_minutes,
    main_minutes,
    cool_down_minutes,
    estimated_minutes,
    coverage: readCoverage(coverage),
    revision: readRevision(orNull(revision)),
    changes: readChanges(orNull(item.changes)),
  };
  // A comparison is of the plan the proposal replaces and of nothing else: one with no revision, or with another
  // plan, would put differences on the card that are not this workout's.
  if (read.changes !== null && (read.revision === null || read.changes.compared_with_plan_id !== read.revision.replaces_plan_id)) {
    return invalid();
  }
  return read;
}

function readProposedExercise(item: unknown): ProposedExercise {
  if (!isRecord(item)) return invalid();
  const { exercise_order, section, exercise_id, exercise_name, equipment, sets } = item;
  const reps = orNull(item.reps);
  const duration_seconds = orNull(item.duration_seconds);
  const rest_seconds = orNull(item.rest_seconds);
  // always sent now; an answer from before the field existed has none, which is no weight
  const weight_kg = orNull(item.weight_kg);
  const notes = orNull(item.notes);
  if (
    !isInteger(exercise_order) ||
    !isSection(section) ||
    !isInteger(exercise_id) ||
    !isText(exercise_name) ||
    exercise_name.trim() === '' ||
    !Array.isArray(equipment) ||
    !equipment.every(isText) ||
    !isInteger(sets) ||
    !isIntegerOrNull(reps) ||
    !isIntegerOrNull(duration_seconds) ||
    !isIntegerOrNull(rest_seconds) ||
    !isNumberOrNull(weight_kg) ||
    !isTextOrNull(notes)
  ) {
    return invalid();
  }
  return { exercise_order, section, exercise_id, exercise_name, equipment, sets, reps, duration_seconds, rest_seconds, weight_kg, notes };
}

function readRevision(item: unknown): ProposalRevision | null {
  if (item === null) return null;
  if (!isRecord(item)) return invalid();
  const { replaces_plan_id, replaces_plan_name, kind, kept_exercises } = item;
  const replaces_plan_estimated_minutes = orNull(item.replaces_plan_estimated_minutes);
  if (
    !isInteger(replaces_plan_id) ||
    !isText(replaces_plan_name) ||
    replaces_plan_name.trim() === '' ||
    !isText(kind) ||
    !REVISION_KINDS.includes(kind) ||
    !Array.isArray(kept_exercises) ||
    !kept_exercises.every(isText) ||
    !isIntegerOrNull(replaces_plan_estimated_minutes)
  ) {
    return invalid();
  }
  return {
    replaces_plan_id,
    replaces_plan_name,
    kind: kind as RevisionKind,
    kept_exercises,
    replaces_plan_estimated_minutes,
  };
}

const DAY = /^\d{4}-\d{2}-\d{2}$/;

// ProposalChanges: how the proposal differs from the plan it replaces, as the backend worked it out. Read in full:
// an exercise change with the wrong sides (an "added" one that has a before, say) is refused with the answer rather
// than shown as something it is not.
function readChanges(item: unknown): ProposalChanges | null {
  if (item === null) return null;
  if (!isRecord(item)) return invalid();
  const { compared_with_plan_id, compared_with_plan_name, added, removed, changed, unchanged } = item;
  const compared_with_scheduled_date = orNull(item.compared_with_scheduled_date);
  if (
    !isInteger(compared_with_plan_id) ||
    !isText(compared_with_plan_name) ||
    !(compared_with_scheduled_date === null || (isText(compared_with_scheduled_date) && DAY.test(compared_with_scheduled_date))) ||
    !Array.isArray(added) ||
    !Array.isArray(removed) ||
    !Array.isArray(changed) ||
    !Array.isArray(unchanged) ||
    !unchanged.every(isText) ||
    typeof item.name_changed !== 'boolean' ||
    typeof item.scheduled_date_changed !== 'boolean' ||
    typeof item.identical !== 'boolean'
  ) {
    return invalid();
  }
  return {
    compared_with_plan_id,
    compared_with_plan_name,
    compared_with_scheduled_date,
    // only in the proposal, only in the plan, and in both with another prescription
    added: added.map((entry) => readExerciseChange(entry, false, true)),
    removed: removed.map((entry) => readExerciseChange(entry, true, false)),
    changed: changed.map((entry) => readExerciseChange(entry, true, true)),
    unchanged,
    name_changed: item.name_changed,
    scheduled_date_changed: item.scheduled_date_changed,
    identical: item.identical,
  };
}

function readExerciseChange(item: unknown, hasBefore: boolean, hasAfter: boolean): ExerciseChange {
  if (!isRecord(item)) return invalid();
  const { section, exercise_name } = item;
  const before = orNull(item.before);
  const after = orNull(item.after);
  if (
    !isSection(section) ||
    !isText(exercise_name) ||
    exercise_name.trim() === '' ||
    (before === null) === hasBefore ||
    (after === null) === hasAfter
  ) {
    return invalid();
  }
  return {
    section,
    exercise_name,
    before: before === null ? null : readPrescription(before),
    after: after === null ? null : readPrescription(after),
  };
}

function readPrescription(item: unknown): Prescription {
  if (!isRecord(item)) return invalid();
  const { sets, summary } = item;
  const reps = orNull(item.reps);
  const duration_seconds = orNull(item.duration_seconds);
  const rest_seconds = orNull(item.rest_seconds);
  const weight_kg = orNull(item.weight_kg);
  if (
    !isInteger(sets) ||
    !isText(summary) ||
    !isIntegerOrNull(reps) ||
    !isIntegerOrNull(duration_seconds) ||
    !isIntegerOrNull(rest_seconds) ||
    !isNumberOrNull(weight_kg)
  ) {
    return invalid();
  }
  return { sets, reps, duration_seconds, rest_seconds, weight_kg, summary };
}

const isRegion = (value: unknown): value is BodyRegion => isText(value) && REGIONS.includes(value);

function readCoverage(item: unknown): ProposalCoverage {
  if (!isRecord(item)) return invalid();
  const { complete, focus, trained_regions, missing_regions, main_exercises_counted, main_exercises_required, limitations } = item;
  if (
    typeof complete !== 'boolean' ||
    !isText(focus) ||
    !FOCUSES.includes(focus) ||
    !Array.isArray(trained_regions) ||
    !trained_regions.every(isRegion) ||
    !Array.isArray(missing_regions) ||
    !missing_regions.every(isRegion) ||
    !isInteger(main_exercises_counted) ||
    !isInteger(main_exercises_required) ||
    !Array.isArray(limitations)
  ) {
    return invalid();
  }
  return {
    complete,
    focus: focus as SessionFocus,
    trained_regions,
    missing_regions,
    main_exercises_counted,
    main_exercises_required,
    limitations: limitations.map(readLimitation),
  };
}

function readLimitation(item: unknown): CoverageLimitation {
  if (!isRecord(item)) return invalid();
  const { code, message } = item;
  const region = orNull(item.region);
  if (!isText(code) || !LIMITATION_CODES.includes(code) || !isText(message) || !(region === null || isRegion(region))) {
    return invalid();
  }
  return { code: code as CoverageLimitation['code'], region, message };
}
