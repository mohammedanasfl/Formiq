import { fireEvent, screen, within } from '@testing-library/react-native';

import { EXERCISE_IMAGE_FRAMING, EXERCISE_IMAGES, exerciseImage } from '../src/workouts/exerciseImages';
import { ExerciseRow } from '../src/workouts/ExerciseRow';
import type { PlannedExercise } from '../src/workouts/planDetails';
import { SECTION_COLORS } from '../src/workouts/sectionColors';
import { themes, type ThemeScheme } from '../src/theme';
import { renderWithTheme } from '../test-utils/renderWithTheme';

const dark = themes.dark.colors;
const light = themes.light.colors;
const HIDDEN = { includeHiddenElements: true };

const plank: PlannedExercise = {
  id: 'p1',
  order: 3,
  section: 'MAIN_WORKOUT',
  name: 'Plank',
  sets: 3,
  durationSeconds: 30,
  equipment: [],
  muscles: [{ name: 'Core', role: 'PRIMARY' }],
  image: exerciseImage('plank'),
};
const climbers: PlannedExercise = {
  id: 'c1',
  order: 1,
  section: 'WARM_UP',
  name: 'Mountain Climbers',
  sets: 2,
  durationSeconds: 30,
  movementPattern: 'CARDIO',
  image: exerciseImage('mountain-climbers'),
};

async function renderRow(exercise: PlannedExercise, options: { scheme?: ThemeScheme; number?: number } = {}) {
  const onPress = jest.fn();
  const scheme = options.scheme ?? 'dark';
  const view = await renderWithTheme(
    <ExerciseRow exercise={exercise} number={options.number ?? 3} section={SECTION_COLORS[exercise.section][scheme]} onPress={onPress} />,
    scheme,
  );
  return { ...view, onPress };
}

