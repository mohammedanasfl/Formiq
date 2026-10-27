import {
  detailLabels,
  EXERCISE_TABS,
  exerciseMuscles,
  instructionsContent,
  setDoneNotice,
  setProgressLabel,
  setTarget,
  stepTarget,
  targetLabel,
  tipItems,
  totalSets,
  UNAVAILABLE,
} from '../src/workouts/exerciseDetails';

describe('the tabs', () => {
  test('are Instructions, Muscles and Tips, in that order, each with something to say when it has nothing', () => {
    expect(EXERCISE_TABS).toEqual([
      { id: 'instructions', label: 'Instructions' },
      { id: 'muscles', label: 'Muscles' },
      { id: 'tips', label: 'Tips' },
    ]);
    expect(Object.keys(UNAVAILABLE)).toEqual(['instructions', 'muscles', 'tips']);
  });
});

describe('detailLabels', () => {
  test('are the primary muscles, then the equipment', () => {
    expect(
      detailLabels({
        muscles: [
          { name: 'Core', role: 'PRIMARY' },
          { name: 'Shoulders', role: 'SECONDARY' },
        ],
        equipment: ['Dumbbell'],
      }),
    ).toEqual(['Core', 'Dumbbell']);
  });

  test('say "Bodyweight" for an exercise the catalog lists no equipment for', () => {
    expect(detailLabels({ muscles: [{ name: 'Core', role: 'PRIMARY' }], equipment: [] })).toEqual(['Core', 'Bodyweight']);
  });

  test('leave out what is not known: no muscles and no equipment list give no labels', () => {
    expect(detailLabels({})).toEqual([]);
    expect(detailLabels({ muscles: null, equipment: null })).toEqual([]);
    expect(detailLabels({ muscles: [{ name: 'Core', role: 'SECONDARY' }] })).toEqual([]);
  });

  test('stay compact: two muscles and two pieces of equipment at most, without blanks or repeats', () => {
    expect(
      detailLabels({
        muscles: [
          { name: 'Chest', role: 'PRIMARY' },
          { name: ' Chest ', role: 'PRIMARY' },
          { name: 'Triceps', role: 'PRIMARY' },
          { name: 'Shoulders', role: 'PRIMARY' },
        ],
        equipment: ['Barbell', '  ', 'Bench', 'Rack'],
      }),
    ).toEqual(['Chest', 'Triceps', 'Barbell', 'Bench']);
  });
});

describe('instructionsContent', () => {
  test('is the steps, in order, when the exercise has them', () => {
    expect(instructionsContent({ instructions: ['Lie down.', ' Sit up. ', ''] })).toEqual({
      kind: 'steps',
      steps: ['Lie down.', 'Sit up.'],
    });
  });

  test('keeps the steps and leaves the description to the Tips tab when it has both', () => {
    expect(instructionsContent({ instructions: ['Hold.'], description: 'A plank.' })).toEqual({ kind: 'steps', steps: ['Hold.'] });
  });

  test("is the description as written when there are no steps (Formiq's own exercises keep their steps there)", () => {
    expect(instructionsContent({ instructions: [], description: ' Step one. Step two. ' })).toEqual({
      kind: 'description',
      text: 'Step one. Step two.',
    });
    expect(instructionsContent({ description: 'About it.' })).toEqual({ kind: 'description', text: 'About it.' });
  });

  test.each([
    ['nothing', {}],
    ['null fields', { instructions: null, description: null }],
    ['an empty list and a blank description', { instructions: ['  '], description: '   ' }],
  ])('is nothing for %s: no steps are made up', (_name, exercise) => {
    expect(instructionsContent(exercise)).toEqual({ kind: 'none' });
  });
});

describe('exerciseMuscles', () => {
  test('lists the muscles in two groups', () => {
    expect(
      exerciseMuscles({
        muscles: [
          { name: 'Core', role: 'PRIMARY' },
          { name: 'Shoulders', role: 'SECONDARY' },
          { name: 'Quadriceps', role: 'SECONDARY' },
        ],
      }),
    ).toEqual({ primary: ['Core'], secondary: ['Shoulders', 'Quadriceps'] });
  });

  test('counts a muscle listed in both roles as a main one, once', () => {
    expect(
      exerciseMuscles({
        muscles: [
          { name: 'Core', role: 'SECONDARY' },
          { name: 'Core', role: 'PRIMARY' },
          { name: 'Core', role: 'PRIMARY' },
        ],
      }),
    ).toEqual({ primary: ['Core'], secondary: [] });
  });

  test('is null when the exercise carries no muscles', () => {
    expect(exerciseMuscles({})).toBeNull();
    expect(exerciseMuscles({ muscles: [] })).toBeNull();
    expect(exerciseMuscles({ muscles: [{ name: '  ', role: 'PRIMARY' }] })).toBeNull();
  });
});

