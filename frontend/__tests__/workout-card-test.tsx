import { fireEvent, render, screen, within } from '@testing-library/react-native';
import type { ReactElement } from 'react';
import { Platform, StyleSheet } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { WORKOUT_CATEGORIES, WORKOUT_CATEGORY_LABELS, type WorkoutCategory } from '../src/workouts/categories';
import { CATEGORY_COLORS } from '../src/workouts/categoryColors';
import type { WorkoutCardData } from '../src/workouts/types';
import { EmptyWorkoutCard, WorkoutCard, workoutMeta } from '../src/workouts/WorkoutCard';
import {
  WORKOUT_FALLBACK_IMAGE,
  WORKOUT_IMAGE_FILES,
  WORKOUT_IMAGE_FRAMING,
  WORKOUT_IMAGES,
  workoutImageKey,
  type WorkoutImageKey,
} from '../src/workouts/workoutImages';
import { ThemeProvider, themes, type ThemeScheme } from '../src/theme';
import { renderWithTheme } from '../test-utils/renderWithTheme';

const dark = themes.dark.colors;
const light = themes.light.colors;
const SCHEMES = ['dark', 'light'] as const;
// '#0F2A22' as '15, 42, 34', the way the fade's gradient writes it
const rgbOf = (hex: string) => [1, 3, 5].map((at) => parseInt(hex.slice(at, at + 2), 16)).join(', ');
const HIDDEN = { includeHiddenElements: true };
const KEYS = Object.keys(WORKOUT_IMAGE_FILES) as WorkoutImageKey[];

// Stand-ins for the photos: the lookup is the same whether or not the real files are bundled yet.
const TEST_PHOTOS = Object.fromEntries(KEYS.map((key) => [key, { uri: `test://${key}.png` }])) as Record<
  WorkoutImageKey,
  { uri: string }
>;

// The photos as the app registers them. A test swaps in the stand-ins above, or clears the table, and
// must put these back.
const BUNDLED = { ...WORKOUT_IMAGES };
const clearPhotos = () => {
  for (const key of KEYS) delete WORKOUT_IMAGES[key];
};
const restoreBundled = () => {
  clearPhotos();
  Object.assign(WORKOUT_IMAGES, BUNDLED);
};

const WORKOUT: WorkoutCardData = {
  id: 'w1',
  title: 'Core & Abs Focus',
  description: 'Strengthen your core and improve stability.',
  durationMinutes: 23,
  exerciseCount: 5,
  categories: ['core'],
};

async function renderCard(
  workout: WorkoutCardData = WORKOUT,
  props: { onPress?: () => void; actionLabel?: string } = {},
  scheme: ThemeScheme = 'dark',
) {
  return renderWithTheme(<WorkoutCard workout={workout} {...props} />, scheme);
}

const style = (element: { props: Record<string, unknown> }) => StyleSheet.flatten(element.props.style as never);

describe('what a workout card shows', () => {
  test('the kind, the title, the description, the length and the exercise count', async () => {
    await renderCard();

    screen.getByText('Strength');
    screen.getByText('Core & Abs Focus');
    screen.getByText('Strengthen your core and improve stability.');
    screen.getByText('23 min');
    screen.getByText('5 exercises');
  });

  test("the kind is a small heading in capitals, in its category's own color", async () => {
    await renderCard();

    expect(screen.getByText('Strength')).toHaveStyle({
      textTransform: 'uppercase',
      color: CATEGORY_COLORS.core.dark.label,
      fontSize: 12,
      fontWeight: '600',
    });
  });

  test('the title is white and bold, the description and details muted', async () => {
    await renderCard();

    expect(screen.getByText('Core & Abs Focus')).toHaveStyle({ color: dark.textPrimary, fontWeight: '700' });
    expect(screen.getByText('Strengthen your core and improve stability.')).toHaveStyle({ color: dark.textSecondary });
    expect(screen.getByText('23 min')).toHaveStyle({ color: dark.textSecondary });
  });

  test('has a stable test id from the workout id', async () => {
    await renderCard({ ...WORKOUT, id: 42 });

    expect(screen.getByTestId('workout-card-42')).toBeOnTheScreen();
  });
});

