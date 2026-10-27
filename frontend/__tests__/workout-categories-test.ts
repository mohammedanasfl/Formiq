import {
  isWorkoutCategory,
  primaryCategory,
  WORKOUT_CATEGORIES,
  WORKOUT_CATEGORY_LABELS,
  type WorkoutCategory,
} from '../src/workouts/categories';

function permutations<T>(items: readonly T[]): T[][] {
  if (items.length <= 1) return [[...items]];
  return items.flatMap((item, index) =>
    permutations([...items.slice(0, index), ...items.slice(index + 1)]).map((rest) => [item, ...rest]),
  );
}

describe('the categories', () => {
  test('are the eight kinds of workout the app has a picture for', () => {
    expect([...WORKOUT_CATEGORIES]).toEqual([
      'core',
      'upper-body',
      'lower-body',
      'full-body',
      'cardio',
      'mobility',
      'recovery',
      'beginner',
    ]);
  });

  test('each has a label, and core, upper and lower body are all "Strength", as the design groups them', () => {
    for (const category of WORKOUT_CATEGORIES) expect(WORKOUT_CATEGORY_LABELS[category].length).toBeGreaterThan(0);
    expect(WORKOUT_CATEGORY_LABELS).toEqual({
      core: 'Strength',
      'upper-body': 'Strength',
      'lower-body': 'Strength',
      'full-body': 'Full body',
      cardio: 'Cardio',
      mobility: 'Mobility',
      recovery: 'Recovery',
      beginner: 'Beginner',
    });
  });

  test('isWorkoutCategory accepts only those eight', () => {
    for (const category of WORKOUT_CATEGORIES) expect(isWorkoutCategory(category)).toBe(true);
    for (const other of ['yoga', 'Core', '', null, undefined, 3, {}]) expect(isWorkoutCategory(other)).toBe(false);
  });
});

describe('primaryCategory', () => {
  test.each(WORKOUT_CATEGORIES.map((category) => [category]))('a workout of one kind, %s, is shown as it', (category) => {
    expect(primaryCategory([category])).toBe(category);
  });

  test('a workout with no categories, an empty list or nothing known has no category: nothing is guessed', () => {
    expect(primaryCategory(undefined)).toBeNull();
    expect(primaryCategory(null)).toBeNull();
    expect(primaryCategory([])).toBeNull();
    expect(primaryCategory(['yoga', 'powerlifting'] as unknown as WorkoutCategory[])).toBeNull();
  });

  test('values the app does not know are ignored, and the known ones still count', () => {
    expect(primaryCategory(['yoga', 'cardio'] as unknown as WorkoutCategory[])).toBe('cardio');
  });

  test('a repeated category is the same as one', () => {
    expect(primaryCategory(['core', 'core', 'core'])).toBe('core');
  });

  test('upper and lower body together make a full-body workout', () => {
    expect(primaryCategory(['upper-body', 'lower-body'])).toBe('full-body');
    expect(primaryCategory(['lower-body', 'core', 'upper-body'])).toBe('full-body');
  });

  test('a mixed workout gets the same category whatever order its categories arrive in', () => {
    const mixes: WorkoutCategory[][] = [
      ['core', 'cardio'],
      ['mobility', 'recovery'],
      ['cardio', 'mobility', 'core'],
      ['recovery', 'beginner', 'lower-body'],
      ['upper-body', 'lower-body', 'cardio'],
    ];
    for (const mix of mixes) {
      const answers = new Set(permutations(mix).map((order) => primaryCategory(order)));
      expect(answers.size).toBe(1);
    }
  });

  test('the fixed order of preference for the rest: broad training first, then core, cardio, mobility, recovery', () => {
    expect(primaryCategory(['core', 'cardio'])).toBe('core');
    expect(primaryCategory(['cardio', 'mobility'])).toBe('cardio');
    expect(primaryCategory(['mobility', 'recovery'])).toBe('mobility');
    expect(primaryCategory(['cardio', 'full-body'])).toBe('full-body');
    expect(primaryCategory(['core', 'lower-body'])).toBe('lower-body');
  });

  test('"beginner" names a workout only when nothing else does: a known workout is never relabelled for a beginner', () => {
    expect(primaryCategory(['beginner'])).toBe('beginner');
    for (const known of WORKOUT_CATEGORIES.filter((category) => category !== 'beginner')) {
      expect(primaryCategory(['beginner', known])).toBe(known);
      expect(primaryCategory([known, 'beginner'])).toBe(known);
    }
    expect(primaryCategory(['beginner', 'yoga'] as unknown as WorkoutCategory[])).toBe('beginner');
  });
});
