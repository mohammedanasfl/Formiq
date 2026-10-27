import {
  listPlannedWorkouts,
  listWorkoutSessions,
  type Session,
  type WorkoutPlan,
  type WorkoutSession,
} from '../api';
import { localDateKey } from './format';

// What Home's "Today's workout" card says, from what the backend says. Only what the backend can answer is
// here; two things it cannot are deliberately missing, and nothing makes them up:
//   - a scheduled REST DAY: a profile stores how many days a week the user trains
//     (training_frequency_per_week), never which ones, and a plan has no rest marker, so a day with no plan is
//     only "no workout planned". A weekly schedule is never worked out from a count.
//   - a PENDING PROPOSAL: a coach proposal is kept in the database, but no route reads it (it is returned
//     only by POST /coach/message, which runs the coach and its language model), so Home cannot know of one.
// Either becomes a state here when the backend can say it (see docs/home-today-workout.md).
export type SettledTodayWorkout =
  // nothing is planned for today, and nothing was done
  | { kind: 'none' }
  // a PLANNED plan for today that has not been done: the one Home shows (the most recently created)
  | { kind: 'scheduled'; plan: WorkoutPlan }
  // a session is running. `plan` is today's plan when the session was started from it, else null.
  | { kind: 'inProgress'; session: WorkoutSession; plan: WorkoutPlan | null }
  // today's plan(s) were all done (`plan`, with the COMPLETED session that did it), or, with no plan today,
  // a workout was completed today (`plan` null)
  | { kind: 'completed'; session: WorkoutSession; plan: WorkoutPlan | null };

export type TodayWorkoutState =
  // nothing has been read yet
  | { kind: 'loading' }
  // the backend could not be asked, or its answer could not be read; `message` is for the person. `retryable`: asking
  // again can help (not when the session has expired: the token is no good, and only signing in again changes that)
  | { kind: 'error'; message: string; retryable: boolean }
  | SettledTodayWorkout;

type Answers = {
  // the user's PLANNED plans for today, as the backend listed them
  plans: readonly WorkoutPlan[];
  inProgress: readonly WorkoutSession[];
  completed: readonly WorkoutSession[];
  // the device's own moment: its calendar day is "today"
  today: Date;
};

// Which state follows from the backend's answers, in this order: a running session first (the user is in the
// middle of a workout, whatever else is planned), then a plan still to do, then a plan or a workout that is
// done, then nothing. The plan the session or the completion belongs to is looked up by id, never guessed.
export function deriveTodayWorkout({ plans, inProgress, completed, today }: Answers): SettledTodayWorkout {
  const todayKey = localDateKey(today);

  const running = inProgress.find((session) => session.status === 'IN_PROGRESS');
  if (running) {
    return { kind: 'inProgress', session: running, plan: plans.find((plan) => plan.id === running.workout_plan_id) ?? null };
  }

  // the backend filters by day and status; this checks it, so a different answer never shows as today's
  const todays = plans.filter((plan) => plan.status === 'PLANNED' && plan.scheduled_date === todayKey);
  const finished = completed.filter((session) => session.status === 'COMPLETED');
  // the most recently started COMPLETED session of the plan (the list comes most recent first)
  const doneFor = (plan: WorkoutPlan) => finished.find((session) => session.workout_plan_id === plan.id);

  const waiting = todays.find((plan) => !doneFor(plan));
  if (waiting) return { kind: 'scheduled', plan: waiting };

  if (todays.length > 0) {
    return { kind: 'completed', plan: todays[0], session: doneFor(todays[0])! };
  }

  // no plan today: a workout the user completed today (a manual one, or from a plan of another day)
  const doneToday = finished.find(
    (session) => session.completed_at !== null && localDateKey(new Date(session.completed_at)) === todayKey,
  );
  return doneToday ? { kind: 'completed', plan: null, session: doneToday } : { kind: 'none' };
}

// Asks the backend, read-only and for the signed-in user only, and derives the state. The three reads run
// together; if any one fails the whole load fails, because a state worked out from two of the three could
// say "start your workout" while a session is running.
export async function loadTodayWorkout(session: Session, today: Date): Promise<SettledTodayWorkout> {
  const [plans, inProgress, completed] = await Promise.all([
    listPlannedWorkouts(session, localDateKey(today)),
    listWorkoutSessions(session, 'IN_PROGRESS'),
    // the route has no limit or plan filter, so this is the user's whole history: see docs/home-today-workout.md
    listWorkoutSessions(session, 'COMPLETED'),
  ]);
  return deriveTodayWorkout({ plans, inProgress, completed, today });
}