describe('the picture follows the workout kind', () => {
  beforeEach(() => {
    Object.assign(WORKOUT_IMAGES, TEST_PHOTOS);
  });
  afterEach(restoreBundled);

  test.each(WORKOUT_CATEGORIES.map((category) => [category]))(
    'a %s workout shows its own photo and its own label',
    async (category) => {
      await renderCard({ ...WORKOUT, categories: [category] });

      expect(screen.getByTestId('workout-card-w1-photo')).toHaveProp('source', TEST_PHOTOS[workoutImageKey(category)]);
      screen.getByText(WORKOUT_CATEGORY_LABELS[category]);
    },
  );

  test('every kind of workout is laid out the same way: same card size, radius and type, same photo box, same crop', async () => {
    const seen: { card: unknown; title: unknown; box: unknown; resizeMode: unknown }[] = [];
    for (const category of WORKOUT_CATEGORIES) {
      const view = await renderCard({ ...WORKOUT, categories: [category] });
      const photo = screen.getByTestId('workout-card-w1-photo');
      const { backgroundColor: _surface, borderColor: _outline, ...cardLayout } = style(screen.getByTestId('workout-card-w1')) as Record<string, unknown>;
      seen.push({
        // everything but the colors, which are the category's
        card: cardLayout,
        title: { ...style(screen.getByText('Core & Abs Focus')) },
        box: { ...style(photo.parent as never) },
        resizeMode: photo.props.resizeMode,
      });
      await view.unmount();
    }

    for (const one of seen) expect(one).toEqual(seen[0]);
    expect(seen[0].resizeMode).toBe('cover');
  });

  test.each(WORKOUT_CATEGORIES.map((category) => [category]))(
    'a %s photo is framed on its own subject: as tall as the card, in its own shape, its point at the same place in the box',
    async (category) => {
      await renderCard({ ...WORKOUT, categories: [category] });

      const framing = WORKOUT_IMAGE_FRAMING[workoutImageKey(category)];
      const photo = screen.getByTestId('workout-card-w1-photo');
      expect(style(photo)).toEqual({
        position: 'absolute',
        top: 0,
        height: '100%',
        minWidth: '100%',
        aspectRatio: framing.width / framing.height,
        // the same place for every photo, right of the text
        left: '66%',
        transform: [{ translateX: `-${Math.round(framing.focus * 10000) / 100}%` }],
      });
      // so no photo can show the bare card behind it on the right
      expect(framing.focus).toBeGreaterThan(0.4);
      expect(framing.focus).toBeLessThan(0.8);
    },
  );

  test('the photo box clips, so a photo wider than it never shows on the text side', async () => {
    await renderCard({ ...WORKOUT, categories: ['cardio'] });

    expect(screen.getByTestId('workout-card-w1-photo').parent).toHaveStyle({ overflow: 'hidden' });
  });

  test('a mixed workout shows the photo of its one deterministic kind, whatever order it is given in', async () => {
    const first = await renderCard({ ...WORKOUT, categories: ['cardio', 'core'] });
    const source = screen.getByTestId('workout-card-w1-photo').props.source;
    await first.unmount();
    await renderCard({ ...WORKOUT, categories: ['core', 'cardio'] });

    expect(screen.getByTestId('workout-card-w1-photo')).toHaveProp('source', source);
    expect(source).toBe(TEST_PHOTOS['core-abs']);
  });

  test('a known workout is not relabelled because it is also for beginners', async () => {
    await renderCard({ ...WORKOUT, categories: ['beginner', 'lower-body'] });

    expect(screen.getByTestId('workout-card-w1-photo')).toHaveProp('source', TEST_PHOTOS['lower-body']);
    screen.getByText('Strength');
    expect(screen.queryByText('Beginner')).toBeNull();
  });

  test('a beginner workout of no other kind shows the beginner photo', async () => {
    await renderCard({ ...WORKOUT, categories: ['beginner'] });

    expect(screen.getByTestId('workout-card-w1-photo')).toHaveProp('source', TEST_PHOTOS.beginner);
    screen.getByText('Beginner');
  });
});

