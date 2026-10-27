import {
  coversPhrase,
  exerciseCountLabel,
  exerciseTags,
  formatDuration,
  formatMinutes,
  formatPrescription,
  groupBySection,
  muscleFocus,
  PLAN_SECTIONS,
  sectionSummary,
  workoutCardFromDetails,
  type PlannedExercise,
  type WorkoutDetailsData,
} from '../src/workouts/planDetails';

const exercise = (id: number, over: Partial<PlannedExercise> = {}): PlannedExercise => ({
  id,
  order: id,
  section: 'MAIN_WORKOUT',
  name: `Exercise ${id}`,
  sets: 3,
  reps: 10,
  ...over,
});
const muscles = (...pairs: [string, 'PRIMARY' | 'SECONDARY'][]) => pairs.map(([name, role]) => ({ name, role }));

describe('the sections', () => {
  test('are three, in the order a workout is done, with the names the screen shows', () => {
    expect(PLAN_SECTIONS).toEqual([
      { id: 'WARM_UP', title: 'Warm-up' },
      { id: 'MAIN_WORKOUT', title: 'Main Workout' },
      { id: 'COOL_DOWN', title: 'Cool-down' },
    ]);
  });
});

describe('groupBySection', () => {
  test('puts warm-up first, then the main workout, then the cool-down, whatever order they arrive in', () => {
    const arrived = [
      exercise(1, { section: 'COOL_DOWN' }),
      exercise(2, { section: 'MAIN_WORKOUT' }),
      exercise(3, { section: 'WARM_UP' }),
      exercise(4, { section: 'COOL_DOWN' }),
      exercise(5, { section: 'WARM_UP' }),
    ];

    const groups = groupBySection(arrived);

    expect(groups.map((group) => group.id)).toEqual(['WARM_UP', 'MAIN_WORKOUT', 'COOL_DOWN']);
    expect(groups.map((group) => group.title)).toEqual(['Warm-up', 'Main Workout', 'Cool-down']);
    expect(groups.map((group) => group.exercises.map((e) => e.id))).toEqual([[3, 5], [2], [1, 4]]);
  });

  test("keeps each section in its exercises' own order, and equal places in the order they arrived", () => {
    const groups = groupBySection([
      exercise(1, { order: 3 }),
      exercise(2, { order: 1 }),
      exercise(3, { order: 2 }),
      exercise(4, { order: 2 }),
    ]);

    expect(groups[0].exercises.map((e) => e.id)).toEqual([2, 3, 4, 1]);
  });

  test('leaves out a section with no exercises, so there is no empty heading', () => {
    const groups = groupBySection([exercise(1, { section: 'WARM_UP' }), exercise(2, { section: 'COOL_DOWN' })]);

    expect(groups.map((group) => group.id)).toEqual(['WARM_UP', 'COOL_DOWN']);
    expect(groupBySection([])).toEqual([]);
  });

  test('loses no exercise, and does not change the list it is given', () => {
    const arrived = [exercise(2, { order: 2 }), exercise(1, { order: 1 }), exercise(3, { section: 'WARM_UP' })];
    const before = arrived.map((e) => e.id);

    const groups = groupBySection(arrived);

    expect(groups.flatMap((group) => group.exercises).map((e) => e.id).sort()).toEqual([1, 2, 3]);
    expect(arrived.map((e) => e.id)).toEqual(before);
  });

  test("carries each section's length when the workout gives one, and null otherwise", () => {
    const groups = groupBySection(
      [exercise(1, { section: 'WARM_UP' }), exercise(2), exercise(3, { section: 'COOL_DOWN' })],
      { WARM_UP: 3, MAIN_WORKOUT: 18 },
    );

    expect(groups.map((group) => group.minutes)).toEqual([3, 18, null]);
  });

  test.each([[0], [-2], [2.5], [Number.NaN]])('a section length of %s is not a length', (minutes) => {
    expect(groupBySection([exercise(1)], { MAIN_WORKOUT: minutes })[0].minutes).toBeNull();
    expect(groupBySection([exercise(1)], null)[0].minutes).toBeNull();
    expect(groupBySection([exercise(1)])[0].minutes).toBeNull();
  });
});

