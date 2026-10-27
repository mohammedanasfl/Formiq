import { fireEvent, screen, within } from '@testing-library/react-native';

import { TodayWorkoutCard } from '../src/home/TodayWorkoutCard';
import type { TodayWorkoutState } from '../src/home/todayWorkout';
import { themes, type ThemeScheme } from '../src/theme';
import { WORKOUT_FALLBACK_IMAGE } from '../src/workouts/workoutImages';
import { renderWithTheme } from '../test-utils/renderWithTheme';
import { corePlan, localTime, NOW, plan, session } from '../test-utils/workoutFixtures';

const dark = themes.dark.colors;

async function renderCard(state: TodayWorkoutState, scheme?: ThemeScheme) {
  const handlers = { onOpenWorkout: jest.fn(), onAskFormiq: jest.fn(), onRetry: jest.fn() };
  const view = await renderWithTheme(<TodayWorkoutCard state={state} today={NOW} {...handlers} />, scheme);
  return { ...view, ...handlers };
}

const running = (overrides = {}) => session({ status: 'IN_PROGRESS', completed_at: null, ...overrides });

describe('loading', () => {
  test('says it is checking, with nothing to press and nothing invented', async () => {
    await renderCard({ kind: 'loading' });

    expect(screen.getByTestId('workout-card-loading')).toBeOnTheScreen();
    screen.getByText("Checking today's workout");
    expect(screen.queryByRole('button')).toBeNull();
    expect(screen.queryByText(/Start Workout|exercise|min\b/)).toBeNull();
  });
});