describe('when the kind or the photo is not known', () => {
  afterEach(restoreBundled);

  test.each([
    ['has no categories', { categories: undefined }],
    ['has an empty list of them', { categories: [] }],
    ['has only unknown ones', { categories: ['yoga'] as unknown as WorkoutCategory[] }],
  ])('a workout that %s shows the neutral picture and no kind', async (_name, extra) => {
    await renderCard({ ...WORKOUT, ...extra });

    const photo = screen.getByTestId('workout-card-w1-photo');
    expect(photo).toHaveProp('source', WORKOUT_FALLBACK_IMAGE);
    // the neutral picture is plainly cropped to the box: nothing is framed on a subject it does not have
    expect(style(photo)).toEqual({ width: '100%', height: '100%' });
    expect(screen.queryByText('Strength')).toBeNull();
    for (const label of new Set(Object.values(WORKOUT_CATEGORY_LABELS))) expect(screen.queryByText(label)).toBeNull();
    screen.getByText('Core & Abs Focus');
  });

  test('a known kind whose photo is not bundled shows its label over the neutral picture', async () => {
    delete WORKOUT_IMAGES.mobility;
    await renderCard({ ...WORKOUT, categories: ['mobility'] });

    screen.getByText('Mobility');
    expect(screen.getByTestId('workout-card-w1-photo')).toHaveProp('source', WORKOUT_FALLBACK_IMAGE);
  });
});

describe('missing details are left out, never filled in', () => {
  test('no length: no "min" and nothing in its place', async () => {
    await renderCard({ ...WORKOUT, durationMinutes: undefined });

    expect(screen.queryByText(/min/)).toBeNull();
    screen.getByText('5 exercises');
    expect(screen.queryByTestId('icon-clock-outline', HIDDEN)).toBeNull();
  });

  test('no exercise count: no "exercises" and nothing in its place', async () => {
    await renderCard({ ...WORKOUT, exerciseCount: null });

    expect(screen.queryByText(/exercise/)).toBeNull();
    screen.getByText('23 min');
  });

  test('neither: no details row at all', async () => {
    await renderCard({ ...WORKOUT, durationMinutes: null, exerciseCount: undefined });

    expect(screen.queryByTestId('workout-card-meta')).toBeNull();
    expect(screen.queryByText(/min|exercise/)).toBeNull();
  });

  test('one detail alone has no divider beside it, two have one between them', async () => {
    const one = await renderCard({ ...WORKOUT, durationMinutes: undefined });
    expect(screen.getByTestId('workout-card-meta').children).toHaveLength(1);
    await one.unmount();

    await renderCard();
    expect(screen.getByTestId('workout-card-meta').children).toHaveLength(2);
  });

  test('no description, a blank one or a null one: no description line', async () => {
    for (const description of [undefined, null, '', '   ']) {
      const view = await renderCard({ ...WORKOUT, description });
      expect(screen.queryByText(/Strengthen/)).toBeNull();
      screen.getByText('Core & Abs Focus');
      await view.unmount();
    }
  });

  test('only the title: a card with just a name still reads well', async () => {
    await renderCard({ id: 1, title: 'Walk' });

    screen.getByText('Walk');
    expect(screen.queryByTestId('workout-card-meta')).toBeNull();
  });

  test.each([
    [0, 'zero'],
    [-3, 'negative'],
    [Number.NaN, 'not a number'],
    [Number.POSITIVE_INFINITY, 'infinite'],
  ])('a length of %s (%s) is treated as missing', (minutes) => {
    expect(workoutMeta({ durationMinutes: minutes })).toEqual([]);
  });

  test.each([
    [0, 'zero'],
    [-1, 'negative'],
    [2.5, 'not whole'],
    [Number.NaN, 'not a number'],
  ])('an exercise count of %s (%s) is treated as missing', (count) => {
    expect(workoutMeta({ exerciseCount: count })).toEqual([]);
  });

  test('a length is rounded to whole minutes, and one exercise is singular', () => {
    expect(workoutMeta({ durationMinutes: 22.6, exerciseCount: 1 })).toEqual([
      { key: 'duration', text: '23 min' },
      { key: 'exercises', text: '1 exercise' },
    ]);
    expect(workoutMeta({ durationMinutes: 0.4 })).toEqual([]);
  });

  test('no number from the design sample is anywhere in the card unless it was given', async () => {
    await renderCard({ id: 'x', title: 'Mystery' });

    expect(screen.queryByText(/\d/)).toBeNull();
  });
});

