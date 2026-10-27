import { fireEvent, screen, within } from '@testing-library/react-native';
import { StyleSheet, type TextStyle } from 'react-native';

import { HomeScreen } from '../src/home/HomeScreen';
import type { TodayWorkoutState } from '../src/home/todayWorkout';
import { MOCK_HOME, type HomeData } from '../src/mock/homeMock';
import { themes, type ThemeScheme } from '../src/theme';
import { CATEGORY_COLORS } from '../src/workouts/categoryColors';
import { WORKOUT_FALLBACK_IMAGE, WORKOUT_IMAGES, type WorkoutImageKey } from '../src/workouts/workoutImages';
import { renderWithTheme } from '../test-utils/renderWithTheme';
import { corePlan } from '../test-utils/workoutFixtures';

const dark = themes.dark.colors;
const light = themes.light.colors;
const HIDDEN = { includeHiddenElements: true };
// Tuesday 20 October 2026, a fixed day so the date on the screen does not depend on the clock
const TODAY = new Date(2026, 9, 20, 9, 30);

// today's workout as the backend says it: a plan still to do, which the card shows
const SCHEDULED: TodayWorkoutState = { kind: 'scheduled', plan: corePlan() };

async function renderHome(
  options: { data?: HomeData; todayWorkout?: TodayWorkoutState; scheme?: ThemeScheme; today?: Date } = {},
) {
  const onNavigate = jest.fn();
  const onRetryTodayWorkout = jest.fn();
  const view = await renderWithTheme(
    <HomeScreen
      data={options.data ?? MOCK_HOME}
      todayWorkout={options.todayWorkout ?? SCHEDULED}
      onRetryTodayWorkout={onRetryTodayWorkout}
      today={options.today ?? TODAY}
      onNavigate={onNavigate}
    />,
    options.scheme,
  );
  return { ...view, onNavigate, onRetryTodayWorkout };
}