describe('an error', () => {
  test("says today's workout could not be loaded, gives the reason, and offers to try again", async () => {
    const { onRetry } = await renderCard({ kind: 'error', message: "Can't reach Formiq. Check your connection and try again.", retryable: true });

    const card = screen.getByTestId('workout-card-error');
    within(card).getByText("Couldn't load today's workout");
    within(card).getByText("Can't reach Formiq. Check your connection and try again.");
    expect(within(card).queryByText(/Start Workout|No workout planned/)).toBeNull();

    await fireEvent.press(screen.getByRole('button', { name: 'Try again' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  test('the retry button shows a refresh glyph, not the arrow that goes somewhere', async () => {
    await renderCard({ kind: 'error', message: 'x', retryable: true });

    const retry = screen.getByRole('button', { name: 'Try again' });
    expect(within(retry).getByTestId('icon-refresh', { includeHiddenElements: true })).toBeOnTheScreen();
    expect(within(retry).queryByTestId('icon-arrow-right', { includeHiddenElements: true })).toBeNull();
  });

  test('an expired session says so and offers no "Try again": asking again with the same token cannot work', async () => {
    const { onRetry } = await renderCard({ kind: 'error', message: 'Your session has expired. Log in again.', retryable: false });

    const card = screen.getByTestId('workout-card-error');
    within(card).getByText("Couldn't load today's workout");
    within(card).getByText('Your session has expired. Log in again.');
    expect(screen.queryByRole('button')).toBeNull();
    expect(screen.queryByText('Try again')).toBeNull();
    expect(onRetry).not.toHaveBeenCalled();
  });
});

describe('no workout', () => {
  test('says nothing is planned and offers to ask Formiq, which only navigates', async () => {
    const { onAskFormiq, onOpenWorkout, onRetry } = await renderCard({ kind: 'none' });

    screen.getByText('No workout planned today');
    screen.getByText('Ask Formiq to build one for you.');
    await fireEvent.press(screen.getByRole('button', { name: 'Ask Formiq' }));

    expect(onAskFormiq).toHaveBeenCalledTimes(1);
    expect(onOpenWorkout).not.toHaveBeenCalled();
    expect(onRetry).not.toHaveBeenCalled();
  });

  test('never calls the day a rest day', async () => {
    await renderCard({ kind: 'none' });

    expect(screen.queryByText(/rest/i)).toBeNull();
  });
});

describe('a workout scheduled for today', () => {
  test("is the plan's own card: its name, description and number of exercises, one button reading Start Workout", async () => {
    const { onOpenWorkout } = await renderCard({ kind: 'scheduled', plan: corePlan() });

    const card = screen.getByRole('button', {
      name: 'Core & Abs Focus. Strengthen your core and improve stability. 6 exercises.',
    });
    expect(card).toHaveProp('accessibilityHint', 'Start Workout');
    within(card).getByText('Start Workout');

    await fireEvent.press(card);
    expect(onOpenWorkout.mock.calls).toEqual([[41]]);
  });

  test('shows only what the plan has: no length, no category, and no description when there is none', async () => {
    await renderCard({ kind: 'scheduled', plan: plan({ name: 'Easy Walk', description: null }) });

    const card = screen.getByTestId('workout-card-41');
    expect(within(card).getByText('Easy Walk')).toBeOnTheScreen();
    expect(within(card).getByText('1 exercise')).toBeOnTheScreen();
    expect(within(card).queryByText(/min\b/)).toBeNull();
    expect(within(card).queryByText(/^(Strength|Mobility|Cardio|Full body|Recovery|Beginner)$/)).toBeNull();
    expect(screen.getByTestId('workout-card-41-photo')).toHaveProp('source', WORKOUT_FALLBACK_IMAGE);
  });

  test('a plan with no exercises shows no count rather than "0 exercises"', async () => {
    await renderCard({ kind: 'scheduled', plan: plan({ exercises: [] }) });

    expect(within(screen.getByTestId('workout-card-41')).queryByText(/exercise/)).toBeNull();
  });
});

describe('a workout in progress', () => {
  test("names the plan it was started from, says when it started, and has nothing to press: it cannot be continued from the app", async () => {
    await renderCard({ kind: 'inProgress', session: running({ started_at: localTime(8, 15) }), plan: corePlan() });

    const card = screen.getByTestId('workout-card-in-progress');
    within(card).getByText('Core & Abs Focus');
    within(card).getByText('In progress. Started today at 8:15 am.');
    expect(screen.queryByRole('button')).toBeNull();
    expect(screen.queryByText(/Start Workout|Continue|Resume/)).toBeNull();
  });

  test('without a plan it says only that a workout is in progress and when it started', async () => {
    await renderCard({ kind: 'inProgress', session: running({ started_at: localTime(8, 15), workout_plan_id: null }), plan: null });

    const card = screen.getByTestId('workout-card-in-progress');
    within(card).getByText('Workout in progress');
    within(card).getByText('Started today at 8:15 am.');
  });

  test('a session left open from an earlier day says which day it started', async () => {
    await renderCard({ kind: 'inProgress', session: running({ started_at: localTime(8, 15, -2) }), plan: null });

    screen.getByText('Started Sun, 18 Oct 2026.');
  });

  test('shows no length, exercise count or category: a session carries none of them', async () => {
    await renderCard({ kind: 'inProgress', session: running(), plan: corePlan() });

    expect(screen.queryByText(/min\b|exercises?\b/)).toBeNull();
  });
});

describe('a completed workout', () => {
  test('names the plan, says when it was completed, and has nothing to press', async () => {
    await renderCard({ kind: 'completed', session: session({ completed_at: localTime(8, 58) }), plan: corePlan() });

    const card = screen.getByTestId('workout-card-completed');
    within(card).getByText('Core & Abs Focus');
    within(card).getByText('Completed today at 8:58 am.');
    expect(screen.queryByRole('button')).toBeNull();
    expect(screen.queryByText(/Start Workout/)).toBeNull();
  });

  test('without a plan it says only that a workout was completed, and when', async () => {
    await renderCard({ kind: 'completed', session: session({ completed_at: localTime(7, 5), workout_plan_id: null }), plan: null });

    within(screen.getByTestId('workout-card-completed')).getByText('Workout completed');
    screen.getByText('Completed today at 7:05 am.');
  });

  test('a plan done on an earlier day says that day', async () => {
    await renderCard({ kind: 'completed', session: session({ completed_at: localTime(20, 0, -1) }), plan: corePlan() });

    screen.getByText('Completed Mon, 19 Oct 2026.');
  });

  test('shows no length, exercise count or category', async () => {
    await renderCard({ kind: 'completed', session: session(), plan: corePlan() });

    expect(screen.queryByText(/min\b|exercises?\b/)).toBeNull();
  });
});

describe('the cards in both themes', () => {
  const states: [string, TodayWorkoutState, string][] = [
    ['loading', { kind: 'loading' }, 'workout-card-loading'],
    ['error', { kind: 'error', message: 'x', retryable: true }, 'workout-card-error'],
    ['none', { kind: 'none' }, 'workout-card-empty'],
    ['scheduled', { kind: 'scheduled', plan: corePlan() }, 'workout-card-41'],
    ['in progress', { kind: 'inProgress', session: running(), plan: null }, 'workout-card-in-progress'],
    ['completed', { kind: 'completed', session: session(), plan: null }, 'workout-card-completed'],
  ];

  test.each(states)('%s is the dark card in the light theme too, with the dark theme\'s words', async (_name, state, testID) => {
    await renderCard(state, 'light');

    expect(screen.getByTestId(testID)).toHaveStyle({ backgroundColor: dark.surface, borderColor: dark.border });
    expect(within(screen.getByTestId(testID)).getAllByText(/./)[0]).toHaveStyle({ color: dark.textPrimary });
  });

  test.each(states)('%s is the same dark card in the dark theme', async (_name, state, testID) => {
    await renderCard(state, 'dark');

    expect(screen.getByTestId(testID)).toHaveStyle({ backgroundColor: dark.surface, borderColor: dark.border });
  });
});