describe('long and awkward text', () => {
  const LONG = 'Upper Body Hypertrophy Foundations With Extended Mobility Finisher And A Very Long Name';

  test('a long title wraps to two lines, then is cut with an ellipsis, with the details still below it', async () => {
    await renderCard({ ...WORKOUT, title: LONG });

    const title = screen.getByText(LONG);
    expect(title).toHaveProp('numberOfLines', 2);
    expect(title).toHaveProp('textBreakStrategy', 'balanced');
    // the title and the description are in one column that stops short of the photo; the details come after it
    const order = screen.getAllByText(/./).map((node) => String(node.props.children));
    expect(order.indexOf(LONG)).toBeGreaterThanOrEqual(0);
    expect(order.indexOf(LONG)).toBeLessThan(order.indexOf('23 min'));
    expect(screen.getByTestId('workout-card-meta')).toBeOnTheScreen();
  });

  test('a long description is held to two lines too', async () => {
    const description = 'Short, hard intervals followed by brief recoveries, repeated until the clock runs out. '.repeat(3);
    await renderCard({ ...WORKOUT, description });

    expect(screen.getByText(description.trim())).toHaveProp('numberOfLines', 2);
  });

  test('the words keep to the left of the card, clear of the photo', async () => {
    await renderCard({ ...WORKOUT, title: LONG });

    const column = screen.getByText(LONG).parent!;
    expect(style(column)).toMatchObject({ maxWidth: '55%' });
  });

  test('text is trimmed: surrounding spaces in a description are not shown', async () => {
    await renderCard({ ...WORKOUT, description: '  Strengthen your core.  ' });

    screen.getByText('Strengthen your core.');
  });
});

