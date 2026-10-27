import { act, fireEvent, render, screen, within } from '@testing-library/react-native';
import { Dimensions, StyleSheet, type TextStyle } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { MOCK_TODAY_WORKOUT } from '../src/mock/workoutDetailsMock';
import { ThemeProvider, themes, type ThemeScheme } from '../src/theme';
import { CATEGORY_COLORS } from '../src/workouts/categoryColors';
import { MuscleFocus } from '../src/workouts/MuscleFocus';
import type { PlannedExercise, WorkoutDetailsData } from '../src/workouts/planDetails';
import { SECTION_COLORS } from '../src/workouts/sectionColors';
import {
  START_UNAVAILABLE_NOTICE,
  WorkoutDetailsScreen,
} from '../src/workouts/WorkoutDetailsScreen';
import { WORKOUT_FALLBACK_IMAGE, WORKOUT_IMAGES } from '../src/workouts/workoutImages';
import { renderWithTheme } from '../test-utils/renderWithTheme';

const dark = themes.dark.colors;
const light = themes.light.colors;
const HIDDEN = { includeHiddenElements: true };
// the color of a glyph drawn by AppIcon: its wrapper's one child is the font's text
const glyphColor = (icon: { children: unknown[] }) =>
  StyleSheet.flatten((icon.children[0] as unknown as { props: { style: TextStyle } }).props.style)?.color;
// '#0B0D0E' as '11, 13, 14', the way a gradient writes it
const rgbOf = (hex: string) => [1, 3, 5].map((at) => parseInt(hex.slice(at, at + 2), 16)).join(', ');

const exercise = (id: number, over: Partial<PlannedExercise> = {}): PlannedExercise => ({
  id: `e${id}`,
  order: id,
  section: 'MAIN_WORKOUT',
  name: `Exercise ${id}`,
  sets: 3,
  reps: 10,
  ...over,
});

async function renderScreen(
  workout: WorkoutDetailsData = MOCK_TODAY_WORKOUT,
  options: { scheme?: ThemeScheme; onStart?: () => void } = {},
) {
  const onBack = jest.fn();
  const onOpenExercise = jest.fn();
  const onEditWithAI = jest.fn();
  const view = await renderWithTheme(
    <WorkoutDetailsScreen
      workout={workout}
      onBack={onBack}
      onOpenExercise={onOpenExercise}
      onEditWithAI={onEditWithAI}
      onStart={options.onStart}
    />,
    options.scheme,
  );
  return { ...view, onBack, onOpenExercise, onEditWithAI };
}