describe('<ExerciseRow />', () => {
  test('shows the picture, its number, the name, what it asks for, its two tags and a chevron', async () => {
    await renderRow(plank);

    const row = screen.getByTestId('exercise-p1');
    expect(within(row).getByText('Plank')).toBeOnTheScreen();
    expect(within(row).getByText('3 sets • 30 seconds')).toBeOnTheScreen();
    expect(within(row).getByText('Core')).toBeOnTheScreen();
    expect(within(row).getByText('Bodyweight')).toBeOnTheScreen();
    expect(within(row).getByTestId('icon-chevron-right', HIDDEN)).toBeOnTheScreen();
    expect(within(row).getByTestId('exercise-p1-thumbnail')).toHaveProp('source', EXERCISE_IMAGES.plank);
    expect(within(row).getByTestId('exercise-p1-thumbnail-badge', HIDDEN)).toHaveTextContent('3');
  });

  test('is one button, named by what it says (the bullet read as a pause), that opens the exercise', async () => {
    const { onPress } = await renderRow(plank);

    const row = screen.getByRole('button', { name: 'Plank. 3 sets, 30 seconds. Core, Bodyweight' });
    expect(row).toHaveProp('accessibilityHint', 'Opens the exercise details');
    await fireEvent.press(row);

    expect(onPress).toHaveBeenCalledTimes(1);
  });

  test("the number is on the picture's corner, in the section's outline and fill, and is the exercise's place in the workout", async () => {
    await renderRow(plank, { number: 5 });

    const badge = screen.getByTestId('exercise-p1-thumbnail-badge', HIDDEN);
    expect(badge).toHaveTextContent('5');
    expect(badge).toHaveStyle({
      position: 'absolute',
      top: 3,
      left: 3,
      borderColor: SECTION_COLORS.MAIN_WORKOUT.dark.accent,
      backgroundColor: SECTION_COLORS.MAIN_WORKOUT.dark.badge,
    });
    // hidden from screen readers: the order is the order of the list
    expect(badge).toHaveProp('accessibilityElementsHidden', true);
  });

  test('the badge stays when there is no picture: it numbers the exercise, not the picture', async () => {
    await renderRow({ ...plank, image: null });

    expect(screen.getByTestId('exercise-p1-thumbnail-badge', HIDDEN)).toBeOnTheScreen();
  });

  test('the picture is a picture, not content: it has no name and is hidden from screen readers', async () => {
    await renderRow(plank);

    const picture = screen.getByTestId('exercise-p1-thumbnail');
    expect(picture).toHaveProp('accessible', false);
    expect(picture).toHaveProp('importantForAccessibility', 'no');
    expect(picture).not.toHaveProp('accessibilityLabel');
  });

  test('frames the picture on its athlete, in a clipped box of a fixed size, so every row lines up', async () => {
    await renderRow(plank);

    const picture = screen.getByTestId('exercise-p1-thumbnail');
    const { width, height, focus } = EXERCISE_IMAGE_FRAMING.plank;
    // every number in dp: as tall as the box, as wide as the picture's shape makes it, its athlete's point in the
    // box's middle, held back so the picture never leaves bare box (this one is nearly as wide as the box, so it
    // stays at the left edge)
    const drawn = 58 * (width / height);
    expect(picture).toHaveStyle({
      position: 'absolute',
      top: 0,
      height: 58,
      width: Number(drawn.toFixed(2)),
      left: Number(Math.min(0, Math.max(132 - drawn, 132 * 0.5 - focus * drawn)).toFixed(2)),
    });
    // the box clips the picture and has the same size whatever picture it holds
    expect(picture.parent).toHaveStyle({ width: 132, height: 58, overflow: 'hidden', borderRadius: 8 });
  });

  test("never leaves bare box beside the picture, whatever its athlete's point is", async () => {
    for (const focus of [0, 0.2, 0.8, 1]) {
      const { unmount } = await renderRow({ ...plank, image: { source: { uri: 'x' }, framing: { width: 300, height: 100, focus } } });
      const style = screen.getByTestId('exercise-p1-thumbnail').props.style;
      const { left, width } = Array.isArray(style) ? Object.assign({}, ...style.flat()) : style;

      expect(left).toBeLessThanOrEqual(0);
      expect(left + width).toBeGreaterThanOrEqual(132);
      await unmount();
    }
  });

  test('a picture that is not one of the fifteen is simply cropped to fill its box', async () => {
    await renderRow({ ...plank, image: { source: { uri: 'https://example.invalid/x.png' }, framing: null } });

    expect(screen.getByTestId('exercise-p1-thumbnail')).toHaveStyle({ width: 132, height: 58 });
  });

  test('without a picture it shows its placeholder, and no image at all', async () => {
    await renderRow({ ...plank, image: null });

    expect(screen.queryByTestId('exercise-p1-thumbnail')).toBeNull();
    expect(screen.getByTestId('exercise-p1-thumbnail-placeholder', HIDDEN)).toBeOnTheScreen();
  });

  test('without an image field it shows its placeholder too', async () => {
    const { image: _image, ...bare } = plank;
    await renderRow(bare);

    expect(screen.queryByTestId('exercise-p1-thumbnail')).toBeNull();
    expect(screen.getByTestId('exercise-p1-thumbnail-placeholder', HIDDEN)).toBeOnTheScreen();
  });

  test('a picture that fails to load is dropped, and the placeholder stays: never a broken-image box', async () => {
    await renderRow(plank);

    await fireEvent(screen.getByTestId('exercise-p1-thumbnail'), 'error');

    expect(screen.queryByTestId('exercise-p1-thumbnail')).toBeNull();
    expect(screen.getByTestId('exercise-p1-thumbnail-placeholder', HIDDEN)).toBeOnTheScreen();
    expect(screen.getByTestId('exercise-p1-thumbnail-badge', HIDDEN)).toBeOnTheScreen();
  });

  test('the placeholder is always under the picture, so nothing shows through before it loads', async () => {
    await renderRow(plank);

    const placeholder = screen.getByTestId('exercise-p1-thumbnail-placeholder', HIDDEN);
    expect(placeholder).toHaveStyle({ position: 'absolute' });
    expect(placeholder).toHaveProp('accessibilityElementsHidden', true);
    expect(placeholder.parent).toHaveStyle({ backgroundColor: dark.surfaceMuted });
  });

  test.each([
    ['sets and reps', { sets: 3, reps: 15, durationSeconds: null }, '3 sets • 15 reps'],
    ['sets and a duration', { sets: 2, reps: null, durationSeconds: 90 }, '2 sets • 1 min 30 sec'],
    ['one set of reps', { sets: 1, reps: 15, durationSeconds: null }, '1 set • 15 reps'],
    ['each side', { sets: 3, reps: 20, durationSeconds: null, eachSide: true }, '3 sets • 20 reps (each side)'],
  ])('shows %s the way the design reads them', async (_name, target, text) => {
    await renderRow({ ...plank, ...target });

    screen.getByText(text);
  });

  test('leaves out every line the exercise does not carry: only the name is certain', async () => {
    await renderRow({ id: 'bare', order: 1, section: 'MAIN_WORKOUT', name: 'Mystery', sets: 0 });

    const row = screen.getByTestId('exercise-bare');
    expect(within(row).getByText('Mystery')).toBeOnTheScreen();
    expect(screen.queryByTestId('exercise-tags')).toBeNull();
    expect(screen.queryByText(/sets|reps|seconds|minute/)).toBeNull();
    screen.getByRole('button', { name: 'Mystery' });
    expect(within(row).getByTestId('exercise-bare-thumbnail-placeholder', HIDDEN)).toBeOnTheScreen();
  });

  test("a warm-up exercise's first tag wears the section's colors, and the second is plain", async () => {
    await renderRow(climbers, { number: 1 });

    const palette = SECTION_COLORS.WARM_UP.dark;
    const tags = within(screen.getByTestId('exercise-tags'));
    expect(tags.getByText('Warm-up')).toHaveStyle({ color: palette.tagText });
    expect(tags.getByText('Warm-up').parent).toHaveStyle({ backgroundColor: palette.tagBackground });
    expect(tags.getByText('Cardio')).toHaveStyle({ color: dark.textSecondary });
    expect(tags.getByText('Cardio').parent).toHaveStyle({ backgroundColor: dark.surfaceMuted });
  });

  test('a long name wraps to two lines at most and does not push the chevron off the row', async () => {
    const name = 'Single-Leg Romanian Deadlift With A Slow Lowering Phase And A Pause At The Bottom';
    await renderRow({ ...plank, name });

    expect(screen.getByText(name)).toHaveProp('numberOfLines', 2);
    expect(screen.getByText(name).parent).toHaveStyle({ flex: 1 });
  });

  test("text follows the font size setting only up to the app's limit", async () => {
    await renderRow(plank);

    expect(screen.getByText('Plank')).toHaveProp('maxFontSizeMultiplier', 1.5);
  });

  test("in the dark theme: white name, secondary prescription, the main section's tag", async () => {
    await renderRow(plank);

    expect(screen.getByText('Plank')).toHaveStyle({ color: dark.textPrimary });
    expect(screen.getByText('3 sets • 30 seconds')).toHaveStyle({ color: dark.textSecondary });
    expect(screen.getByText('Core')).toHaveStyle({ color: SECTION_COLORS.MAIN_WORKOUT.dark.tagText });
  });

  test('in the light theme: dark words, and the section tags in their light colors', async () => {
    await renderRow(plank, { scheme: 'light' });

    expect(screen.getByText('Plank')).toHaveStyle({ color: light.textPrimary });
    expect(screen.getByText('3 sets • 30 seconds')).toHaveStyle({ color: light.textSecondary });
    expect(screen.getByText('Core')).toHaveStyle({ color: SECTION_COLORS.MAIN_WORKOUT.light.tagText });
    expect(screen.getByText('Core').parent).toHaveStyle({ backgroundColor: SECTION_COLORS.MAIN_WORKOUT.light.tagBackground });
    expect(screen.getByText('Bodyweight').parent).toHaveStyle({ backgroundColor: light.surfaceMuted });
  });
});
