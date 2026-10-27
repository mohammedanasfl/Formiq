// MOCK DATA: nothing in this file comes from the Formiq backend.
//
// The design phase builds the workout screen against this made-up workout so its look can be settled before
// any integration. It is not a user's plan, and no screen may present it as if it were. When the screen is
// connected, it receives its `WorkoutDetailsData` from a mapper over the backend's plan instead, and this
// file goes away. Home's "Today's workout" card is made from it (see homeMock.ts), so the card and the
// screen agree on the name, the length and the number of exercises.
//
// What a real plan will NOT have, and this fixture invents so the screen can be drawn in full:
//   - the workout's length and category, and the length of each section (the plan stores none of them: see
//     src/workouts/types.ts);
//   - each exercise's movement pattern, equipment and muscles (the plan response has only the exercise's
//     name, description and steps; these come from the catalog, GET /exercises/{id}, which a later step
//     looks up), and whether it is done on each side (nothing in the backend says so);
//   - each exercise's picture (the catalog serves its own images; these are the development set in
//     assets/images/exercises) and its looping animation (the catalog has none; the six GIFs supplied with the
//     design, in assets/images/exercise-gifs, are development placeholders, and only Plank and Lunges have one);
//   - what the details screen shows beyond the plan: the rest between sets and a note, which are made up here.
// The values above are illustrative: they are not copied from the catalog, which has the final say. The one
// exception is the steps of Mountain Climbers, Plank and Hamstring Stretch: they are the free-exercise-db
// record of the same name, word for word (backend/data/free-exercise-db/exercises.json: "Mountain_Climbers",
// "Plank", "Hamstring_Stretch"). The other three have no record of their own name, so they have no steps, and
// their Instructions tab says so.
//
// What it does have the way a real plan does: sections (WARM_UP, MAIN_WORKOUT, COOL_DOWN), sets, and one
// target per set (reps, or seconds for a held or timed set), in the plan's exercise order.
//
// It follows the design reference's structure: two warm-up exercises, three main ones and one cool-down. The
// reference's own numbers disagree with its list (it says 5 exercises and lists 6); the screen counts what
// is there.

import { exerciseGif } from '../workouts/exerciseGifs';
import { exerciseImage } from '../workouts/exerciseImages';
import type { PlannedExercise, WorkoutDetailsData } from '../workouts/planDetails';

export const MOCK_TODAY_WORKOUT: WorkoutDetailsData = {
  id: 'mock-workout-today',
  title: 'Core & Abs Focus',
  description: 'Strengthen your core and improve stability.',
  durationMinutes: 23,
  sectionMinutes: { WARM_UP: 3, MAIN_WORKOUT: 18, COOL_DOWN: 2 },
  categories: ['core'],
  exercises: [
    // warm-up
    mock(1, 'WARM_UP', 'Mountain Climbers', { sets: 2, durationSeconds: 30 }, 'CARDIO', [], [['Core', 'PRIMARY'], ['Quadriceps', 'SECONDARY'], ['Shoulders', 'SECONDARY']], 'mountain-climbers', {
      restSeconds: 30,
      instructions: [
        'Begin in a pushup position, with your weight supported by your hands and toes. Flexing the knee and hip, bring one leg until the knee is approximately under the hip. This will be your starting position.',
        'Explosively reverse the positions of your legs, extending the bent leg until the leg is straight and supported by the toe, and bringing the other foot up with the hip and knee flexed. Repeat in an alternating fashion for 20-30 seconds.',
      ],
    }),
    mock(2, 'WARM_UP', 'Lunges', { sets: 2, reps: 10, eachSide: true }, 'MOBILITY', [], [['Quadriceps', 'PRIMARY'], ['Glutes', 'SECONDARY']], 'lunges', {
      restSeconds: 30,
      gif: 'lunge',
    }),
    // main workout
    mock(3, 'MAIN_WORKOUT', 'Plank', { sets: 3, durationSeconds: 30 }, null, [], [['Core', 'PRIMARY'], ['Shoulders', 'SECONDARY']], 'plank', {
      restSeconds: 45,
      notes: 'Hold the full 30 seconds before resting.',
      gif: 'plank',
      instructions: [
        'Get into a prone position on the floor, supporting your weight on your toes and your forearms. Your arms are bent and directly below the shoulder.',
        'Keep your body straight at all times, and hold this position as long as possible. To increase difficulty, an arm or leg can be raised.',
      ],
    }),
    mock(4, 'MAIN_WORKOUT', 'Bicycle Crunches', { sets: 3, reps: 20, eachSide: true }, null, [], [['Core', 'PRIMARY']], 'bicycle-crunches', { restSeconds: 45 }),
    mock(5, 'MAIN_WORKOUT', 'Leg Raises', { sets: 3, reps: 15 }, null, [], [['Core', 'PRIMARY'], ['Quadriceps', 'SECONDARY']], 'leg-raises', { restSeconds: 45 }),
    // cool-down
    mock(6, 'COOL_DOWN', 'Hamstring Stretch', { sets: 1, durationSeconds: 30, eachSide: true }, 'STRETCH', [], [['Hamstrings', 'PRIMARY'], ['Lower Back', 'SECONDARY']], 'hamstring-stretch', {
      instructions: [
        'Lie on your back with one leg extended above you, with the hip at ninety degrees. Keep the other leg flat on the floor.',
        'Loop a belt, band, or rope over the ball of your foot. This will be your starting position.',
        'Pull on the belt to create tension in the calves and hamstrings. Hold this stretch for 10-30 seconds, and repeat with the other leg.',
      ],
    }),
  ],
};

// The workouts that have a screen, by the id of the card that opens them. Only today's has one: a card
// whose id is not here has nothing to open yet.
const MOCK_WORKOUT_DETAILS: Record<string, WorkoutDetailsData> = {
  [MOCK_TODAY_WORKOUT.id]: MOCK_TODAY_WORKOUT,
};

export function findMockWorkoutDetails(id: number | string): WorkoutDetailsData | null {
  return Object.prototype.hasOwnProperty.call(MOCK_WORKOUT_DETAILS, id) ? MOCK_WORKOUT_DETAILS[id] : null;
}

function mock(
  order: number,
  section: PlannedExercise['section'],
  name: string,
  target: Pick<PlannedExercise, 'sets' | 'reps' | 'durationSeconds' | 'eachSide'>,
  movementPattern: PlannedExercise['movementPattern'],
  equipment: string[],
  muscles: [string, 'PRIMARY' | 'SECONDARY'][],
  imageKey: string,
  extras: { instructions?: string[]; restSeconds?: number; notes?: string; gif?: string } = {},
): PlannedExercise {
  const { gif, ...plan } = extras;
  return {
    id: `mock-exercise-${order}`,
    order,
    section,
    name,
    ...target,
    movementPattern,
    equipment,
    muscles: muscles.map(([muscle, role]) => ({ name: muscle, role })),
    image: exerciseImage(imageKey),
    animation: exerciseGif(gif),
    ...plan,
  };
}
