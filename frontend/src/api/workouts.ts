import { apiRequest, isRecord } from './client';
import { invalid, isInteger, isIntegerOrNull, isNumberOrNull, isSection, isText, isTextOrNull, isTime } from './readers';
import type {
  PlanExercise,
  PlanSectionName,
  PlanStatus,
  Session,
  SessionStatus,
  WorkoutPlan,
  WorkoutSession,
} from './types';

// These reads are for the signed-in user only: the id in the path is the token's own, and the backend answers
// 404 for any other. They only read: nothing here creates, changes or deletes a plan or a session.

// GET /users/{id}/workout-plans?status=PLANNED&scheduled_date=YYYY-MM-DD: 200 with the user's PLANNED plans
// for that day, most recently created first (an empty list when there is none).
export async function listPlannedWorkouts(session: Session, date: string): Promise<WorkoutPlan[]> {
  const query = `status=PLANNED&scheduled_date=${encodeURIComponent(date)}`;
  const data = await apiRequest(`/users/${session.userId}/workout-plans?${query}`, { token: session.token });
  return readList(data, readPlan);
}

// GET /users/{id}/workout-sessions?status=IN_PROGRESS|COMPLETED: 200 with the user's sessions in that status,
// the most recently started first. The route takes no other filter and no limit.
export async function listWorkoutSessions(
  session: Session,
  status: Extract<SessionStatus, 'IN_PROGRESS' | 'COMPLETED'>,
): Promise<WorkoutSession[]> {
  const data = await apiRequest(`/users/${session.userId}/workout-sessions?status=${status}`, {
    token: session.token,
  });
  return readList(data, readSession);
}

function readList<T>(data: unknown, readItem: (item: unknown) => T): T[] {
  if (!Array.isArray(data)) invalid();
  return data.map(readItem);
}

const PLAN_STATUSES: readonly string[] = ['DRAFT', 'PLANNED', 'CANCELLED'] satisfies PlanStatus[];
const SESSION_STATUSES: readonly string[] = ['IN_PROGRESS', 'COMPLETED', 'CANCELLED'] satisfies SessionStatus[];

// One plan as the backend sends it (WorkoutPlanResponse): the plan lists, GET one plan, and an approval's answer.
export function readPlan(item: unknown): WorkoutPlan {
  if (!isRecord(item)) return invalid();
  const { id, name, description, status, scheduled_date, exercises } = item;
  if (
    !isInteger(id) ||
    !isText(name) ||
    name.trim() === '' ||
    !isTextOrNull(description) ||
    !isText(status) ||
    !PLAN_STATUSES.includes(status) ||
    !(scheduled_date === null || (isText(scheduled_date) && /^\d{4}-\d{2}-\d{2}$/.test(scheduled_date))) ||
    !Array.isArray(exercises)
  ) {
    return invalid();
  }
  return {
    id,
    name,
    description,
    status: status as PlanStatus,
    scheduled_date,
    exercises: exercises.map(readPlanExercise),
  };
}

function readPlanExercise(item: unknown): PlanExercise {
  if (!isRecord(item)) return invalid();
  const { id, exercise_order, section, sets, reps, duration_seconds, weight_kg, rest_seconds, notes, exercise } = item;
  if (
    !isInteger(id) ||
    !isInteger(exercise_order) ||
    !isText(section) ||
    !isSection(section) ||
    !isInteger(sets) ||
    !isIntegerOrNull(reps) ||
    !isIntegerOrNull(duration_seconds) ||
    !isNumberOrNull(weight_kg) ||
    !isIntegerOrNull(rest_seconds) ||
    !isTextOrNull(notes) ||
    !isRecord(exercise)
  ) {
    return invalid();
  }
  const { name, description, instructions } = exercise;
  if (
    !isText(name) ||
    name.trim() === '' ||
    !isTextOrNull(description) ||
    !Array.isArray(instructions) ||
    !instructions.every(isText)
  ) {
    return invalid();
  }
  return {
    id,
    exercise_order,
    section: section as PlanSectionName,
    sets,
    reps,
    duration_seconds,
    weight_kg,
    rest_seconds,
    notes,
    exercise: { name, description, instructions },
  };
}

function readSession(item: unknown): WorkoutSession {
  if (!isRecord(item)) return invalid();
  const { id, workout_plan_id, status, started_at, completed_at } = item;
  if (
    !isInteger(id) ||
    !isIntegerOrNull(workout_plan_id) ||
    !isText(status) ||
    !SESSION_STATUSES.includes(status) ||
    !isTime(started_at) ||
    !(completed_at === null || isTime(completed_at))
  ) {
    return invalid();
  }
  return { id, workout_plan_id, status: status as SessionStatus, started_at, completed_at };
}