describe('the top of the screen', () => {
  test("shows the workout's title as the screen's heading, with its length and its number of exercises", async () => {
    await renderScreen();

    expect(screen.getByRole('header', { name: 'Core & Abs Focus' })).toBeOnTheScreen();
    const meta = within(screen.getByTestId('workout-hero-meta'));
    meta.getByText('23 minutes');
    meta.getByText('6 exercises');
    expect(meta.getByTestId('icon-clock-outline', HIDDEN)).toBeOnTheScreen();
    expect(meta.getByTestId('icon-dumbbell', HIDDEN)).toBeOnTheScreen();
  });

  test('counts the exercises it actually has, not a number it was told', async () => {
    await renderScreen({ id: 1, title: 'Two', exercises: [exercise(1), exercise(2)] });

    within(screen.getByTestId('workout-hero-meta')).getByText('2 exercises');
  });

  test('says "1 exercise" for one, and leaves out the length when the workout has none', async () => {
    await renderScreen({ id: 1, title: 'One', exercises: [exercise(1)] });

    const meta = within(screen.getByTestId('workout-hero-meta'));
    meta.getByText('1 exercise');
    expect(meta.queryByText(/minute/)).toBeNull();
    expect(meta.queryByTestId('icon-clock-outline', HIDDEN)).toBeNull();
  });

  test('a length that is not a positive number is left out too', async () => {
    await renderScreen({ id: 1, title: 'W', durationMinutes: 0, exercises: [exercise(1)] });

    expect(within(screen.getByTestId('workout-hero-meta')).queryByText(/minute/)).toBeNull();
  });

  test('a long title wraps to three lines at most and the plan still follows it', async () => {
    const title = 'The Complete Eight Week Progressive Overload Total Body Conditioning And Core Stability Program';
    await renderScreen({ id: 7, title, exercises: [exercise(1)] });

    expect(screen.getByRole('header', { name: title })).toHaveProp('numberOfLines', 3);
    screen.getByRole('header', { name: 'Workout Plan (1)' });
    screen.getByRole('button', { name: /^Exercise 1/ });
  });

  describe('on a phone-sized screen', () => {
    beforeEach(() => Dimensions.set({ window: { width: 400, height: 800, scale: 2, fontScale: 1 } }));
    afterEach(() => Dimensions.set({ window: { width: 750, height: 1334, scale: 2, fontScale: 2 } }));

    test("shows the photograph of the workout's kind behind it, drawn as tall as the hero and as wide as its own shape makes it", async () => {
      await renderScreen();

      const photo = screen.getByTestId('workout-hero-photo');
      expect(photo).toHaveProp('source', WORKOUT_IMAGES['core-abs']);
      expect(photo).toHaveProp('accessible', false);
      expect(photo).toHaveProp('importantForAccessibility', 'no');
      // explicit numbers, as tall as the box: the photograph is as wide as its own shape makes it, not stretched
      const style = photo.props.style;
      expect(style).toMatchObject({ position: 'absolute', top: 0, height: 136 });
      expect(style.width / style.height).toBeCloseTo(737 / 215, 1);
    });

    test("puts the photograph's athlete in the middle of the screen, with the empty gym left for the title", async () => {
      await renderScreen();

      const { left, width } = screen.getByTestId('workout-hero-photo').props.style;
      // the athlete's point is at 0.57 of the picture (core-abs); it lands at half the screen's width
      expect(left + 0.57 * width).toBeCloseTo(400 * 0.5, 0);
      // and the picture never leaves bare page on either side
      expect(left).toBeLessThanOrEqual(0);
      expect(left + width).toBeGreaterThanOrEqual(400);
    });
  });

  test('on a screen wider than the photograph is, the photograph is stretched to the screen rather than leaving the page bare', async () => {
    await renderScreen();

    const { left, width } = screen.getByTestId('workout-hero-photo').props.style;
    expect(left).toBe(0);
    expect(width).toBeGreaterThanOrEqual(750);
  });

  test('a workout with no kind gets the neutral picture, cropped to fill, and no label', async () => {
    await renderScreen({ id: 7, title: 'Plain workout', exercises: [exercise(1)] });

    const photo = screen.getByTestId('workout-hero-photo');
    expect(photo).toHaveProp('source', WORKOUT_FALLBACK_IMAGE);
    expect(photo.props.style).not.toHaveProperty('position');
  });

  test('categories the app does not know are ignored, never guessed at', async () => {
    await renderScreen({
      id: 7,
      title: 'Yoga flow',
      categories: ['yoga'] as unknown as WorkoutDetailsData['categories'],
      exercises: [exercise(1)],
    });

    expect(screen.getByTestId('workout-hero-photo')).toHaveProp('source', WORKOUT_FALLBACK_IMAGE);
  });

  test('a mixed workout is shown with its one deterministic kind, and a known one never as "Beginner"', async () => {
    await renderScreen({ id: 7, title: 'Mixed', categories: ['beginner', 'cardio'], exercises: [exercise(1)] });

    expect(screen.getByTestId('workout-hero-photo')).toHaveProp('source', WORKOUT_IMAGES['cardio-hiit']);
  });

  test('a photograph that fails to load is dropped, and the page color is all that is left behind the title', async () => {
    await renderScreen();

    await fireEvent(screen.getByTestId('workout-hero-photo'), 'error');

    expect(screen.queryByTestId('workout-hero-photo')).toBeNull();
    expect(screen.getByRole('header', { name: 'Core & Abs Focus' })).toBeOnTheScreen();
  });

  test('the photograph fades into the page color at the bottom and on the left, so the title reads on it', async () => {
    await renderScreen();

    const page = rgbOf(dark.background);
    expect(screen.getByTestId('workout-hero-fade-bottom').props.style.backgroundImage).toContain(`linear-gradient(to top, rgba(${page}, 1) 0%`);
    // the veil on the left is lighter on the dark page, where the words are white and the photograph dark
    expect(screen.getByTestId('workout-hero-fade-left').props.style.backgroundImage).toContain(`linear-gradient(to right, rgba(${page}, 0.4) 0%`);
  });

  test('on the pale page the fade is the pale color, and the veil on the left is much stronger', async () => {
    await renderScreen(MOCK_TODAY_WORKOUT, { scheme: 'light' });

    const page = rgbOf(light.background);
    expect(screen.getByTestId('workout-hero-fade-bottom').props.style.backgroundImage).toContain(`rgba(${page}, 1) 0%`);
    expect(screen.getByTestId('workout-hero-fade-left').props.style.backgroundImage).toContain(`rgba(${page}, 0.9) 0%`);
  });
});

