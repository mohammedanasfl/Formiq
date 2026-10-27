import { findMockWorkoutDetails, MOCK_TODAY_WORKOUT } from '../src/mock/workoutDetailsMock';
import { MOCK_HOME } from '../src/mock/homeMock';
import { EXERCISE_GIFS } from '../src/workouts/exerciseGifs';
import { EXERCISE_IMAGES, exerciseImage } from '../src/workouts/exerciseImages';
import { framedImageStyle, framedImageStyleInBox } from '../src/workouts/framing';
import {
  coversPhrase,
  exerciseTags,
  formatPrescription,
  groupBySection,
  muscleFocus,
  PLAN_SECTIONS,
} from '../src/workouts/planDetails';

// The fixture is made up (and says so in its file), but it must be shaped as a real plan is, so that the
// screen it feeds is the screen a real plan will feed.
describe('the mock workout', () => {
  const { exercises } = MOCK_TODAY_WORKOUT;

  test("has the reference's structure: two warm-up exercises, three main ones and one cool-down", () => {
    const groups = groupBySection(exercises, MOCK_TODAY_WORKOUT.sectionMinutes);

    expect(groups.map((group) => group.id)).toEqual(PLAN_SECTIONS.map((section) => section.id));
    expect(groups.map((group) => group.exercises.length)).toEqual([2, 3, 1]);
    expect(exercises).toHaveLength(6);
  });

  test("keeps the plan's order: the exercise order runs warm-up, main, cool-down, without repeats", () => {
    const orders = exercises.map((exercise) => exercise.order);

    expect([...orders].sort((a, b) => a - b)).toEqual(orders);
    expect(new Set(orders).size).toBe(orders.length);
    expect(new Set(exercises.map((exercise) => exercise.id)).size).toBe(exercises.length);
    expect(exercises.map((exercise) => exercise.section)).toEqual([
      ...Array(2).fill('WARM_UP'),
      ...Array(3).fill('MAIN_WORKOUT'),
      'COOL_DOWN',
    ]);
  });

  test("the sections' lengths add up to the workout's length, so the screen never contradicts itself", () => {
    const minutes = Object.values(MOCK_TODAY_WORKOUT.sectionMinutes ?? {});

    expect(minutes).toEqual([3, 18, 2]);
    expect(minutes.reduce((sum, value) => sum + value, 0)).toBe(MOCK_TODAY_WORKOUT.durationMinutes);
  });

  test('gives every set one target, reps or seconds and never both, as the backend requires', () => {
    for (const exercise of exercises) {
      expect(Number.isInteger(exercise.sets) && exercise.sets >= 1).toBe(true);
      const targets = [exercise.reps, exercise.durationSeconds].filter((value) => value != null);
      expect(targets).toHaveLength(1);
      expect(Number.isInteger(targets[0]) && (targets[0] as number) >= 1).toBe(true);
    }
  });

  test('reads like the reference: held planks and stretches in seconds, crunches and raises in reps, each side where it applies', () => {
    expect(exercises.map((exercise) => formatPrescription(exercise))).toEqual([
      '2 sets • 30 seconds',
      '2 sets • 10 reps (each side)',
      '3 sets • 30 seconds',
      '3 sets • 20 reps (each side)',
      '3 sets • 15 reps',
      '1 set • 30 seconds (each side)',
    ]);
  });

  test('uses a picture from the supplied set for every exercise, and each picture once', () => {
    const sources = exercises.map((exercise) => exercise.image?.source);

    for (const source of sources) expect(Object.values(EXERCISE_IMAGES)).toContain(source);
    expect(new Set(sources).size).toBe(exercises.length);
    expect(exercises.map((exercise) => exercise.image)).toEqual(
      ['mountain-climbers', 'lunges', 'plank', 'bicycle-crunches', 'leg-raises', 'hamstring-stretch'].map(exerciseImage),
    );
  });

  test('plays a development animation for Plank and Lunges only, matched by key and never by name', () => {
    expect(exercises.map((exercise) => [exercise.name, exercise.animation ?? null])).toEqual([
      ['Mountain Climbers', null],
      ['Lunges', { source: EXERCISE_GIFS.lunge, placeholder: true }],
      ['Plank', { source: EXERCISE_GIFS.plank, placeholder: true }],
      ['Bicycle Crunches', null],
      ['Leg Raises', null],
      ['Hamstring Stretch', null],
    ]);
  });

  test("has steps for the three exercises whose catalog record it copies, and none made up for the other three", () => {
    expect(exercises.map((exercise) => [exercise.name, (exercise.instructions ?? []).length])).toEqual([
      ['Mountain Climbers', 2],
      ['Lunges', 0],
      ['Plank', 2],
      ['Bicycle Crunches', 0],
      ['Leg Raises', 0],
      ['Hamstring Stretch', 3],
    ]);
    expect(exercises[2].instructions?.[0]).toBe(
      'Get into a prone position on the floor, supporting your weight on your toes and your forearms. Your arms are bent and directly below the shoulder.',
    );
  });

  test('gives the exercises a rest, apart from the cool-down, and one of them a note: all made up, as the file says', () => {
    expect(exercises.map((exercise) => exercise.restSeconds ?? null)).toEqual([30, 30, 45, 45, 45, null]);
    expect(exercises.filter((exercise) => exercise.notes)).toHaveLength(1);
    expect(exercises.every((exercise) => exercise.description == null && exercise.weightKg == null)).toBe(true);
  });

  test('carries the catalog-shaped extras the plan response lacks, so the tags and the focus can be drawn', () => {
    for (const exercise of exercises) {
      expect(exercise.equipment).toBeDefined();
      expect((exercise.muscles ?? []).length).toBeGreaterThan(0);
    }
    expect(muscleFocus(exercises)).toEqual({ primary: ['Core'], secondary: ['Shoulders', 'Quadriceps'] });
    expect(coversPhrase(muscleFocus(exercises))).toBe('Covers core');
  });

  test("tags the warm-up and cool-down by their section and movement, and the main exercises by muscle and equipment", () => {
    expect(exercises.map((exercise) => exerciseTags(exercise).map((tag) => tag.text))).toEqual([
      ['Warm-up', 'Cardio'],
      ['Warm-up', 'Mobility'],
      ['Core', 'Bodyweight'],
      ['Core', 'Bodyweight'],
      ['Core', 'Bodyweight'],
      ['Cool-down', 'Flexibility'],
    ]);
  });

  test("is the design phase's workout: Home's card is the backend's now, so nothing of Home is made from it", () => {
    expect(MOCK_TODAY_WORKOUT).toMatchObject({
      id: 'mock-workout-today',
      title: 'Core & Abs Focus',
      durationMinutes: 23,
      categories: ['core'],
    });
    expect(MOCK_TODAY_WORKOUT.exercises).toHaveLength(6);
    expect('todayWorkout' in MOCK_HOME).toBe(false);
  });
});