describe('what Home shows', () => {
  test("shows today's workout under its own heading, as a card: title, description and count, and nothing the plan lacks", async () => {
    await renderHome();

    expect(screen.getByRole('header', { name: "Today's workout" })).toBeOnTheScreen();
    const card = screen.getByTestId('workout-card-41');
    for (const text of ['Core & Abs Focus', 'Strengthen your core and improve stability.', '6 exercises']) {
      expect(within(card).getByText(text)).toBeOnTheScreen();
    }
    // a saved plan has no length and no category: the card shows neither, and has no kind heading
    expect(within(card).queryByText(/min\b/)).toBeNull();
    expect(within(card).queryByText(/^(Strength|Mobility|Cardio|Full body|Recovery|Beginner)$/)).toBeNull();
    // so its picture is the neutral one: a picture, not content, with no name
    const photo = screen.getByTestId('workout-card-41-photo');
    expect(photo).toHaveProp('source', WORKOUT_FALLBACK_IMAGE);
    expect(photo).toHaveProp('accessible', false);
    expect(photo).not.toHaveProp('accessibilityLabel');
  });

  test('the card is one button, whose call to action is "Start Workout"', async () => {
    await renderHome();

    const card = screen.getByRole('button', { name: /^Core & Abs Focus\./ });
    expect(card).toHaveProp('accessibilityHint', 'Start Workout');
    expect(within(card).getByText('Start Workout')).toBeOnTheScreen();
    expect(within(card).getByTestId('icon-arrow-right', HIDDEN)).toBeOnTheScreen();
  });

  test('shows the nutrition and progress tiles, each read as one sentence', async () => {
    await renderHome();

    expect(screen.getByRole('button', { name: "Nutrition: 1,850 kcal, Today's target, 60%" })).toBeOnTheScreen();
    expect(screen.getByRole('button', { name: 'Progress: On track, Weekly goal, 4 / 7' })).toBeOnTheScreen();
  });

  test('has four quick actions under their own heading', async () => {
    await renderHome();

    expect(screen.getByRole('header', { name: 'Quick Actions' })).toBeOnTheScreen();
    for (const name of [
      'View Plan. See your workouts',
      'Ask Formiq. Get AI guidance',
      'Log Meal. Track your nutrition',
      'Update Profile. Keep your info current',
    ]) {
      expect(screen.getByRole('button', { name })).toBeOnTheScreen();
    }
  });

  test('lists the recent activity it is given, one row each, under a heading with a "See all" link', async () => {
    await renderHome();

    expect(screen.getByRole('header', { name: 'Recent Activity' })).toBeOnTheScreen();
    expect(screen.getByRole('link', { name: 'See all recent activity' })).toBeOnTheScreen();
    for (const entry of MOCK_HOME.recentActivity) {
      expect(screen.getByRole('button', { name: `${entry.title}. ${entry.subtitle}` })).toBeOnTheScreen();
    }
  });

  test('shows whatever data it is given, not a fixed text: the screen is ready for the backend', async () => {
    await renderHome({
      todayWorkout: {
        kind: 'scheduled',
        plan: { ...corePlan(), id: 7, name: 'Lower Body Power', description: 'Squats and hinges.', exercises: corePlan().exercises.slice(0, 5) },
      },
      data: {
        userName: 'Priya',
        upNext: [{ id: 8, title: 'Easy Walk' }],
        nutrition: { kcal: 2400, progress: 0.25 },
        weeklyGoal: { status: 'Behind', sessionsDone: 1, sessionsTarget: 3 },
        recentActivity: [{ id: 'a', title: 'Walk', subtitle: 'Completed • Monday' }],
      },
    });

    screen.getByRole('header', { name: 'Good morning, Priya' });
    screen.getByText('Lower Body Power');
    screen.getByText('Squats and hinges.');
    screen.getByText('5 exercises');
    screen.getByRole('button', { name: "Nutrition: 2,400 kcal, Today's target, 25%" });
    screen.getByRole('button', { name: 'Progress: Behind, Weekly goal, 1 / 3' });
    expect(screen.getAllByRole('button', { name: /Completed/ })).toHaveLength(1);
    expect(screen.queryByText('Core & Abs Focus')).toBeNull();
    // the up-next workout has only a name, and shows only that
    expect(within(screen.getByTestId('workout-card-8')).getAllByText(/./)).toHaveLength(1);
  });

  test('the bars show how far along each measure is', async () => {
    await renderHome();

    expect(screen.getByTestId('nutrition-tile-bar-fill', HIDDEN)).toHaveStyle({ width: '60%', backgroundColor: dark.primary });
    expect(screen.getByTestId('progress-tile-bar-fill', HIDDEN)).toHaveStyle({
      width: `${(4 / 7) * 100}%`,
      backgroundColor: dark.progress,
    });
  });

  test("the date is the device's own when none is given", async () => {
    // only the clock is faked: React's and the test library's timers must keep running
    jest.useFakeTimers({
      now: new Date(2027, 1, 3, 12),
      doNotFake: [
        'setTimeout',
        'clearTimeout',
        'setInterval',
        'clearInterval',
        'setImmediate',
        'clearImmediate',
        'nextTick',
        'queueMicrotask',
        'requestAnimationFrame',
        'cancelAnimationFrame',
        'requestIdleCallback',
        'cancelIdleCallback',
        'hrtime',
        'performance',
      ],
    });
    try {
      await renderWithTheme(
        <HomeScreen data={MOCK_HOME} todayWorkout={SCHEDULED} onRetryTodayWorkout={jest.fn()} onNavigate={jest.fn()} />,
      );

      screen.getByText('Wed, 3 Feb 2027');
    } finally {
      jest.useRealTimers();
    }
  });
});

describe('where every control leads', () => {
  test.each([
    [/^Core & Abs Focus\./, 'button', 'workouts'],
    [/^Lower Body Strength, Strength\./, 'button', 'workouts'],
    [/^Mobility Reset, Mobility\./, 'button', 'workouts'],
    ['See all recent activity', 'link', 'workouts'],
    ['Upper Body Strength. Completed • Yesterday', 'button', 'workouts'],
    ['View Plan. See your workouts', 'button', 'workouts'],
    ["Nutrition: 1,850 kcal, Today's target, 60%", 'button', 'nutrition'],
    ['Log Meal. Track your nutrition', 'button', 'nutrition'],
    ['Progress: On track, Weekly goal, 4 / 7', 'button', 'progress'],
    ['Ask Formiq. Get AI guidance', 'button', 'coach'],
    ['Update Profile. Keep your info current', 'button', 'profile'],
  ] as const)('%s leads to %s, and nothing else happens', async (name, role, destination) => {
    const { onNavigate } = await renderHome();

    await fireEvent.press(screen.getByRole(role, { name }));

    expect(onNavigate.mock.calls).toEqual([[destination]]);
    expect(screen.queryByTestId('toast')).toBeNull();
  });
});