describe('the "Covers" pill and the muscle focus', () => {
  test('says what the workout mainly covers, in the colors of its kind', async () => {
    await renderScreen();

    const pill = screen.getByTestId('workout-covers');
    expect(pill).toHaveProp('accessibilityLabel', 'Covers core');
    expect(within(pill).getByText('Covers core')).toHaveStyle({ color: CATEGORY_COLORS.core.dark.label });
    expect(pill).toHaveStyle({ borderColor: CATEGORY_COLORS.core.dark.border, backgroundColor: CATEGORY_COLORS.core.dark.chip });
    expect(within(pill).getByTestId('icon-target', HIDDEN)).toBeOnTheScreen();
  });

  test('"View muscle focus" opens the muscles the workout trains, and closes them again', async () => {
    await renderScreen();
    const toggle = screen.getByRole('button', { name: 'View muscle focus' });
    expect(toggle).toHaveProp('accessibilityState', expect.objectContaining({ expanded: false }));
    expect(screen.queryByTestId('muscle-focus')).toBeNull();
    expect(within(toggle).getByTestId('icon-chevron-right', HIDDEN)).toBeOnTheScreen();

    await fireEvent.press(toggle);

    const focus = screen.getByTestId('muscle-focus');
    expect(within(focus).getByText('Core')).toHaveStyle({ color: CATEGORY_COLORS.core.dark.label });
    for (const name of ['Shoulders', 'Quadriceps']) expect(within(focus).getByText(name)).toHaveStyle({ color: dark.textSecondary });
    // the warm-up's and the cool-down's muscles are not what the workout trains
    expect(within(focus).queryByText('Hamstrings')).toBeNull();
    expect(screen.getByRole('button', { name: 'View muscle focus' })).toHaveProp('accessibilityState', expect.objectContaining({ expanded: true }));
    expect(within(screen.getByRole('button', { name: 'View muscle focus' })).getByTestId('icon-chevron-down', HIDDEN)).toBeOnTheScreen();

    await fireEvent.press(screen.getByRole('button', { name: 'View muscle focus' }));

    expect(screen.queryByTestId('muscle-focus')).toBeNull();
  });

  test('the open focus is one element for a screen reader, which hears the muscles in words', async () => {
    await renderScreen();
    await fireEvent.press(screen.getByRole('button', { name: 'View muscle focus' }));

    expect(screen.getByTestId('muscle-focus')).toHaveProp('accessibilityLabel', 'Muscle focus: Core. also Shoulders, Quadriceps');
  });

  test('neither the pill nor the control is there when no exercise carries muscles (the plan itself has none)', async () => {
    await renderScreen({ id: 1, title: 'W', exercises: [exercise(1), exercise(2)] });

    expect(screen.queryByTestId('workout-covers')).toBeNull();
    expect(screen.queryByRole('button', { name: 'View muscle focus' })).toBeNull();
    expect(screen.queryByTestId('muscle-focus')).toBeNull();
  });

  test("a workout with no kind wears the theme's plain colors", async () => {
    await renderScreen({
      id: 1,
      title: 'W',
      exercises: [exercise(1, { muscles: [{ name: 'Chest', role: 'PRIMARY' }] })],
    });

    const pill = screen.getByTestId('workout-covers');
    expect(within(pill).getByText('Covers chest')).toHaveStyle({ color: dark.textSecondary });
    expect(pill).toHaveStyle({ borderColor: dark.border, backgroundColor: dark.surfaceMuted });
  });

  test('on the pale page the pill and the primary muscles wear the kind\'s light colors', async () => {
    await renderScreen(MOCK_TODAY_WORKOUT, { scheme: 'light' });

    expect(screen.getByTestId('workout-covers')).toHaveStyle({ backgroundColor: CATEGORY_COLORS.core.light.chip, borderColor: CATEGORY_COLORS.core.light.border });
    await fireEvent.press(screen.getByRole('button', { name: 'View muscle focus' }));
    expect(within(screen.getByTestId('muscle-focus')).getByText('Core')).toHaveStyle({ color: CATEGORY_COLORS.core.light.label });
  });
});

describe('<MuscleFocus />', () => {
  test('a focus with only secondary muscles still reads in words', async () => {
    await renderWithTheme(
      <MuscleFocus
        focus={{ primary: [], secondary: ['Calves'] }}
        card={{ label: '#000000', border: '#111111', blend: '#222222', chip: '#333333' }}
      />,
    );

    expect(screen.getByTestId('muscle-focus')).toHaveProp('accessibilityLabel', 'Muscle focus. also Calves');
  });
});

