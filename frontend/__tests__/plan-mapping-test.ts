import { workoutCardFromPlan, workoutDetailsFromPlan } from '../src/workouts/planMapping';
import { corePlan, plan, planExercise } from '../test-utils/workoutFixtures';

describe("a saved plan as Home's card", () => {
  test('takes the id, the name, the description and the number of exercises, and nothing else', () => {
    expect(workoutCardFromPlan(corePlan())).toEqual({
      id: 41,
      title: 'Core & Abs Focus',
      description: 'Strengthen your core and improve stability.',
      exerciseCount: 6,
    });
  });

  test('has no length and no category: the plan has neither, so they are not made up', () => {
    const card = workoutCardFromPlan(corePlan());

    expect(card).not.toHaveProperty('durationMinutes');
    expect(card).not.toHaveProperty('categories');
  });

  test('keeps a missing description missing', () => {
    expect(workoutCardFromPlan(plan({ description: null })).description).toBeNull();
  });

  test('counts every exercise of the plan: warm-up and cool-down included', () => {
    expect(workoutCardFromPlan(corePlan()).exerciseCount).toBe(corePlan().exercises.length);
    expect(workoutCardFromPlan(plan({ exercises: [] })).exerciseCount).toBe(0);
  });
});

describe("a saved plan as the workout screen's data", () => {
  const details = workoutDetailsFromPlan(
    plan({
      id: 7,
      name: 'Push Day',
      description: 'Chest and shoulders.',
      exercises: [
        planExercise({
          id: 70,
          exercise_order: 2,
          section: 'MAIN_WORKOUT',
          sets: 4,
          reps: 8,
          duration_seconds: null,
          weight_kg: 40,
          rest_seconds: 90,
          notes: 'Slow on the way down.',
          exercise: { name: 'Bench Press', description: 'A press.', instructions: ['Lie down.', 'Press.'] },
        }),
      ],
    }),
  );

  test("carries the plan's id, name and description", () => {
    expect(details).toMatchObject({ id: 7, title: 'Push Day', description: 'Chest and shoulders.' });
  });

  test("carries each exercise's own numbers and the catalog's words, under the screen's names", () => {
    expect(details.exercises).toEqual([
      {
        id: 70,
        order: 2,
        section: 'MAIN_WORKOUT',
        name: 'Bench Press',
        sets: 4,
        reps: 8,
        durationSeconds: null,
        weightKg: 40,
        restSeconds: 90,
        notes: 'Slow on the way down.',
        instructions: ['Lie down.', 'Press.'],
        description: 'A press.',
      },
    ]);
  });

  test('leaves out what the plan response does not carry: lengths, category, muscles, equipment, picture, animation', () => {
    expect(details).not.toHaveProperty('durationMinutes');
    expect(details).not.toHaveProperty('sectionMinutes');
    expect(details).not.toHaveProperty('categories');
    for (const key of ['movementPattern', 'equipment', 'muscles', 'image', 'animation', 'eachSide']) {
      expect(details.exercises[0]).not.toHaveProperty(key);
    }
  });

  test('keeps a timed exercise timed', () => {
    const [timed] = workoutDetailsFromPlan(
      plan({ exercises: [planExercise({ reps: null, duration_seconds: 30 })] }),
    ).exercises;

    expect([timed.reps, timed.durationSeconds]).toEqual([null, 30]);
  });
});