describe('opening a workout', () => {
  test("a workout card opens that workout when the app can open one, and goes nowhere else", async () => {
    const onNavigate = jest.fn();
    const onOpenWorkout = jest.fn();
    await renderWithTheme(
      <HomeScreen
        data={MOCK_HOME}
        todayWorkout={SCHEDULED}
        onRetryTodayWorkout={jest.fn()}
        today={TODAY}
        onNavigate={onNavigate}
        onOpenWorkout={onOpenWorkout}
      />,
    );

    await fireEvent.press(screen.getByRole('button', { name: /^Core & Abs Focus\./ }));
    await fireEvent.press(screen.getByRole('button', { name: /^Lower Body Strength, Strength\./ }));
    await fireEvent.press(screen.getByRole('button', { name: /^Mobility Reset, Mobility\./ }));

    // today's card opens its plan by the plan's own id; the other cards by theirs
    expect(onOpenWorkout.mock.calls).toEqual([[41], ['mock-workout-up-1'], ['mock-workout-up-2']]);
    expect(onNavigate).not.toHaveBeenCalled();
  });

  test('the other controls still lead where they did when the app can open a workout', async () => {
    const onNavigate = jest.fn();
    const onOpenWorkout = jest.fn();
    await renderWithTheme(
      <HomeScreen
        data={MOCK_HOME}
        todayWorkout={SCHEDULED}
        onRetryTodayWorkout={jest.fn()}
        today={TODAY}
        onNavigate={onNavigate}
        onOpenWorkout={onOpenWorkout}
      />,
    );

    await fireEvent.press(screen.getByRole('button', { name: 'View Plan. See your workouts' }));
    await fireEvent.press(screen.getByRole('link', { name: 'See all recent activity' }));

    expect(onNavigate.mock.calls).toEqual([['workouts'], ['workouts']]);
    expect(onOpenWorkout).not.toHaveBeenCalled();
  });

  test('without a way to open a workout, today\'s card opens the Workouts screen, as the others do', async () => {
    const { onNavigate } = await renderHome();

    await fireEvent.press(screen.getByRole('button', { name: /^Core & Abs Focus\./ }));

    expect(onNavigate.mock.calls).toEqual([['workouts']]);
  });
});

describe('the header', () => {
  // the device's own clock decides the greeting: these are local times on the day of TODAY
  const at = (hour: number, minute = 0) => new Date(2026, 9, 20, hour, minute);

  test('greets for the time of day, with the name, as the screen\'s heading, and gives the date under it', async () => {
    await renderHome();

    expect(screen.getByRole('header', { name: 'Good morning, Anas' })).toHaveTextContent('Good morning, Anas');
    screen.getByText('Tue, 20 Oct 2026');
  });

  test.each([
    [5, 0, 'Good morning'],
    [9, 30, 'Good morning'],
    [11, 59, 'Good morning'],
    [12, 0, 'Good afternoon'],
    [16, 59, 'Good afternoon'],
    [17, 0, 'Good evening'],
    [23, 59, 'Good evening'],
    [0, 0, 'Good evening'],
    [4, 59, 'Good evening'],
  ])('at %i:%i it says "%s"', async (hour, minute, words) => {
    await renderHome({ today: at(hour, minute) });

    screen.getByRole('header', { name: `${words}, Anas` });
  });

  test('uses the name only when there is one: a blank name leaves it out, with no comma', async () => {
    await renderHome({ data: { ...MOCK_HOME, userName: '' }, today: at(14) });
    expect(screen.getByRole('header', { name: 'Good afternoon' })).toHaveTextContent(/^Good afternoon$/);
  });

  test('a name with spaces around it is trimmed', async () => {
    await renderHome({ data: { ...MOCK_HOME, userName: '  Priya ' }, today: at(19) });

    screen.getByRole('header', { name: 'Good evening, Priya' });
  });

  test('the greeting is the primary text and the date smaller and muted, in the dark theme', async () => {
    await renderHome();

    const greeting = screen.getByRole('header', { name: 'Good morning, Anas' });
    const date = screen.getByText('Tue, 20 Oct 2026');
    expect(greeting).toHaveStyle({ color: dark.textPrimary, fontSize: 24 });
    expect(date).toHaveStyle({ color: dark.textMuted, fontSize: 13 });
    expect(greeting.props.numberOfLines).toBe(2);
  });

  test('and in the light theme: dark primary text, muted grey date', async () => {
    await renderHome({ scheme: 'light' });

    expect(screen.getByRole('header', { name: 'Good morning, Anas' })).toHaveStyle({ color: light.textPrimary });
    expect(screen.getByText('Tue, 20 Oct 2026')).toHaveStyle({ color: light.textMuted });
  });

  test('has no emoji, no notification bell, no avatar and no initials', async () => {
    await renderHome();

    expect(screen.queryByText(/\p{Extended_Pictographic}/u)).toBeNull();
    expect(screen.queryByRole('button', { name: /Notifications/ })).toBeNull();
    expect(screen.queryByTestId('unread-dot', HIDDEN)).toBeNull();
    expect(screen.queryByRole('button', { name: 'Account menu' })).toBeNull();
    expect(screen.queryByText('A', HIDDEN)).toBeNull();
    expect(screen.queryByTestId('icon-bell-outline', HIDDEN)).toBeNull();
  });

  test('the greeting and the toggle sit side by side in one row', async () => {
    await renderHome();

    const toggle = screen.getByRole('button', { name: 'Switch to light theme' });
    const row = toggle.parent!;
    expect(row).toHaveStyle({ flexDirection: 'row', alignItems: 'center' });
    // the words take the room the toggle leaves, so a long name wraps and never pushes it off
    expect(screen.getByRole('header', { name: 'Good morning, Anas' }).parent).toHaveStyle({ flex: 1 });
  });
});