describe('the workout plan', () => {
  test('is headed "Workout Plan" with the number of exercises, beside the Edit with AI button', async () => {
    await renderScreen();

    screen.getByRole('header', { name: 'Workout Plan (6)' });
    screen.getByRole('button', { name: 'Edit with AI' });
    expect(screen.getByTestId('icon-creation', HIDDEN)).toBeOnTheScreen();
  });

  test('has no Overview tab', async () => {
    await renderScreen();

    expect(screen.queryByText('Overview')).toBeNull();
    expect(screen.queryByRole('tab')).toBeNull();
    expect(screen.queryByRole('tablist')).toBeNull();
  });

  test('has three cards in the order the workout is done, each with its count and length', async () => {
    await renderScreen();

    const headings = screen.getAllByRole('header').map((node) => node.props.children);
    expect(headings).toEqual(['Core & Abs Focus', 'Workout Plan (6)', 'Warm-up', 'Main Workout', 'Cool-down']);
    expect(screen.getByRole('button', { name: 'Warm-up, 2 exercises, 3 min' })).toBeOnTheScreen();
    expect(screen.getByRole('button', { name: 'Main Workout, 3 exercises, 18 min' })).toBeOnTheScreen();
    expect(screen.getByRole('button', { name: 'Cool-down, 1 exercise, 2 min' })).toBeOnTheScreen();
    within(screen.getByTestId('section-WARM_UP')).getByText('2 exercises • 3 min');
    within(screen.getByTestId('section-MAIN_WORKOUT')).getByText('3 exercises • 18 min');
    within(screen.getByTestId('section-COOL_DOWN')).getByText('1 exercise • 2 min');
  });

  test("keeps each exercise in its card, in the plan's order, numbered on from one card into the next", async () => {
    await renderScreen();

    const rows = (id: string) =>
      within(screen.getByTestId(id))
        .getAllByRole('button', { name: /sets|set\b|reps/ })
        .map((row) => row.props.accessibilityLabel.split('.')[0]);
    expect(rows('section-WARM_UP')).toEqual(['Mountain Climbers', 'Lunges']);
    expect(rows('section-MAIN_WORKOUT')).toEqual(['Plank', 'Bicycle Crunches', 'Leg Raises']);
    expect(rows('section-COOL_DOWN')).toEqual(['Hamstring Stretch']);
    const badges = screen.getAllByTestId(/^exercise-mock-exercise-\d+-thumbnail-badge$/, HIDDEN);
    badges.forEach((badge, index) => expect(badge).toHaveTextContent(String(index + 1)));
    expect(badges).toHaveLength(6);
  });

  test('puts the exercises in order whatever order the plan arrives in', async () => {
    await renderScreen({
      id: 3,
      title: 'Scrambled',
      exercises: [
        exercise(5, { section: 'COOL_DOWN', name: 'Cool B', order: 6 }),
        exercise(1, { section: 'MAIN_WORKOUT', name: 'Main B', order: 4 }),
        exercise(2, { section: 'WARM_UP', name: 'Warm B', order: 2 }),
        exercise(3, { section: 'COOL_DOWN', name: 'Cool A', order: 5 }),
        exercise(4, { section: 'MAIN_WORKOUT', name: 'Main A', order: 3 }),
        exercise(6, { section: 'WARM_UP', name: 'Warm A', order: 1 }),
      ],
    });

    const order = screen.getAllByRole('button', { name: /^(Warm|Main|Cool) [AB]\./ }).map((row) => row.props.accessibilityLabel.split('.')[0]);
    expect(order).toEqual(['Warm A', 'Warm B', 'Main A', 'Main B', 'Cool A', 'Cool B']);
  });

  test('a section with no exercises has no card, and a section whose length is not known shows only its count', async () => {
    await renderScreen({
      id: 3,
      title: 'No cool-down',
      sectionMinutes: { WARM_UP: 4 },
      exercises: [exercise(1, { section: 'WARM_UP' }), exercise(2, { section: 'MAIN_WORKOUT' })],
    });

    expect(screen.queryByText('Cool-down')).toBeNull();
    expect(screen.queryByTestId('section-COOL_DOWN')).toBeNull();
    within(screen.getByTestId('section-WARM_UP')).getByText('1 exercise • 4 min');
    within(screen.getByTestId('section-MAIN_WORKOUT')).getByText('1 exercise');
  });

  test('each card folds away from its header and opens again, without touching the others', async () => {
    await renderScreen();
    const header = () => screen.getByRole('button', { name: 'Warm-up, 2 exercises, 3 min' });
    expect(header()).toHaveProp('accessibilityState', expect.objectContaining({ expanded: true }));
    expect(header()).toHaveProp('accessibilityHint', 'Folds the section away');
    expect(within(header()).getByTestId('icon-chevron-up', HIDDEN)).toBeOnTheScreen();

    await fireEvent.press(header());

    expect(screen.queryByRole('button', { name: /^Mountain Climbers\./ })).toBeNull();
    expect(screen.queryByRole('button', { name: /^Lunges\./ })).toBeNull();
    expect(screen.getByRole('button', { name: /^Plank\./ })).toBeOnTheScreen();
    expect(header()).toHaveProp('accessibilityState', expect.objectContaining({ expanded: false }));
    expect(header()).toHaveProp('accessibilityHint', 'Opens the section');
    expect(within(header()).getByTestId('icon-chevron-down', HIDDEN)).toBeOnTheScreen();

    await fireEvent.press(header());

    expect(screen.getByRole('button', { name: /^Mountain Climbers\./ })).toBeOnTheScreen();
  });

  test('a folded card keeps its numbers: the others do not renumber', async () => {
    await renderScreen();

    await fireEvent.press(screen.getByRole('button', { name: 'Warm-up, 2 exercises, 3 min' }));

    const badges = screen.getAllByTestId(/-thumbnail-badge$/, HIDDEN);
    expect(badges).toHaveLength(4);
    badges.forEach((badge, index) => expect(badge).toHaveTextContent(String(index + 3)));
  });

  test('each card has the icon of its part on a disc of its color: a figure running, a dumbbell, a snowflake', async () => {
    await renderScreen();

    for (const [section, icon] of [['WARM_UP', 'icon-run-fast'], ['MAIN_WORKOUT', 'icon-dumbbell'], ['COOL_DOWN', 'icon-snowflake']] as const) {
      const disc = screen.getByTestId(`section-${section}-disc`, HIDDEN);
      expect(disc).toHaveStyle({ backgroundColor: SECTION_COLORS[section].dark.accent, borderRadius: 18 });
      expect(within(disc).getByTestId(icon, HIDDEN)).toBeOnTheScreen();
      // the glyph is white on the accent in both themes
      expect(glyphColor(within(disc).getByTestId(icon, HIDDEN))).toBe('#FFFFFF');
    }
  });

  test('the card is the three colors of the design: purple, green and blue, in the dark theme', async () => {
    await renderScreen();

    for (const section of ['WARM_UP', 'MAIN_WORKOUT', 'COOL_DOWN'] as const) {
      const palette = SECTION_COLORS[section].dark;
      expect(screen.getByTestId(`section-${section}`)).toHaveStyle({ borderColor: palette.border, backgroundColor: palette.rows, borderRadius: 16, overflow: 'hidden' });
      expect(screen.getByTestId(`section-${section}-header`)).toHaveStyle({ backgroundColor: palette.header });
    }
  });

  test('the cards use their light colors on the pale page, and the words follow the theme', async () => {
    await renderScreen(MOCK_TODAY_WORKOUT, { scheme: 'light' });

    for (const section of ['WARM_UP', 'MAIN_WORKOUT', 'COOL_DOWN'] as const) {
      const palette = SECTION_COLORS[section].light;
      expect(screen.getByTestId(`section-${section}`)).toHaveStyle({ borderColor: palette.border, backgroundColor: palette.rows });
      expect(screen.getByTestId(`section-${section}-header`)).toHaveStyle({ backgroundColor: palette.header });
    }
    expect(screen.getByText('Main Workout')).toHaveStyle({ color: light.textPrimary });
    expect(screen.getByText('3 exercises • 18 min')).toHaveStyle({ color: light.textSecondary });
  });

  test('pressing a row opens that exercise', async () => {
    const { onOpenExercise } = await renderScreen();

    await fireEvent.press(screen.getByRole('button', { name: /^Leg Raises\./ }));

    expect(onOpenExercise).toHaveBeenCalledTimes(1);
    expect(onOpenExercise.mock.calls[0][0]).toMatchObject({ id: 'mock-exercise-5', name: 'Leg Raises' });
  });

  test('a workout with no exercises says so, offers no card, and cannot be started', async () => {
    await renderScreen({ id: 1, title: 'Empty', exercises: [] });

    screen.getByRole('header', { name: 'Workout Plan (0)' });
    screen.getByText('No exercises');
    screen.getByText('This workout has no exercises yet.');
    expect(screen.queryByTestId('section-MAIN_WORKOUT')).toBeNull();
    expect(screen.getByRole('button', { name: 'Start Workout' })).toBeDisabled();
  });

  test('an exercise with no picture shows its placeholder, in its own row only', async () => {
    await renderScreen({ id: 1, title: 'W', exercises: [exercise(1, { image: null }), exercise(2, { image: MOCK_TODAY_WORKOUT.exercises[2].image })] });

    expect(screen.queryByTestId('exercise-e1-thumbnail')).toBeNull();
    expect(screen.getByTestId('exercise-e1-thumbnail-placeholder', HIDDEN)).toBeOnTheScreen();
    expect(screen.getByTestId('exercise-e2-thumbnail')).toBeOnTheScreen();
  });

  test('a picture that fails to load falls back to the placeholder in its own row only', async () => {
    await renderScreen();

    await fireEvent(screen.getByTestId('exercise-mock-exercise-3-thumbnail'), 'error');

    expect(screen.queryByTestId('exercise-mock-exercise-3-thumbnail')).toBeNull();
    expect(screen.getByTestId('exercise-mock-exercise-4-thumbnail')).toBeOnTheScreen();
  });
});

