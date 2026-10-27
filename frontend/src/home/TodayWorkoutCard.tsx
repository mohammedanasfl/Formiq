import { workoutCardFromPlan } from '../workouts/planMapping';
import { EmptyWorkoutCard, WorkoutCard } from '../workouts/WorkoutCard';
import { formatWhen } from './format';
import type { TodayWorkoutState } from './todayWorkout';

type TodayWorkoutCardProps = {
  state: TodayWorkoutState;
  // the device's own moment, for "today at 9:30 am"
  today: Date;
  // opens a plan's own screen, by its id
  onOpenWorkout: (planId: number) => void;
  onAskFormiq: () => void;
  onRetry: () => void;
};

// The card under "Today's workout", for each thing the backend can say, in the card shells Home already
// has: a workout card for a plan still to do, and the plain card (title, a line, an optional button) for the
// rest. Every line comes from the backend's answer; a field it does not carry (a length, a category) is left
// out, not filled in. Only the plan still to do is pressable: no workout can be started or continued from
// the app yet, so nothing running or finished offers to be.
export function TodayWorkoutCard({ state, today, onOpenWorkout, onAskFormiq, onRetry }: TodayWorkoutCardProps) {
  switch (state.kind) {
    case 'loading':
      return (
        <EmptyWorkoutCard
          testID="workout-card-loading"
          title="Checking today's workout"
          message="One moment."
        />
      );
    case 'error':
      return (
        <EmptyWorkoutCard
          testID="workout-card-error"
          title="Couldn't load today's workout"
          message={state.message}
          // an expired session says so and offers nothing: asking again with the same token cannot work
          actionLabel={state.retryable ? 'Try again' : undefined}
          actionIcon="refresh"
          onAction={state.retryable ? onRetry : undefined}
        />
      );
    case 'none':
      return (
        <EmptyWorkoutCard
          title="No workout planned today"
          message="Ask Formiq to build one for you."
          actionLabel="Ask Formiq"
          onAction={onAskFormiq}
        />
      );
    case 'scheduled':
      return (
        <WorkoutCard
          workout={workoutCardFromPlan(state.plan)}
          actionLabel="Start Workout"
          onPress={() => onOpenWorkout(state.plan.id)}
        />
      );
    case 'inProgress': {
      const when = formatWhen(state.session.started_at, today);
      const started = when ? `Started ${when}.` : null;
      return (
        <EmptyWorkoutCard
          testID="workout-card-in-progress"
          title={state.plan?.name ?? 'Workout in progress'}
          // the plan's name is the title, so the line says what state it is in; "Workout in progress" says it itself
          message={[state.plan ? 'In progress.' : null, started].filter(Boolean).join(' ') || 'In progress.'}
        />
      );
    }
    case 'completed': {
      const when = formatWhen(state.session.completed_at ?? state.session.started_at, today);
      return (
        <EmptyWorkoutCard
          testID="workout-card-completed"
          title={state.plan?.name ?? 'Workout completed'}
          message={when ? `Completed ${when}.` : 'Completed.'}
        />
      );
    }
  }
}
