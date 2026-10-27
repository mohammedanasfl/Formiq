// Plans and sessions as the backend sends them (WorkoutPlanResponse and WorkoutSessionResponse), and a scripted
// backend that answers the three reads Home makes. Nothing here is a real user's.
import type { PlanExercise, WorkoutPlan, WorkoutSession } from '../src/api';
import type { MockFetch, Reply } from './mockFetch';

// Tuesday 20 October 2026, half past nine in the morning, local time: the moment the Home tests run at
export const NOW = new Date(2026, 9, 20, 9, 30);
export const TODAY = '2026-10-20';
export const YESTERDAY = '2026-10-19';
export const TOMORROW = '2026-10-21';

// An ISO time for a local clock time on the day of NOW, plus `days`: built from the device's own time zone, so
// "today at 8:15" is today whatever zone the tests run in
export function localTime(hour: number, minute = 0, days = 0): string {
  return new Date(2026, 9, 20 + days, hour, minute).toISOString();
}

export function planExercise(overrides: Partial<PlanExercise> = {}): PlanExercise {
  return {
    id: 1,
    exercise_order: 1,
    section: 'MAIN_WORKOUT',
    sets: 3,
    reps: 10,
    duration_seconds: null,
    weight_kg: null,
    rest_seconds: 60,
    notes: null,
    exercise: { name: 'Goblet Squat', description: null, instructions: [] },
    ...overrides,
  };
}

export function plan(overrides: Partial<WorkoutPlan> = {}): WorkoutPlan {
  return {
    id: 41,
    name: 'Lower Body Strength',
    description: null,
    status: 'PLANNED',
    scheduled_date: TODAY,
    exercises: [planExercise()],
    ...overrides,
  };
}

export function session(overrides: Partial<WorkoutSession> = {}): WorkoutSession {
  return {
    id: 9,
    workout_plan_id: 41,
    status: 'COMPLETED',
    started_at: localTime(8, 15),
    completed_at: localTime(8, 58),
    ...overrides,
  };
}

// The workout of the design phase (src/mock/workoutDetailsMock.ts) as a saved plan would carry it: the same
// name, description and exercises, with what a plan has not got (a length, a category, muscles, equipment)
// left out. For the tests of the screens that open a workout.
export function corePlan(scheduledDate: string | null = TODAY): WorkoutPlan {
  const exercise = (
    id: number,
    section: PlanExercise['section'],
    name: string,
    target: Pick<PlanExercise, 'sets' | 'reps' | 'duration_seconds'>,
  ) => planExercise({ id, exercise_order: id, section, exercise: { name, description: null, instructions: [] }, ...target });
  return plan({
    id: 41,
    name: 'Core & Abs Focus',
    description: 'Strengthen your core and improve stability.',
    scheduled_date: scheduledDate,
    exercises: [
      exercise(1, 'WARM_UP', 'Mountain Climbers', { sets: 2, reps: null, duration_seconds: 30 }),
      exercise(2, 'WARM_UP', 'Lunges', { sets: 2, reps: 10, duration_seconds: null }),
      exercise(3, 'MAIN_WORKOUT', 'Plank', { sets: 3, reps: null, duration_seconds: 30 }),
      exercise(4, 'MAIN_WORKOUT', 'Dead Bug', { sets: 3, reps: 12, duration_seconds: null }),
      exercise(5, 'MAIN_WORKOUT', 'Bicycle Crunch', { sets: 3, reps: 16, duration_seconds: null }),
      exercise(6, 'COOL_DOWN', 'Hamstring Stretch', { sets: 1, reps: null, duration_seconds: 30 }),
    ],
  });
}

// What each read answers: a list is a 200 with that body, or a whole reply (an error, a dropped connection, a
// request left open). Left out, a read answers 200 with nothing. The answers can be changed during a test: they
// are read when each request arrives.
export type WorkoutAnswers = {
  plans?: unknown[] | Reply;
  inProgress?: unknown[] | Reply;
  completed?: unknown[] | Reply;
};

export function backendWorkouts(backend: MockFetch, userId: number, answers: WorkoutAnswers = {}): WorkoutAnswers {
  const reply = (answer: WorkoutAnswers[keyof WorkoutAnswers]): Reply =>
    Array.isArray(answer) ? { status: 200, body: answer } : (answer ?? { status: 200, body: [] });
  backend.on('GET', `/users/${userId}/workout-plans`, () => reply(answers.plans));
  backend.on('GET', `/users/${userId}/workout-sessions`, (request) => {
    const status = new URL(request.url).searchParams.get('status');
    if (status === 'IN_PROGRESS') return reply(answers.inProgress);
    if (status === 'COMPLETED') return reply(answers.completed);
    return { status: 422 };
  });
  return answers;
}

// the reads Home made, as "path?query"
export function readsMade(backend: MockFetch): string[] {
  return backend.requests.map((request) => `${request.method} ${request.path}${new URL(request.url).search}`);
}