describe('the theme toggle', () => {
  test('in the dark theme it shows a sun and offers the light theme', async () => {
    await renderHome();

    const toggle = screen.getByRole('button', { name: 'Switch to light theme' });
    expect(within(toggle).getByTestId('icon-weather-sunny', HIDDEN)).toBeOnTheScreen();
    expect(within(toggle).queryByTestId('icon-weather-night', HIDDEN)).toBeNull();
  });

  test('in the light theme it shows a moon and offers the dark theme', async () => {
    await renderHome({ scheme: 'light' });

    const toggle = screen.getByRole('button', { name: 'Switch to dark theme' });
    expect(within(toggle).getByTestId('icon-weather-night', HIDDEN)).toBeOnTheScreen();
  });

  test('pressing it switches the whole screen to the other theme, and back', async () => {
    await renderHome();
    expect(screen.getByRole('header', { name: 'Good morning, Anas' })).toHaveStyle({ color: dark.textPrimary });
    expect(screen.getByTestId('tab-inset').parent).toHaveStyle({ backgroundColor: dark.background });

    await fireEvent.press(screen.getByRole('button', { name: 'Switch to light theme' }));

    expect(screen.getByRole('header', { name: 'Good morning, Anas' })).toHaveStyle({ color: light.textPrimary });
    expect(screen.getByTestId('tab-inset').parent).toHaveStyle({ backgroundColor: light.background });
    expect(screen.getByRole('button', { name: 'Switch to dark theme' })).toBeOnTheScreen();
    expect(screen.queryByRole('button', { name: 'Switch to light theme' })).toBeNull();

    await fireEvent.press(screen.getByRole('button', { name: 'Switch to dark theme' }));
    expect(screen.getByRole('header', { name: 'Good morning, Anas' })).toHaveStyle({ color: dark.textPrimary });
    expect(screen.getByRole('button', { name: 'Switch to light theme' })).toBeOnTheScreen();
  });

  test('it is a round, plain button with a thumb-sized touch area, not an emerald accent', async () => {
    await renderHome();

    const toggle = screen.getByRole('button', { name: 'Switch to light theme' });
    expect(toggle).toHaveStyle({
      width: 44,
      height: 44,
      borderRadius: 999,
      borderColor: dark.border,
      backgroundColor: dark.surface,
    });
    // 44 dp drawn, 48 dp to hit
    expect(toggle).toHaveProp('hitSlop', 2);
    const icon = within(toggle).getByTestId('icon-weather-sunny', HIDDEN);
    expect(StyleSheet.flatten((icon.children[0] as unknown as { props: { style: TextStyle } }).props.style)?.color).toBe(dark.textPrimary);
  });

  test('it changes nothing else: no navigation, no notice', async () => {
    const { onNavigate } = await renderHome();

    await fireEvent.press(screen.getByRole('button', { name: 'Switch to light theme' }));

    expect(onNavigate).not.toHaveBeenCalled();
    expect(screen.queryByTestId('toast')).toBeNull();
  });
});