describe('the Back button over the photograph', () => {
  test('Back goes back, and nothing else happens', async () => {
    const { onBack, onEditWithAI, onOpenExercise } = await renderScreen();

    await fireEvent.press(screen.getByRole('button', { name: 'Back' }));

    expect(onBack).toHaveBeenCalledTimes(1);
    expect(onEditWithAI).not.toHaveBeenCalled();
    expect(onOpenExercise).not.toHaveBeenCalled();
  });

  test('Back is the only button over the photograph: there is no heart and no more-options button', async () => {
    await renderScreen();

    const bar = within(screen.getByTestId('workout-details-top-bar'));
    expect(bar.getAllByRole('button')).toHaveLength(1);
    expect(bar.getByRole('button', { name: 'Back' })).toBeOnTheScreen();
    for (const name of [/favorite/i, /more options/i]) expect(screen.queryByRole('button', { name })).toBeNull();
    expect(screen.queryByTestId('icon-heart-outline', HIDDEN)).toBeNull();
    expect(screen.queryByTestId('icon-heart', HIDDEN)).toBeNull();
    expect(screen.queryByTestId('icon-dots-horizontal', HIDDEN)).toBeNull();
  });

  test('is round, dark and see-through with a white icon in the dark theme, and the same in the light one', async () => {
    for (const scheme of ['dark', 'light'] as const) {
      const { unmount } = await renderScreen(MOCK_TODAY_WORKOUT, { scheme });

      const back = screen.getByRole('button', { name: 'Back' });
      expect(back).toHaveStyle({ width: 36, height: 36, borderRadius: 18, borderColor: 'rgba(255, 255, 255, 0.32)', backgroundColor: 'rgba(8, 10, 12, 0.58)' });
      // a white icon whatever the theme: the circle is dark in both
      expect(glyphColor(within(back).getByTestId('icon-arrow-left', HIDDEN))).toBe('#FFFFFF');
      await unmount();
    }
  });

  test('stays in reach: it is over the scrolling page, not in it', async () => {
    await renderScreen();

    expect(within(screen.getByTestId('workout-details-scroll')).queryByRole('button', { name: 'Back' })).toBeNull();
    expect(within(screen.getByTestId('workout-details-top-bar')).getByRole('button', { name: 'Back' })).toBeOnTheScreen();
  });

  test('the veil behind the status bar is faint over the photograph and nearly solid once the page has scrolled', async () => {
    await renderScreen();
    const page = rgbOf(dark.background);
    expect(screen.getByTestId('workout-details-top-veil').props.style.backgroundImage).toContain(`linear-gradient(to bottom, rgba(${page}, 0.35) 0%`);

    await fireEvent.scroll(screen.getByTestId('workout-details-scroll'), { nativeEvent: { contentOffset: { y: 120 } } });

    expect(screen.getByTestId('workout-details-top-veil').props.style.backgroundImage).toContain(`rgba(${page}, 0.96) 0%`);

    await fireEvent.scroll(screen.getByTestId('workout-details-scroll'), { nativeEvent: { contentOffset: { y: 0 } } });

    expect(screen.getByTestId('workout-details-top-veil').props.style.backgroundImage).toContain(`rgba(${page}, 0.35) 0%`);
  });

  test('on the pale page the veil over the photograph is stronger, for the dark icons', async () => {
    await renderScreen(MOCK_TODAY_WORKOUT, { scheme: 'light' });

    expect(screen.getByTestId('workout-details-top-veil').props.style.backgroundImage).toContain(`rgba(${rgbOf(light.background)}, 0.8) 0%`);
  });
});