describe('the words for counts and lengths', () => {
  test('exerciseCountLabel says "1 exercise" and "6 exercises"', () => {
    expect(exerciseCountLabel(1)).toBe('1 exercise');
    expect(exerciseCountLabel(0)).toBe('0 exercises');
    expect(exerciseCountLabel(6)).toBe('6 exercises');
  });

  test.each([
    [23, '23 minutes'],
    [1, '1 minute'],
    [22.6, '23 minutes'],
  ])('formatMinutes(%s) is "%s"', (minutes, text) => {
    expect(formatMinutes(minutes)).toBe(text);
  });

  test.each([[0], [0.4], [-5], [Number.NaN], [Number.POSITIVE_INFINITY], [null], [undefined]])(
    'formatMinutes(%s) is nothing: a length that is not a positive number is left out',
    (minutes) => {
      expect(formatMinutes(minutes)).toBeNull();
    },
  );

  test('sectionSummary is the count, then the length when there is one', () => {
    const one = exercise(1);

    expect(sectionSummary({ exercises: [one, one], minutes: 3 })).toBe('2 exercises • 3 min');
    expect(sectionSummary({ exercises: [one], minutes: 2 })).toBe('1 exercise • 2 min');
    expect(sectionSummary({ exercises: [one, one, one], minutes: null })).toBe('3 exercises');
  });
});

describe('formatDuration', () => {
  test.each([
    [1, '1 second'],
    [5, '5 seconds'],
    [30, '30 seconds'],
    [59, '59 seconds'],
    [60, '1 minute'],
    [90, '1 min 30 sec'],
    [120, '2 minutes'],
    [605, '10 min 5 sec'],
    [44.6, '45 seconds'],
  ])('%s seconds is "%s"', (seconds, text) => {
    expect(formatDuration(seconds)).toBe(text);
  });
});

describe('formatPrescription', () => {
  test.each([
    [{ sets: 3, reps: 15 }, '3 sets • 15 reps'],
    [{ sets: 3, durationSeconds: 30 }, '3 sets • 30 seconds'],
    [{ sets: 2, durationSeconds: 90 }, '2 sets • 1 min 30 sec'],
    [{ sets: 1, reps: 12 }, '1 set • 12 reps'],
    [{ sets: 1, durationSeconds: 30 }, '1 set • 30 seconds'],
    [{ sets: 1, reps: 1 }, '1 set • 1 rep'],
    [{ sets: 3, reps: null, durationSeconds: null }, '3 sets'],
    [{ sets: 1 }, '1 set'],
  ])('%j reads "%s"', (target, text) => {
    expect(formatPrescription(target)).toBe(text);
  });

  test('says "(each side)" after the target when the exercise is done on each side', () => {
    expect(formatPrescription({ sets: 2, durationSeconds: 30, eachSide: true })).toBe('2 sets • 30 seconds (each side)');
    expect(formatPrescription({ sets: 3, reps: 20, eachSide: true })).toBe('3 sets • 20 reps (each side)');
    expect(formatPrescription({ sets: 3, reps: 20, eachSide: false })).toBe('3 sets • 20 reps');
    expect(formatPrescription({ sets: 3, reps: 20, eachSide: null })).toBe('3 sets • 20 reps');
  });

  test('has no "(each side)" without a target for it to qualify', () => {
    expect(formatPrescription({ sets: 3, eachSide: true })).toBe('3 sets');
  });

  test('says nothing when the plan gives neither sets nor a target, and does not make a number up', () => {
    expect(formatPrescription({ sets: 0 })).toBeNull();
    expect(formatPrescription({ sets: 2.5, reps: -1, durationSeconds: 0 })).toBeNull();
    expect(formatPrescription({ sets: Number.NaN, reps: null })).toBeNull();
  });

  test('a target without a set count is still shown', () => {
    expect(formatPrescription({ sets: 0, reps: 8 })).toBe('8 reps');
    expect(formatPrescription({ sets: 0, reps: 8, eachSide: true })).toBe('8 reps (each side)');
  });

  test('reps win over a duration when a malformed plan gives both (the backend never does)', () => {
    expect(formatPrescription({ sets: 3, reps: 10, durationSeconds: 30 })).toBe('3 sets • 10 reps');
  });
});

