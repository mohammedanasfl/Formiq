import { WORKOUT_CATEGORIES, WORKOUT_CATEGORY_LABELS, type WorkoutCategory } from '../src/workouts/categories';
import {
  resolveWorkoutVisual,
  WORKOUT_FALLBACK_IMAGE,
  WORKOUT_IMAGE_FILES,
  WORKOUT_IMAGE_FRAMING,
  WORKOUT_IMAGES,
  workoutImageKey,
  type WorkoutImageKey,
} from '../src/workouts/workoutImages';

const KEYS = Object.keys(WORKOUT_IMAGE_FILES) as WorkoutImageKey[];
// the test reads the folder with Node's own fs; the project does not load Node's types, so it is typed here
const { existsSync, readdirSync, readFileSync } = jest.requireActual('fs') as {
  existsSync: (path: string) => boolean;
  readdirSync: (path: string) => string[];
  readFileSync: (path: string) => { readUInt32BE: (offset: number) => number; subarray: (a: number, b: number) => { toString: (encoding: string) => string } };
};
const PHOTO_DIR = `${process.cwd()}/assets/images/workouts`;

// The photos as the app registers them. A test swaps in stand-ins or clears the table and puts these back.
const BUNDLED = { ...WORKOUT_IMAGES };
const clearPhotos = () => {
  for (const key of KEYS) delete WORKOUT_IMAGES[key];
};
const restoreBundled = () => {
  clearPhotos();
  Object.assign(WORKOUT_IMAGES, BUNDLED);
};

// Stand-ins for the photos, so the lookup is checked on its own, apart from the files.
const TEST_PHOTOS: Record<WorkoutImageKey, { uri: string }> = Object.fromEntries(
  KEYS.map((key) => [key, { uri: `test://${WORKOUT_IMAGE_FILES[key]}` }]),
) as Record<WorkoutImageKey, { uri: string }>;

describe('the photo each category calls for', () => {
  test.each<[WorkoutCategory, WorkoutImageKey]>([
    ['core', 'core-abs'],
    ['upper-body', 'upper-body'],
    ['lower-body', 'lower-body'],
    ['full-body', 'full-body'],
    ['cardio', 'cardio-hiit'],
    ['mobility', 'mobility'],
    ['recovery', 'recovery-stretch'],
    ['beginner', 'beginner'],
  ])('%s -> %s', (category, key) => {
    expect(workoutImageKey(category)).toBe(key);
  });

  test('every category has one, and no two categories share a photo', () => {
    const keys = WORKOUT_CATEGORIES.map((category) => workoutImageKey(category));
    expect(new Set(keys).size).toBe(WORKOUT_CATEGORIES.length);
    for (const key of keys) expect(KEYS).toContain(key);
  });

  test('the files are the eight the design names, in assets/images/workouts', () => {
    expect(WORKOUT_IMAGE_FILES).toEqual({
      'core-abs': 'core-abs.png',
      'upper-body': 'upper-body.png',
      'lower-body': 'lower-body.png',
      'full-body': 'full-body.png',
      'cardio-hiit': 'cardio-hiit.png',
      mobility: 'mobility.png',
      'recovery-stretch': 'recovery-stretch.png',
      beginner: 'beginner.png',
    });
  });
});