describe('"Edit with AI"', () => {
  test('opens the coach with this workout, and nothing else happens', async () => {
    const { onEditWithAI, onOpenExercise, onBack } = await renderScreen();

    await fireEvent.press(screen.getByRole('button', { name: 'Edit with AI' }));

    expect(onEditWithAI).toHaveBeenCalledTimes(1);
    expect(onOpenExercise).not.toHaveBeenCalled();
    expect(onBack).not.toHaveBeenCalled();
    expect(screen.queryByTestId('toast')).toBeNull();
  });

  test('is the green button with the sparkles, slim but a full touch target', async () => {
    await renderScreen();

    const button = screen.getByRole('button', { name: 'Edit with AI' });
    expect(button).toHaveStyle({ backgroundColor: dark.primary, minHeight: 34 });
    expect(button).toHaveProp('hitSlop', 7);
  });

  test('tells a screen reader the workout stays as it is until a change is approved', async () => {
    await renderScreen();

    expect(screen.getByRole('button', { name: 'Edit with AI' })).toHaveProp(
      'accessibilityHint',
      'Opens the coach with this workout. The workout stays as it is until you approve a change.',
    );
  });

  test('says nothing was saved or changed, because nothing here can save or change a workout', async () => {
    await renderScreen();

    expect(screen.queryByText(/saved|updated|revised/i)).toBeNull();
  });
});