describe('exerciseTags', () => {
  describe('in the main workout', () => {
    test("the first is the main muscle, in the section's colors, and the second is the equipment, plain", () => {
      expect(
        exerciseTags({ section: 'MAIN_WORKOUT', muscles: muscles(['Core', 'PRIMARY'], ['Shoulders', 'SECONDARY']), equipment: ['Medicine Ball'] }),
      ).toEqual([
        { text: 'Core', tone: 'section' },
        { text: 'Medicine Ball', tone: 'plain' },
      ]);
    });

    test('an empty equipment list says "Bodyweight": it needs none', () => {
      expect(exerciseTags({ section: 'MAIN_WORKOUT', muscles: muscles(['Core', 'PRIMARY']), equipment: [] })).toEqual([
        { text: 'Core', tone: 'section' },
        { text: 'Bodyweight', tone: 'plain' },
      ]);
    });

    test('equipment that is not known (absent) gives no tag, and a missing primary muscle gives no first tag', () => {
      expect(exerciseTags({ section: 'MAIN_WORKOUT', muscles: muscles(['Core', 'PRIMARY']) })).toEqual([{ text: 'Core', tone: 'section' }]);
      expect(exerciseTags({ section: 'MAIN_WORKOUT', equipment: ['Dumbbell'], muscles: muscles(['Calves', 'SECONDARY']) })).toEqual([
        { text: 'Dumbbell', tone: 'plain' },
      ]);
      expect(exerciseTags({ section: 'MAIN_WORKOUT' })).toEqual([]);
      expect(exerciseTags({ section: 'MAIN_WORKOUT', equipment: null, muscles: null })).toEqual([]);
    });

    test('shows the first of several pieces of equipment, and the first primary muscle', () => {
      expect(
        exerciseTags({ section: 'MAIN_WORKOUT', muscles: muscles(['Lats', 'PRIMARY'], ['Biceps', 'PRIMARY']), equipment: ['Dumbbell', 'Bench'] }),
      ).toEqual([
        { text: 'Lats', tone: 'section' },
        { text: 'Dumbbell', tone: 'plain' },
      ]);
    });

    test('blank names are not tags', () => {
      expect(exerciseTags({ section: 'MAIN_WORKOUT', equipment: ['', '  '], muscles: muscles([' ', 'PRIMARY']) })).toEqual([]);
    });
  });

  describe('in the warm-up and the cool-down', () => {
    test("the first is the section's own name, and the second is the kind of movement", () => {
      expect(exerciseTags({ section: 'WARM_UP', movementPattern: 'MOBILITY' })).toEqual([
        { text: 'Warm-up', tone: 'section' },
        { text: 'Mobility', tone: 'plain' },
      ]);
      expect(exerciseTags({ section: 'WARM_UP', movementPattern: 'CARDIO' })[1]).toEqual({ text: 'Cardio', tone: 'plain' });
      expect(exerciseTags({ section: 'COOL_DOWN', movementPattern: 'STRETCH' })).toEqual([
        { text: 'Cool-down', tone: 'section' },
        { text: 'Flexibility', tone: 'plain' },
      ]);
    });

    test('without a movement pattern the second tag is the equipment, and without that there is none', () => {
      expect(exerciseTags({ section: 'WARM_UP', equipment: [] })).toEqual([
        { text: 'Warm-up', tone: 'section' },
        { text: 'Bodyweight', tone: 'plain' },
      ]);
      expect(exerciseTags({ section: 'COOL_DOWN' })).toEqual([{ text: 'Cool-down', tone: 'section' }]);
    });

    test('a movement pattern of the main workout is not a tag; the equipment is used instead', () => {
      expect(exerciseTags({ section: 'WARM_UP', movementPattern: 'SQUAT', equipment: ['Resistance Band'] })).toEqual([
        { text: 'Warm-up', tone: 'section' },
        { text: 'Resistance Band', tone: 'plain' },
      ]);
      expect(exerciseTags({ section: 'WARM_UP', movementPattern: 'LUNGE' })).toEqual([{ text: 'Warm-up', tone: 'section' }]);
    });

    test('the muscles are not used here: a warm-up is named by its section, not by what it trains', () => {
      expect(exerciseTags({ section: 'WARM_UP', muscles: muscles(['Core', 'PRIMARY']) })).toEqual([{ text: 'Warm-up', tone: 'section' }]);
    });
  });
});