describe('tipItems', () => {
  test('are what the plan and the catalog say about doing the exercise, each labelled with what it is', () => {
    expect(
      tipItems({
        notes: 'Keep it slow.',
        restSeconds: 90,
        weightKg: 22.5,
        instructions: ['Lift.'],
        description: 'A beginner exercise.',
      }),
    ).toEqual([
      { id: 'notes', label: 'Plan note', text: 'Keep it slow.' },
      { id: 'rest', label: 'Rest between sets', text: '1 min 30 sec' },
      { id: 'weight', label: 'Weight', text: '22.5 kg' },
      { id: 'about', label: 'About this exercise', text: 'A beginner exercise.' },
    ]);
  });

  test('writes a whole weight without a decimal point', () => {
    expect(tipItems({ weightKg: 20 })).toEqual([{ id: 'weight', label: 'Weight', text: '20 kg' }]);
  });

  test('does not say the description twice: when there are no steps it is already on the Instructions tab', () => {
    expect(tipItems({ description: 'Steps, in words.', instructions: [] })).toEqual([]);
  });

  test.each([
    ['nothing', {}],
    ['nulls', { notes: null, restSeconds: null, weightKg: null, description: null }],
    ['a blank note', { notes: '  ' }],
    ['no rest', { restSeconds: 0 }],
    ['a weight that is not a weight', { weightKg: 0 }],
    ['an infinite weight', { weightKg: Infinity }],
  ])('are none for %s: no tips are made up', (_name, exercise) => {
    expect(tipItems(exercise)).toEqual([]);
  });
});

describe('setTarget', () => {
  test('starts at the reps the plan gives, with limits of 1 to 100', () => {
    expect(setTarget({ reps: 12 })).toEqual({ unit: 'reps', initial: 12, min: 1, max: 100, step: 1 });
  });

  test('starts at the seconds the plan gives, with limits of 5 seconds to 10 minutes in steps of 5', () => {
    expect(setTarget({ durationSeconds: 30 })).toEqual({ unit: 'seconds', initial: 30, min: 5, max: 600, step: 5 });
  });

  test('lets a target outside the limits keep its own value as the edge, so it is never shown as another number', () => {
    expect(setTarget({ reps: 150 })).toMatchObject({ initial: 150, min: 1, max: 150 });
    expect(setTarget({ durationSeconds: 3 })).toMatchObject({ initial: 3, min: 3, max: 600 });
    expect(setTarget({ durationSeconds: 900 })).toMatchObject({ initial: 900, min: 5, max: 900 });
  });

  test('takes the reps when a source gives both', () => {
    expect(setTarget({ reps: 8, durationSeconds: 30 })).toMatchObject({ unit: 'reps', initial: 8 });
  });

  test.each([
    ['neither', {}],
    ['nulls', { reps: null, durationSeconds: null }],
    ['zero reps', { reps: 0 }],
    ['half a rep', { reps: 2.5 }],
    ['negative seconds', { durationSeconds: -30 }],
  ])('is null for %s: no target is made up', (_name, exercise) => {
    expect(setTarget(exercise)).toBeNull();
  });
});

describe('stepTarget', () => {
  const reps = setTarget({ reps: 12 })!;
  const seconds = setTarget({ durationSeconds: 30 })!;

  test('moves one step at a time: a rep, or five seconds', () => {
    expect(stepTarget(reps, 12, 1)).toBe(13);
    expect(stepTarget(reps, 12, -1)).toBe(11);
    expect(stepTarget(seconds, 30, 1)).toBe(35);
    expect(stepTarget(seconds, 30, -1)).toBe(25);
  });

  test('never goes past either limit', () => {
    expect(stepTarget(reps, 1, -1)).toBe(1);
    expect(stepTarget(reps, 100, 1)).toBe(100);
    expect(stepTarget(seconds, 5, -1)).toBe(5);
    expect(stepTarget(seconds, 8, -1)).toBe(5);
    expect(stepTarget(seconds, 600, 1)).toBe(600);
    expect(stepTarget(seconds, 598, 1)).toBe(600);
  });
});

describe('the words of a set', () => {
  test('targetLabel counts reps and writes seconds as a person says them', () => {
    expect(targetLabel('reps', 12)).toBe('12 reps');
    expect(targetLabel('reps', 1)).toBe('1 rep');
    expect(targetLabel('seconds', 30)).toBe('30 seconds');
    expect(targetLabel('seconds', 90)).toBe('1 min 30 sec');
  });

  test('totalSets is the plan\'s number of sets, or null when it gives none', () => {
    expect(totalSets({ sets: 3 })).toBe(3);
    expect(totalSets({ sets: 0 })).toBeNull();
    expect(totalSets({ sets: 1.5 })).toBeNull();
  });

  test('setProgressLabel says which set it is, of how many when that is known', () => {
    expect(setProgressLabel(2, 3)).toBe('Set 2 of 3');
    expect(setProgressLabel(2, null)).toBe('Set 2');
  });

  test('setDoneNotice says the set is kept on the screen only, and that nothing was saved', () => {
    expect(setDoneNotice(1, 3)).toBe('Set 1 of 3 marked done on this screen only. Nothing was saved.');
    expect(setDoneNotice(1, null)).toBe('Set 1 marked done on this screen only. Nothing was saved.');
  });
});