describe('the themes', () => {
  test('dark: a solid near-black page with no photograph behind it, charcoal cards, emerald button on the hero', async () => {
    await renderHome();

    expect(screen.queryByTestId('tab-photo', HIDDEN)).toBeNull();
    expect(screen.getByTestId('tab-inset').parent).toHaveStyle({ backgroundColor: dark.background });
    expect(screen.getByRole('button', { name: 'View Plan. See your workouts' })).toHaveStyle({
      backgroundColor: dark.surface,
      borderColor: dark.border,
    });
    expect(screen.getByTestId('workout-card-action')).toHaveStyle({ backgroundColor: dark.primary });
  });

  test("light: a solid pale page and light tiles, no photo behind the page, but the workout card stays the dark card", async () => {
    await renderHome({ scheme: 'light' });

    expect(screen.queryByTestId('tab-photo', HIDDEN)).toBeNull();
    expect(screen.getByTestId('tab-inset').parent).toHaveStyle({ backgroundColor: light.background });
    expect(screen.getByRole('button', { name: 'View Plan. See your workouts' })).toHaveStyle({
      backgroundColor: light.surface,
      borderColor: light.border,
    });
    expect(screen.getByRole('header', { name: 'Good morning, Anas' })).toHaveStyle({ color: light.textPrimary });
    // the workout card is a dark card on the light page too (the plain one: a saved plan has no category), with
    // white words and the dark theme's call to action
    expect(screen.getByTestId('workout-card-41')).toHaveStyle({
      backgroundColor: dark.surface,
      borderColor: dark.border,
    });
    expect(screen.getByText('Core & Abs Focus')).toHaveStyle({ color: dark.textPrimary });
    expect(screen.getByText('Strengthen your core and improve stability.')).toHaveStyle({ color: dark.textSecondary });
    expect(screen.getByTestId('workout-card-action')).toHaveStyle({ backgroundColor: dark.primary });
    // the "Up next" cards too
    expect(screen.getByTestId('workout-card-mock-workout-up-1')).toHaveStyle({
      backgroundColor: CATEGORY_COLORS['lower-body'].dark.blend,
    });
    expect(screen.getByRole('header', { name: "Today's workout" })).toHaveStyle({ color: light.textPrimary });
  });

  test('the tiles take their wash from their own tint in both themes', async () => {
    const view = await renderHome();
    expect(screen.getByRole('button', { name: /^Progress:/ })).toHaveStyle({ backgroundColor: `${dark.progress}14` });
    expect(screen.getByRole('button', { name: /^Nutrition:/ })).toHaveStyle({ backgroundColor: `${dark.primary}14` });
    await view.unmount();

    await renderHome({ scheme: 'light' });
    expect(screen.getByRole('button', { name: /^Progress:/ })).toHaveStyle({ backgroundColor: `${light.progress}14` });
    expect(screen.getByRole('button', { name: /^Nutrition:/ })).toHaveStyle({ backgroundColor: `${light.primary}14` });
  });
});