describe('muscleFocus', () => {
  test("is the main workout's primary muscles, most trained first, then its secondary ones", () => {
    const focus = muscleFocus([
      exercise(1, { section: 'WARM_UP', muscles: muscles(['Chest', 'PRIMARY']) }),
      exercise(2, { muscles: muscles(['Core', 'PRIMARY'], ['Shoulders', 'SECONDARY']) }),
      exercise(3, { muscles: muscles(['Glutes', 'PRIMARY'], ['Lower Back', 'SECONDARY']) }),
      exercise(4, { muscles: muscles(['Core', 'PRIMARY']) }),
    ]);

    // Chest is only in the warm-up, so it is not part of what the workout trains
    expect(focus).toEqual({ primary: ['Core', 'Glutes'], secondary: ['Shoulders', 'Lower Back'] });
  });

  test('ties keep the order the muscles first appeared in', () => {
    const focus = muscleFocus([
      exercise(1, { muscles: muscles(['Glutes', 'PRIMARY']) }),
      exercise(2, { muscles: muscles(['Core', 'PRIMARY']) }),
    ]);

    expect(focus?.primary).toEqual(['Glutes', 'Core']);
  });

  test('shows at most three primary muscles and four in all', () => {
    const focus = muscleFocus([
      exercise(1, { muscles: muscles(['A', 'PRIMARY'], ['B', 'PRIMARY'], ['C', 'PRIMARY'], ['D', 'PRIMARY'], ['E', 'SECONDARY'], ['F', 'SECONDARY']) }),
    ]);

    expect(focus).toEqual({ primary: ['A', 'B', 'C'], secondary: ['E'] });
  });

  test('a muscle that is primary somewhere is not also listed as secondary', () => {
    const focus = muscleFocus([
      exercise(1, { muscles: muscles(['Core', 'PRIMARY'], ['Shoulders', 'SECONDARY']) }),
      exercise(2, { muscles: muscles(['Shoulders', 'PRIMARY']) }),
    ]);

    expect(focus).toEqual({ primary: ['Core', 'Shoulders'], secondary: [] });
  });

  test('a workout with no main exercise that carries muscles uses all of its exercises', () => {
    const focus = muscleFocus([
      exercise(1, { section: 'MAIN_WORKOUT' }),
      exercise(2, { section: 'COOL_DOWN', muscles: muscles(['Hamstrings', 'PRIMARY']) }),
    ]);

    expect(focus).toEqual({ primary: ['Hamstrings'], secondary: [] });
  });

  test('is null when nothing carries muscles: the plan says nothing about them, so nothing is shown', () => {
    expect(muscleFocus([])).toBeNull();
    expect(muscleFocus([exercise(1), exercise(2, { muscles: [] }), exercise(3, { muscles: null })])).toBeNull();
  });

  test('works from secondary muscles alone', () => {
    expect(muscleFocus([exercise(1, { muscles: muscles(['Calves', 'SECONDARY']) })])).toEqual({
      primary: [],
      secondary: ['Calves'],
    });
  });
});

describe('coversPhrase', () => {
  test('names what the workout mainly trains, in lower case: "Covers core"', () => {
    expect(coversPhrase({ primary: ['Core'], secondary: ['Shoulders'] })).toBe('Covers core');
    expect(coversPhrase({ primary: ['Core', 'Lower Back'], secondary: [] })).toBe('Covers core, lower back');
  });

  test('is nothing when there is no primary muscle to name, or no focus at all', () => {
    expect(coversPhrase({ primary: [], secondary: ['Calves'] })).toBeNull();
    expect(coversPhrase(null)).toBeNull();
  });
});

describe('workoutCardFromDetails', () => {
  const workout: WorkoutDetailsData = {
    id: 9,
    title: 'Legs',
    description: 'Squats and hinges.',
    durationMinutes: 30,
    categories: ['lower-body'],
    exercises: [exercise(1), exercise(2), exercise(3)],
  };

  test('is the card of the same workout, counting the exercises the screen shows', () => {
    expect(workoutCardFromDetails(workout)).toEqual({
      id: 9,
      title: 'Legs',
      description: 'Squats and hinges.',
      durationMinutes: 30,
      exerciseCount: 3,
      categories: ['lower-body'],
    });
  });

  test('passes what is missing on as missing: nothing is filled in', () => {
    const card = workoutCardFromDetails({ id: 'x', title: 'Bare', exercises: [] });

    expect(card.description).toBeUndefined();
    expect(card.durationMinutes).toBeUndefined();
    expect(card.categories).toBeUndefined();
    expect(card.exerciseCount).toBe(0);
  });
});