describe('findMockWorkoutDetails', () => {
  test("finds today's workout by the id of its card", () => {
    expect(findMockWorkoutDetails('mock-workout-today')).toBe(MOCK_TODAY_WORKOUT);
  });

  test.each([
    ['another workout of Home', 'mock-workout-up-1'],
    ['an id nothing has', 'nope'],
    ['a number', 7],
    ['a name from the object prototype', 'constructor'],
  ])('finds nothing for %s: that card has nothing to open yet', (_name, id) => {
    expect(findMockWorkoutDetails(id)).toBeNull();
  });
});

describe('framedImageStyle', () => {
  test('puts the subject at the chosen point of the box: left edge there, picture slid back by its own width times the point', () => {
    expect(framedImageStyle({ width: 300, height: 100, focus: 0.45 }, 0.5)).toEqual({
      position: 'absolute',
      top: 0,
      height: '100%',
      minWidth: '100%',
      aspectRatio: 3,
      left: '50%',
      transform: [{ translateX: '-45%' }],
    });
  });

  test('writes the percentages without the float noise', () => {
    const style = framedImageStyle({ width: 100, height: 40, focus: 0.57 }, 0.66);

    expect(style).toMatchObject({ left: '66%', transform: [{ translateX: '-57%' }] });
  });

  test('a picture with no framing is cropped to fill the box', () => {
    expect(framedImageStyle(null, 0.5)).toEqual({ width: '100%', height: '100%' });
  });
});

describe('framedImageStyleInBox', () => {
  const box = { width: 88, height: 64 };

  test('is as tall as the box and as wide as its shape makes it, with the subject at the chosen point of the box', () => {
    // 320 x 128 is 2.5 : 1, so 160 dp wide at 64 dp tall; the subject at 0.5 of it (80) goes to 0.5 of the box (44)
    expect(framedImageStyleInBox({ width: 320, height: 128, focus: 0.5 }, box, 0.5)).toEqual({
      position: 'absolute',
      top: 0,
      left: -36,
      width: 160,
      height: 64,
    });
  });

  test('never leaves bare box on either side, however near an edge the subject is', () => {
    // a subject at the very left would put the picture's left edge inside the box; at the very right, its right edge
    expect(framedImageStyleInBox({ width: 320, height: 128, focus: 0 }, box, 0.5)).toMatchObject({ left: 0 });
    expect(framedImageStyleInBox({ width: 320, height: 128, focus: 1 }, box, 0.5)).toMatchObject({ left: 88 - 160 });
  });

  test('a picture narrower than the box is stretched to it rather than leaving it bare', () => {
    expect(framedImageStyleInBox({ width: 100, height: 100, focus: 0.5 }, box, 0.5)).toMatchObject({ width: 88, left: 0 });
  });

  test('a picture with no framing fills the box', () => {
    expect(framedImageStyleInBox(null, box, 0.5)).toEqual({ width: 88, height: 64 });
  });
});