describe('resolveWorkoutVisual', () => {
  afterEach(restoreBundled);

  test.each(WORKOUT_CATEGORIES.map((category) => [category]))(
    'a %s workout gets its category, its label, its own photo and its framing',
    (category) => {
      Object.assign(WORKOUT_IMAGES, TEST_PHOTOS);

      const visual = resolveWorkoutVisual({ categories: [category] });

      expect(visual).toEqual({
        category,
        label: WORKOUT_CATEGORY_LABELS[category],
        imageKey: workoutImageKey(category),
        source: TEST_PHOTOS[workoutImageKey(category)],
        framing: WORKOUT_IMAGE_FRAMING[workoutImageKey(category)],
        isFallback: false,
      });
    },
  );

  test('different categories get different photos', () => {
    Object.assign(WORKOUT_IMAGES, TEST_PHOTOS);

    const sources = WORKOUT_CATEGORIES.map((category) => resolveWorkoutVisual({ categories: [category] }).source);

    expect(new Set(sources).size).toBe(WORKOUT_CATEGORIES.length);
  });

  test.each([
    ['no categories at all', {}],
    ['null categories', { categories: null }],
    ['an empty list', { categories: [] }],
    ['only categories the app does not know', { categories: ['yoga'] as unknown as WorkoutCategory[] }],
  ])('%s: the neutral picture, and no label, no photo key, no framing (nothing is made up)', (_name, workout) => {
    Object.assign(WORKOUT_IMAGES, TEST_PHOTOS);

    expect(resolveWorkoutVisual(workout)).toEqual({
      category: null,
      label: null,
      imageKey: null,
      source: WORKOUT_FALLBACK_IMAGE,
      framing: null,
      isFallback: true,
    });
  });

  test('a known category whose photo is not bundled keeps its label and shows the neutral picture', () => {
    delete WORKOUT_IMAGES['cardio-hiit'];

    const visual = resolveWorkoutVisual({ categories: ['cardio'] });

    expect(visual).toEqual({
      category: 'cardio',
      label: 'Cardio',
      imageKey: 'cardio-hiit',
      source: WORKOUT_FALLBACK_IMAGE,
      framing: null,
      isFallback: true,
    });
  });

  test('photos can be added one at a time: a registered one is used, the others fall back', () => {
    clearPhotos();
    WORKOUT_IMAGES['core-abs'] = TEST_PHOTOS['core-abs'];

    expect(resolveWorkoutVisual({ categories: ['core'] }).source).toBe(TEST_PHOTOS['core-abs']);
    expect(resolveWorkoutVisual({ categories: ['mobility'] }).source).toBe(WORKOUT_FALLBACK_IMAGE);
  });

  test('a beginner workout of unknown kind gets the beginner photo, a known one keeps its own', () => {
    Object.assign(WORKOUT_IMAGES, TEST_PHOTOS);

    expect(resolveWorkoutVisual({ categories: ['beginner'] }).source).toBe(TEST_PHOTOS.beginner);
    expect(resolveWorkoutVisual({ categories: ['beginner', 'lower-body'] }).source).toBe(TEST_PHOTOS['lower-body']);
    expect(resolveWorkoutVisual({ categories: ['lower-body', 'beginner'] }).label).toBe('Strength');
  });

  test('a mixed workout gets the photo of its one deterministic category', () => {
    Object.assign(WORKOUT_IMAGES, TEST_PHOTOS);

    expect(resolveWorkoutVisual({ categories: ['upper-body', 'lower-body'] }).source).toBe(TEST_PHOTOS['full-body']);
    expect(resolveWorkoutVisual({ categories: ['cardio', 'core'] }).source).toBe(TEST_PHOTOS['core-abs']);
    expect(resolveWorkoutVisual({ categories: ['core', 'cardio'] }).source).toBe(TEST_PHOTOS['core-abs']);
  });
});

describe('the bundled pictures', () => {
  afterEach(restoreBundled);

  test('the neutral picture is a bundled file, the same dark gym as the rest of the app', () => {
    expect(WORKOUT_FALLBACK_IMAGE).toBe(require('../assets/images/signup-background.png'));
  });

  test('all eight photos are registered, so every category shows its own, not the neutral picture', () => {
    for (const key of KEYS) expect(BUNDLED[key]).toBeDefined();
    for (const category of WORKOUT_CATEGORIES) {
      const visual = resolveWorkoutVisual({ categories: [category] });

      expect(visual.isFallback).toBe(false);
      expect(visual.source).toBe(BUNDLED[workoutImageKey(category)]);
      expect(visual.source).not.toBe(WORKOUT_FALLBACK_IMAGE);
    }
  });

  test('every photo that is in assets/images/workouts is registered, so adding a file cannot be forgotten', () => {
    const present = existsSync(PHOTO_DIR) ? readdirSync(PHOTO_DIR) : [];
    const unregistered = KEYS.filter(
      (key) => present.includes(WORKOUT_IMAGE_FILES[key]) && WORKOUT_IMAGES[key] === undefined,
    );

    expect(unregistered).toEqual([]);
  });

  test('every registered photo has a file to bundle, and the folder holds those eight and nothing else', () => {
    const present = existsSync(PHOTO_DIR) ? readdirSync(PHOTO_DIR) : [];
    const missing = KEYS.filter(
      (key) => WORKOUT_IMAGES[key] !== undefined && !present.includes(WORKOUT_IMAGE_FILES[key]),
    );

    expect(missing).toEqual([]);
    expect([...present].sort()).toEqual(Object.values(WORKOUT_IMAGE_FILES).sort());
  });
});

describe('the photo files', () => {
  const PNG_SIGNATURE = '\u0089PNG\r\n\u001a\n';

  test.each(KEYS.map((key) => [key]))('%s is a real PNG of the size the framing says it is', (key) => {
    const file = readFileSync(`${PHOTO_DIR}/${WORKOUT_IMAGE_FILES[key]}`);

    expect(file.subarray(0, 8).toString('latin1')).toBe(PNG_SIGNATURE);
    expect(file.subarray(12, 16).toString('latin1')).toBe('IHDR');
    expect({ width: file.readUInt32BE(16), height: file.readUInt32BE(20) }).toEqual({
      width: WORKOUT_IMAGE_FRAMING[key].width,
      height: WORKOUT_IMAGE_FRAMING[key].height,
    });
  });

  test('every photo is a wide strip, the shape the card frames', () => {
    for (const key of KEYS) {
      const { width, height } = WORKOUT_IMAGE_FRAMING[key];
      expect(width / height).toBeGreaterThan(2.5);
    }
  });

  test("each photo's subject point lies inside it, with room for the card to show it either side", () => {
    for (const key of KEYS) {
      expect(WORKOUT_IMAGE_FRAMING[key].focus).toBeGreaterThan(0.4);
      expect(WORKOUT_IMAGE_FRAMING[key].focus).toBeLessThan(0.8);
    }
  });
});