describe('"Start Workout"', () => {
  test('is a primary button with a play triangle at the bottom, outside the scrolling page, so it stays in view', async () => {
    await renderScreen();

    const start = screen.getByRole('button', { name: 'Start Workout' });
    expect(within(screen.getByTestId('workout-details-footer')).getByRole('button', { name: 'Start Workout' })).toBe(start);
    expect(within(screen.getByTestId('workout-details-scroll')).queryByText('Start Workout')).toBeNull();
    expect(start).toHaveStyle({ backgroundColor: dark.primary });
    expect(within(start).getByTestId('icon-play', HIDDEN)).toBeOnTheScreen();
    expect(start).toBeEnabled();
  });

  test('says it is not available yet and starts nothing, while the app has no session flow', async () => {
    const { onEditWithAI, onOpenExercise } = await renderScreen();

    await fireEvent.press(screen.getByRole('button', { name: 'Start Workout' }));

    within(screen.getByTestId('toast')).getByText(START_UNAVAILABLE_NOTICE);
    expect(START_UNAVAILABLE_NOTICE).toBe("Starting a workout isn't available yet. Nothing was started.");
    expect(onEditWithAI).not.toHaveBeenCalled();
    expect(onOpenExercise).not.toHaveBeenCalled();
    // still on the workout, with nothing marked as started
    screen.getByRole('header', { name: 'Core & Abs Focus' });
    expect(screen.queryByText(/in progress|started!|resume/i)).toBeNull();
  });

  test('the notice is announced politely and sits above the button, never over it', async () => {
    await renderScreen();

    await fireEvent.press(screen.getByRole('button', { name: 'Start Workout' }));

    expect(screen.getByTestId('toast')).toHaveProp('accessibilityLiveRegion', 'polite');
    expect(within(screen.getByTestId('workout-details-footer')).queryByTestId('toast')).toBeNull();
    expect(screen.getByTestId('toast-layer')).toHaveProp('pointerEvents', 'none');
  });

  test('calls the session flow when the app has one, and then shows no notice', async () => {
    const onStart = jest.fn();
    await renderScreen(MOCK_TODAY_WORKOUT, { onStart });

    await fireEvent.press(screen.getByRole('button', { name: 'Start Workout' }));

    expect(onStart).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId('toast')).toBeNull();
  });

  test('the notice goes by itself', async () => {
    jest.useFakeTimers({ doNotFake: ['nextTick', 'setImmediate', 'queueMicrotask'] });
    try {
      await renderScreen();
      await fireEvent.press(screen.getByRole('button', { name: 'Start Workout' }));
      expect(screen.getByTestId('toast')).toBeOnTheScreen();

      await act(async () => {
        jest.advanceTimersByTime(4100);
      });

      expect(screen.queryByTestId('toast')).toBeNull();
    } finally {
      jest.useRealTimers();
    }
  });
});