describe('workout cards on Home', () => {
  test('"Up next" lists the planned workouts, each a card keyed by its id, under its own heading', async () => {
    await renderHome();

    expect(screen.getByRole('header', { name: 'Up next' })).toBeOnTheScreen();
    for (const workout of MOCK_HOME.upNext) {
      expect(screen.getByTestId(`workout-card-${workout.id}`)).toBeOnTheScreen();
    }
  });

  test('a workout with no length shows none, as a real plan would: the mock does not invent one for it', async () => {
    await renderHome();

    const card = screen.getByTestId('workout-card-mock-workout-up-1');
    expect(within(card).queryByText(/min/)).toBeNull();
    expect(within(card).getByText('6 exercises')).toBeOnTheScreen();
  });

  test('no "Up next" heading when nothing is coming up', async () => {
    await renderHome({ data: { ...MOCK_HOME, upNext: [] } });

    expect(screen.queryByRole('header', { name: 'Up next' })).toBeNull();
    expect(screen.getByRole('header', { name: 'Recent Activity' })).toBeOnTheScreen();
  });

  test('the cards render without a duplicate-key warning', async () => {
    const errors = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    await renderHome();

    expect(errors.mock.calls.filter((call) => /key/i.test(String(call[0])))).toEqual([]);
    errors.mockRestore();
  });

  test('the recent-activity thumbnails come from the same lookup as the cards', async () => {
    const photos = { 'upper-body': { uri: 'test://upper-body.png' }, 'lower-body': { uri: 'test://lower-body.png' } };
    const bundled = { ...WORKOUT_IMAGES };
    Object.assign(WORKOUT_IMAGES, photos);
    delete WORKOUT_IMAGES.mobility;
    try {
      await renderHome();
      const source = (id: string) => screen.getByTestId(`recent-${id}-thumbnail`).props.source;
      expect(source('mock-1')).toBe(photos['upper-body']);
      expect(source('mock-2')).toBe(photos['lower-body']);
      // mobility has no photo registered in this test: the neutral picture
      expect(source('mock-3')).toBe(WORKOUT_FALLBACK_IMAGE);
    } finally {
      for (const key of Object.keys(WORKOUT_IMAGES)) delete WORKOUT_IMAGES[key as WorkoutImageKey];
      Object.assign(WORKOUT_IMAGES, bundled);
    }
  });

  test("with the bundled photos, every recent entry shows its own category photo, and today's plan, which has no category, the neutral picture", async () => {
    await renderHome();

    expect(screen.getByTestId('workout-card-41-photo')).toHaveProp('source', WORKOUT_FALLBACK_IMAGE);
    expect(screen.getByTestId('recent-mock-1-thumbnail')).toHaveProp('source', WORKOUT_IMAGES['upper-body']);
    expect(screen.getByTestId('recent-mock-2-thumbnail')).toHaveProp('source', WORKOUT_IMAGES['lower-body']);
    expect(screen.getByTestId('recent-mock-3-thumbnail')).toHaveProp('source', WORKOUT_IMAGES.mobility);
  });

  test('an entry with no category has the neutral thumbnail', async () => {
    await renderHome({
      data: { ...MOCK_HOME, recentActivity: [{ id: 'x', title: 'Walk', subtitle: 'Completed • Today' }] },
    });

    expect(screen.getByTestId('recent-x-thumbnail')).toHaveProp('source', WORKOUT_FALLBACK_IMAGE);
  });
});

describe('when there is no workout today', () => {
  const none: HomeData = { ...MOCK_HOME, upNext: [] };
  const NONE: TodayWorkoutState = { kind: 'none' };

  test('Home says so, instead of an empty or invented card, and still has its heading', async () => {
    await renderHome({ data: none, todayWorkout: NONE });

    expect(screen.getByRole('header', { name: "Today's workout" })).toBeOnTheScreen();
    screen.getByText('No workout planned today');
    screen.getByText('Ask Formiq to build one for you.');
    expect(screen.getByTestId('workout-card-empty')).toBeOnTheScreen();
    expect(screen.queryByText('Core & Abs Focus')).toBeNull();
    expect(screen.queryByText('Start Workout')).toBeNull();
    expect(screen.queryByTestId('workout-card-action')).toBeNull();
  });

  test('its next step, "Ask Formiq", opens the Coach tab', async () => {
    const { onNavigate } = await renderHome({ data: none, todayWorkout: NONE });

    await fireEvent.press(screen.getByRole('button', { name: 'Ask Formiq' }));

    expect(onNavigate.mock.calls).toEqual([['coach']]);
  });

  test('the rest of Home is unaffected', async () => {
    await renderHome({ data: none, todayWorkout: NONE });

    screen.getByRole('button', { name: /^Nutrition:/ });
    screen.getByRole('header', { name: 'Quick Actions' });
    screen.getByRole('header', { name: 'Recent Activity' });
  });

  test("the empty card is the plain dark card in the light theme too", async () => {
    await renderHome({ data: none, todayWorkout: NONE, scheme: 'light' });

    expect(screen.getByTestId('workout-card-empty')).toHaveStyle({
      backgroundColor: dark.surface,
      borderColor: dark.border,
    });
  });
});