describe('opening a workout', () => {
  test('a card with something to open is one button, named by what it says', async () => {
    const onPress = jest.fn();
    await renderCard(WORKOUT, { onPress });

    const card = screen.getByRole('button');
    expect(card).toHaveAccessibleName(
      'Core & Abs Focus, Strength. Strengthen your core and improve stability. 23 min, 5 exercises.',
    );
    expect(screen.getAllByRole('button')).toHaveLength(1);
    await fireEvent.press(card);
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  test('the name carries only what the card shows', async () => {
    await renderCard({ id: 1, title: 'Walk', exerciseCount: 1 }, { onPress: jest.fn() });

    expect(screen.getByRole('button')).toHaveAccessibleName('Walk. 1 exercise.');
  });

  test('a card with nothing to open is not a button and is not announced as one', async () => {
    await renderCard();

    expect(screen.queryByRole('button')).toBeNull();
    screen.getByText('Core & Abs Focus');
  });

  test('the call to action is drawn only on a card that can be pressed, and is part of the one button', async () => {
    const onPress = jest.fn();
    const view = await renderCard(WORKOUT, { onPress, actionLabel: 'Start Workout' });

    const pill = screen.getByTestId('workout-card-action');
    expect(within(pill).getByText('Start Workout')).toHaveStyle({ color: dark.textOnPrimary });
    expect(pill).toHaveStyle({ backgroundColor: dark.primary });
    expect(screen.getAllByRole('button')).toHaveLength(1);
    expect(screen.getByRole('button')).toHaveProp('accessibilityHint', 'Start Workout');
    await fireEvent.press(screen.getByText('Start Workout'));
    expect(onPress).toHaveBeenCalledTimes(1);
    await view.unmount();

    // a call to action that does nothing would be a lie
    await renderCard(WORKOUT, { actionLabel: 'Start Workout' });
    expect(screen.queryByText('Start Workout')).toBeNull();
  });

  test('a card without a call to action is a plain card that opens the workout', async () => {
    await renderCard(WORKOUT, { onPress: jest.fn() });

    expect(screen.queryByTestId('workout-card-action')).toBeNull();
  });

  test.each(['dark', 'light'] as const)(
    'pressing lays a dark scrim over the whole card, never a pale one: in the %s theme',
    async (scheme) => {
      await renderCard(WORKOUT, { onPress: jest.fn() }, scheme);
      const touch = { nativeEvent: { touches: [], changedTouches: [], timestamp: 0 }, persist: () => undefined };

      expect(screen.queryByTestId('workout-card-w1-pressed')).toBeNull();
      await fireEvent(screen.getByTestId('workout-card-w1'), 'responderGrant', touch);

      // one overlay filling the card, black at a low strength, over the photo and the words alike
      const scrim = screen.getByTestId('workout-card-w1-pressed');
      expect(scrim).toHaveStyle({
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.16)',
      });
      expect(scrim).toHaveProp('pointerEvents', 'none');
      // the card is not faded (that would blend it with the page behind it, which is pale in the light theme),
      // and its own surface and outline are as they were
      const card = screen.getByTestId('workout-card-w1');
      expect(card).not.toHaveStyle({ opacity: 0.9 });
      expect(card).not.toHaveProp('needsOffscreenAlphaCompositing');
      expect(card).toHaveStyle({ backgroundColor: CATEGORY_COLORS.core.dark.blend, overflow: 'hidden', borderRadius: 16 });
    },
  );

  test('has no Android ripple: it was drawn under the photo, so it lit only the text side whenever a finger came down to scroll', async () => {
    const os = jest.replaceProperty(Platform, 'OS', 'android');
    try {
      await renderCard(WORKOUT, { onPress: jest.fn() });

      expect(screen.getByTestId('workout-card-w1')).not.toHaveProp('nativeBackgroundAndroid');
    } finally {
      os.restore();
    }
  });
});

describe('the colors a card is drawn in', () => {
  const cases = WORKOUT_CATEGORIES.flatMap((category) => SCHEMES.map((scheme) => [category, scheme] as const));

  test.each(cases)(
    "%s, %s theme: its category's dark surface, outline and heading color, and the photo fades into that surface",
    async (category, scheme) => {
      await renderCard({ ...WORKOUT, categories: [category] }, {}, scheme);

      // the dark palette in both themes: a card is a dark card over a dark photograph
      const colors = CATEGORY_COLORS[category].dark;
      expect(screen.getByTestId('workout-card-w1')).toHaveStyle({
        backgroundColor: colors.blend,
        borderColor: colors.border,
        borderRadius: 16,
        borderWidth: 1,
        overflow: 'hidden',
      });
      expect(screen.getByText(WORKOUT_CATEGORY_LABELS[category])).toHaveStyle({ color: colors.label });
      // under the photo, and the fade over it, are the same surface: the photo's edge is never seen
      expect(screen.getByTestId('workout-card-w1-placeholder', HIDDEN)).toHaveStyle({ backgroundColor: colors.blend });
      const fade = screen.getByTestId('workout-card-w1-photo').parent!.children[2] as unknown as {
        props: { style: { backgroundImage: string } };
      };
      expect(fade.props.style.backgroundImage).toContain(`rgba(${rgbOf(colors.blend)}, 1) 0%`);
      expect(fade.props.style.backgroundImage).toContain(`rgba(${rgbOf(colors.blend)}, 0) 100%`);
    },
  );

  test('different categories are drawn in different colors, not one color for every card', async () => {
    const surfaces = new Set<string>();
    const headings = new Set<string>();
    for (const category of WORKOUT_CATEGORIES) {
      const view = await renderCard({ ...WORKOUT, categories: [category] });
      surfaces.add(style(screen.getByTestId('workout-card-w1')).backgroundColor as string);
      headings.add(style(screen.getByText(WORKOUT_CATEGORY_LABELS[category])).color as string);
      await view.unmount();
    }

    expect(surfaces.size).toBe(WORKOUT_CATEGORIES.length);
    expect(headings.size).toBe(WORKOUT_CATEGORIES.length);
  });

  test.each(cases)('%s, %s theme: no part of the card is Formiq emerald but the call to action', async (category, scheme) => {
    await renderCard({ ...WORKOUT, categories: [category] }, { onPress: jest.fn(), actionLabel: 'Start Workout' }, scheme);

    const emerald = [dark.primary, dark.primaryPressed, dark.primarySubtle, dark.accent];
    const card = style(screen.getByTestId('workout-card-w1'));
    expect(emerald).not.toContain(card.backgroundColor);
    expect(emerald).not.toContain(card.borderColor);
    expect(emerald).not.toContain(style(screen.getByText(WORKOUT_CATEGORY_LABELS[category])).color);
    expect(screen.getByTestId('workout-card-action')).toHaveStyle({ backgroundColor: dark.primary });
  });

  test.each(SCHEMES)('the words are the dark theme\'s in the %s theme too: white titles on the dark card', async (scheme) => {
    await renderCard(WORKOUT, { onPress: jest.fn(), actionLabel: 'Start Workout' }, scheme);

    const colors = themes.dark.colors;
    expect(screen.getByText('Core & Abs Focus')).toHaveStyle({ color: colors.textPrimary });
    expect(screen.getByText('Strengthen your core and improve stability.')).toHaveStyle({ color: colors.textSecondary });
    expect(screen.getByText('23 min')).toHaveStyle({ color: colors.textSecondary });
    expect(within(screen.getByTestId('workout-card-action')).getByText('Start Workout')).toHaveStyle({
      color: colors.textOnPrimary,
    });
  });

  test.each(SCHEMES)('a workout of no known kind has the plain dark surface and outline and no heading, in the %s theme', async (scheme) => {
    await renderCard({ ...WORKOUT, categories: undefined }, {}, scheme);

    const colors = themes.dark.colors;
    expect(screen.getByTestId('workout-card-w1')).toHaveStyle({
      backgroundColor: colors.surface,
      borderColor: colors.border,
    });
    for (const label of new Set(Object.values(WORKOUT_CATEGORY_LABELS))) expect(screen.queryByText(label)).toBeNull();
  });

  test('the light theme keeps the dark card: the same surface, white words, and the details and icons in the dark theme\'s colors', async () => {
    const dark_ = await renderCard(WORKOUT, {}, 'dark');
    const darkSurface = style(screen.getByTestId('workout-card-w1')).backgroundColor;
    await dark_.unmount();

    await renderCard(WORKOUT, { onPress: jest.fn(), actionLabel: 'Start Workout' }, 'light');

    expect(screen.getByTestId('workout-card-w1')).toHaveStyle({ backgroundColor: CATEGORY_COLORS.core.dark.blend });
    expect(style(screen.getByTestId('workout-card-w1')).backgroundColor).toBe(darkSurface);
    expect(screen.getByText('Core & Abs Focus')).toHaveStyle({ color: dark.textPrimary });
    expect(screen.getByText('Core & Abs Focus')).not.toHaveStyle({ color: light.textPrimary });
    // the line that separates the length from the count is the dark theme's too
    expect(screen.getByText('23 min')).toHaveStyle({ color: dark.textSecondary });
    expect(screen.getByText('Start Workout')).toHaveStyle({ color: dark.textOnPrimary });
  });

  test('the photograph is not tinted: the only layer over it is the fade that keeps the words readable', async () => {
    await renderCard();

    const box = screen.getByTestId('workout-card-w1-photo').parent!;
    // the placeholder, the photo and the fade: no wash of color between them
    const layers = box.children as unknown as { props: { testID?: string; pointerEvents?: string } }[];
    expect(layers).toHaveLength(3);
    expect(layers[1].props.testID).toBe('workout-card-w1-photo');
  });
});

describe('the picture box', () => {
  test('is cropped to cover, sized explicitly, named by nobody, and never takes a tap', async () => {
    await renderCard();

    const photo = screen.getByTestId('workout-card-w1-photo');
    expect(photo).toHaveProp('resizeMode', 'cover');
    // a framed photo has its size from its own shape; the check of each one is above
    expect(photo).toHaveStyle({ height: '100%', minWidth: '100%' });
    expect(photo).toHaveProp('accessible', false);
    expect(photo).toHaveProp('importantForAccessibility', 'no');
    expect(photo).not.toHaveProp('accessibilityLabel');
    expect(photo.parent).toHaveProp('pointerEvents', 'none');
    expect(photo.parent).toHaveStyle({
      position: 'absolute',
      top: 0,
      right: 0,
      bottom: 0,
      width: '62%',
      overflow: 'hidden',
    });
  });

  test('has a quiet placeholder under the picture, for before it loads', async () => {
    await renderCard();

    const placeholder = screen.getByTestId('workout-card-w1-placeholder', HIDDEN);
    expect(placeholder).toHaveStyle({ backgroundColor: CATEGORY_COLORS.core.dark.blend });
    expect(within(placeholder).getByTestId('icon-dumbbell', HIDDEN)).toBeOnTheScreen();
    expect(placeholder).toHaveProp('importantForAccessibility', 'no-hide-descendants');
  });

  test("a photo that fails to load is dropped for the neutral picture, and if that fails too the placeholder stays: never a broken image", async () => {
    Object.assign(WORKOUT_IMAGES, TEST_PHOTOS);
    try {
      await renderCard({ ...WORKOUT, categories: ['cardio'] });
      expect(screen.getByTestId('workout-card-w1-photo')).toHaveProp('source', TEST_PHOTOS['cardio-hiit']);

      await fireEvent(screen.getByTestId('workout-card-w1-photo'), 'error');
      expect(screen.getByTestId('workout-card-w1-photo')).toHaveProp('source', WORKOUT_FALLBACK_IMAGE);
      // the neutral picture is not framed on the subject of the photo that failed
      expect(style(screen.getByTestId('workout-card-w1-photo'))).toEqual({ width: '100%', height: '100%' });

      await fireEvent(screen.getByTestId('workout-card-w1-photo'), 'error');
      expect(screen.queryByTestId('workout-card-w1-photo')).toBeNull();
      expect(screen.getByTestId('workout-card-w1-placeholder', HIDDEN)).toBeOnTheScreen();
      // the words are untouched by all this
      screen.getByText('Core & Abs Focus');
      screen.getByText('Cardio');
    } finally {
      restoreBundled();
    }
  });

  test('the neutral picture failing leaves the placeholder, not a broken image', async () => {
    await renderCard({ ...WORKOUT, categories: undefined });

    await fireEvent(screen.getByTestId('workout-card-w1-photo'), 'error');

    expect(screen.queryByTestId('workout-card-w1-photo')).toBeNull();
    expect(screen.getByTestId('workout-card-w1-placeholder', HIDDEN)).toBeOnTheScreen();
  });

  test('a card failing to load its picture does not affect the next card', async () => {
    await renderWithTheme(
      <>
        <WorkoutCard workout={{ ...WORKOUT, id: 'a', categories: undefined }} />
        <WorkoutCard workout={{ ...WORKOUT, id: 'b', categories: undefined }} />
      </>,
    );

    await fireEvent(screen.getByTestId('workout-card-a-photo'), 'error');

    expect(screen.queryByTestId('workout-card-a-photo')).toBeNull();
    expect(screen.getByTestId('workout-card-b-photo')).toBeOnTheScreen();
  });

  test('a card keeps its own failed state when a list is reordered, because rows are keyed by workout id', async () => {
    // no category: one error is enough to empty a card (the neutral picture has nothing behind it)
    const a = { ...WORKOUT, id: 'a', categories: undefined };
    const b = { ...WORKOUT, id: 'b', categories: undefined };
    const list = (workouts: WorkoutCardData[]) => (
      <>
        {workouts.map((workout) => (
          <WorkoutCard key={workout.id} workout={workout} />
        ))}
      </>
    );
    // rerender replaces the whole tree, so the providers go in with it
    const withProviders = (ui: ReactElement) => (
      <SafeAreaProvider>
        <ThemeProvider>{ui}</ThemeProvider>
      </SafeAreaProvider>
    );
    const errors = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    const view = await render(withProviders(list([a, b])));
    await fireEvent(screen.getByTestId('workout-card-a-photo'), 'error');

    await view.rerender(withProviders(list([b, a])));

    expect(screen.queryByTestId('workout-card-a-photo')).toBeNull();
    expect(screen.getByTestId('workout-card-b-photo')).toBeOnTheScreen();
    expect(errors.mock.calls.filter((call) => String(call[0]).includes('key'))).toEqual([]);
    errors.mockRestore();
  });
});

describe('<EmptyWorkoutCard />', () => {
  const props = {
    title: 'No workout planned today',
    message: 'Ask Formiq to build one for you.',
    actionLabel: 'Ask Formiq',
  };

  test('says there is no workout, and offers the next step as a real button', async () => {
    const onAction = jest.fn();
    await renderWithTheme(<EmptyWorkoutCard {...props} onAction={onAction} />);

    screen.getByText('No workout planned today');
    screen.getByText('Ask Formiq to build one for you.');
    const button = screen.getByRole('button', { name: 'Ask Formiq' });
    expect(screen.getAllByRole('button')).toHaveLength(1);
    await fireEvent.press(button);
    expect(onAction).toHaveBeenCalledTimes(1);
  });

  test('shows nothing that looks like a workout: no kind, no length, no count', async () => {
    await renderWithTheme(<EmptyWorkoutCard {...props} onAction={jest.fn()} />);

    expect(screen.queryByTestId('workout-card-meta')).toBeNull();
    expect(screen.queryByText(/min|exercise/)).toBeNull();
    for (const label of new Set(Object.values(WORKOUT_CATEGORY_LABELS))) expect(screen.queryByText(label)).toBeNull();
  });

  test("has the same shell as a workout card, in the plain dark colors in both themes, over the neutral picture", async () => {
    for (const scheme of ['dark', 'light'] as const) {
      const view = await renderWithTheme(<EmptyWorkoutCard {...props} onAction={jest.fn()} />, scheme);

      const colors = themes.dark.colors;
      expect(screen.getByTestId('workout-card-empty')).toHaveStyle({
        backgroundColor: colors.surface,
        borderColor: colors.border,
        borderRadius: 16,
        overflow: 'hidden',
      });
      expect(screen.getByTestId('workout-card-empty-photo')).toHaveProp('source', WORKOUT_FALLBACK_IMAGE);
      expect(screen.getByText('No workout planned today')).toHaveStyle({ color: colors.textPrimary });
      await view.unmount();
    }
  });

  test('without an action it shows only what it says: no button, and nothing to press', async () => {
    await renderWithTheme(<EmptyWorkoutCard title="Checking today's workout" message="One moment." />);

    screen.getByText("Checking today's workout");
    screen.getByText('One moment.');
    expect(screen.queryByRole('button')).toBeNull();
  });

  test('an action needs both its label and its handler to be shown', async () => {
    await renderWithTheme(<EmptyWorkoutCard {...props} />);
    expect(screen.queryByRole('button')).toBeNull();
    await renderWithTheme(<EmptyWorkoutCard title="t" message="m" onAction={jest.fn()} />);
    expect(screen.queryByRole('button')).toBeNull();
  });

  test('the action can carry a refresh glyph instead of the arrow', async () => {
    await renderWithTheme(<EmptyWorkoutCard {...props} onAction={jest.fn()} actionIcon="refresh" />);

    const button = screen.getByRole('button', { name: 'Ask Formiq' });
    expect(within(button).getByTestId('icon-refresh', { includeHiddenElements: true })).toBeOnTheScreen();
    expect(within(button).queryByTestId('icon-arrow-right', { includeHiddenElements: true })).toBeNull();
  });

  test('is not pressable itself: only its button acts', async () => {
    const onAction = jest.fn();
    await renderWithTheme(<EmptyWorkoutCard {...props} onAction={onAction} />);

    await fireEvent.press(screen.getByText('No workout planned today'));

    expect(onAction).not.toHaveBeenCalled();
  });
});