describe('the page', () => {
  test('is a solid near-black screen in the dark theme: the photograph is the top of it, not the page', async () => {
    await renderScreen();

    expect(screen.getByTestId('workout-details')).toHaveStyle({ flex: 1, backgroundColor: dark.background });
    expect(screen.queryByTestId('tab-photo')).toBeNull();
    expect(screen.queryByTestId('photo-backdrop')).toBeNull();
    // the only pictures are the hero's photograph and the thumbnails inside the exercise rows
    expect(screen.getAllByTestId(/-thumbnail$|^workout-hero-photo$/)).toHaveLength(1 + 6);
  });

  test('is the pale themed screen in the light theme, with dark titles', async () => {
    await renderScreen(MOCK_TODAY_WORKOUT, { scheme: 'light' });

    expect(screen.getByTestId('workout-details')).toHaveStyle({ backgroundColor: light.background });
    expect(screen.getByRole('header', { name: 'Core & Abs Focus' })).toHaveStyle({ color: light.textPrimary });
    expect(screen.getByRole('header', { name: 'Workout Plan (6)' })).toHaveStyle({ color: light.textPrimary });
    expect(screen.getByTestId('workout-details-footer')).toHaveStyle({ backgroundColor: light.background });
  });

  test('the footer sits on the page color with no line above it, and the last rows fade into it', async () => {
    await renderScreen();

    expect(screen.getByTestId('workout-details-footer')).toHaveStyle({ backgroundColor: dark.background });
    expect(screen.getByTestId('workout-details-footer')).not.toHaveStyle({ borderTopWidth: 1 });
    expect(screen.getByTestId('workout-details-bottom-fade').props.style.backgroundImage).toContain(`linear-gradient(to top, rgba(${rgbOf(dark.background)}, 1) 0%`);
    expect(screen.getByTestId('workout-details-bottom-fade')).toHaveProp('pointerEvents', 'none');
  });

  describe('safe areas', () => {
    const metrics = {
      frame: { x: 0, y: 0, width: 360, height: 800 },
      insets: { top: 40, bottom: 20, left: 8, right: 4 },
    };
    const renderWithInsets = () =>
      render(
        <SafeAreaProvider initialMetrics={metrics}>
          <ThemeProvider>
            <WorkoutDetailsScreen workout={MOCK_TODAY_WORKOUT} onBack={jest.fn()} onOpenExercise={jest.fn()} onEditWithAI={jest.fn()} />
          </ThemeProvider>
        </SafeAreaProvider>,
      );

    test('keeps the button clear of the system bar and of a cut-out beside it', async () => {
      await renderWithInsets();

      expect(screen.getByTestId('workout-details-footer')).toHaveStyle({
        paddingBottom: 20 + 12,
        paddingLeft: 8 + 16,
        paddingRight: 4 + 16,
      });
    });

    test('keeps the buttons over the photograph below the status bar and clear of the sides', async () => {
      await renderWithInsets();

      expect(screen.getByTestId('workout-details-top-bar')).toHaveStyle({
        paddingTop: 40 + 6,
        paddingLeft: 8 + 20 - 4,
        paddingRight: 4 + 20 - 4,
      });
    });

    test('lets the photograph reach the top of the screen, behind the status bar, and keeps the title below the buttons', async () => {
      await renderWithInsets();

      const hero = screen.getByTestId('workout-hero');
      expect(hero).toBeOnTheScreen();
      expect(screen.getByTestId('workout-details')).not.toHaveStyle({ paddingTop: 40 });
      // the title block starts below the status bar, the buttons' row and a gap
      expect(screen.getByRole('header', { name: 'Core & Abs Focus' }).parent).toHaveStyle({
        paddingTop: 40 + 6 + 36 + 30,
        paddingLeft: 8 + 20,
        paddingRight: 4 + 20,
      });
    });

    test('draws the photograph as tall as the status bar plus its own height, so it reaches under the bar', async () => {
      await renderWithInsets();

      expect(screen.getByTestId('workout-hero-photo').props.style.height).toBe(40 + 136);
    });

    test('keeps the cards clear of a cut-out beside them', async () => {
      await renderWithInsets();

      expect(screen.getByTestId('section-WARM_UP').parent).toHaveStyle({ paddingLeft: 8 + 16, paddingRight: 4 + 16 });
    });
  });
});
