import type { WorkoutCategory } from './categories';
import type { ExerciseGif } from './exerciseGifs';
import type { ExerciseImage } from './exerciseImages';
import type { WorkoutCardData } from './types';

// What the workout screen is given, and the plain rules that turn it into what the screen shows. Each
// field says where its value comes from, because the backend's workout plan
// (backend/app/schemas/workout_plan.py) carries less than the screen can show: a field it does not have is
// optional here and the screen leaves it out, never filling it in. The screen takes this shape from
// whoever builds it (the design phase's mock fixture now; in the integration phase a mapper from
// WorkoutPlanResponse, plus a catalog lookup for the fields marked below).

// The parts of a workout, with the backend's own names (WorkoutSection).
export type PlanSection = 'WARM_UP' | 'MAIN_WORKOUT' | 'COOL_DOWN';

// The three sections in the order they are done, and what each is called on the screen.
export const PLAN_SECTIONS: readonly { id: PlanSection; title: string }[] = [
  { id: 'WARM_UP', title: 'Warm-up' },
  { id: 'MAIN_WORKOUT', title: 'Main Workout' },
  { id: 'COOL_DOWN', title: 'Cool-down' },
];

// The catalog's movement patterns (MovementPattern in backend/app/schemas/exercise.py). The last three are
// the ones Formiq gives its warm-up and cool-down activities.
export type ExerciseMovement =
  | 'HORIZONTAL_PUSH'
  | 'HORIZONTAL_PULL'
  | 'VERTICAL_PUSH'
  | 'VERTICAL_PULL'
  | 'SQUAT'
  | 'HINGE'
  | 'LUNGE'
  | 'CARRY'
  | 'ROTATION'
  | 'ISOLATION'
  | 'MOBILITY'
  | 'STRETCH'
  | 'CARDIO';

export type ExerciseMuscle = {
  name: string;
  role: 'PRIMARY' | 'SECONDARY';
};

export type PlannedExercise = {
  // WorkoutPlanExerciseResponse.id: the row's identity and its React key
  id: number | string;
  // .exercise_order: the exercise's place in the whole workout
  order: number;
  // .section
  section: PlanSection;
  // .exercise.name
  name: string;
  // .sets
  sets: number;
  // .reps and .duration_seconds: a plan gives each set one of the two (never both)
  reps?: number | null;
  durationSeconds?: number | null;
  // NOT in the plan response or the catalog: an exercise done on one side and then the other ("each side").
  // The plan could only say it in its free-text `notes`. Shown only when a source supplies it.
  eachSide?: boolean | null;
  // NOT in the plan response: the catalog's record of the exercise (ExerciseResponse, by exercise_id).
  // Its movement pattern; null/absent when Formiq has not classified the exercise.
  movementPattern?: ExerciseMovement | null;
  // The catalog's equipment names. An empty list means it needs none; absent means not known.
  equipment?: readonly string[] | null;
  // The catalog's muscles, as ExerciseResponse.muscles has them
  muscles?: readonly ExerciseMuscle[] | null;
  // NOT in the plan response: a picture, if there is one to show (see exerciseImages.ts)
  image?: ExerciseImage | null;
  // .exercise.instructions: the catalog record's steps, in order; an empty list when the record has none
  instructions?: readonly string[] | null;
  // .exercise.description: Formiq's own description (the steps, a suggested dose and a safety note) or, for an
  // imported exercise, one summary sentence; null when it has none
  description?: string | null;
  // .weight_kg, .rest_seconds and .notes: what the plan itself says about this exercise
  weightKg?: number | null;
  restSeconds?: number | null;
  notes?: string | null;
  // NOT in the plan response or the catalog: a looping animation, if there is one to play (see exerciseGifs.ts)
  animation?: ExerciseGif | null;
};

export type WorkoutDetailsData = {
  // WorkoutPlanResponse.id: the screen's stable identity
  id: number | string;
  // WorkoutPlanResponse.name
  title: string;
  // WorkoutPlanResponse.description (null when the plan has none)
  description?: string | null;
  // NOT in the backend contract: the plan stores no length. Shown only when a source supplies one.
  durationMinutes?: number | null;
  // NOT in the backend contract: the length of each section, likewise. Shown only for the sections a source
  // gives one for.
  sectionMinutes?: Partial<Record<PlanSection, number>> | null;
  // NOT in the backend contract (see categories.ts). Absent means "unknown", not "none".
  categories?: readonly WorkoutCategory[] | null;
  // WorkoutPlanResponse.exercises. The count the screen shows is how many there are.
  exercises: readonly PlannedExercise[];
};

// The card a workout has on Home (and wherever workouts are listed), from the details the workout's own
// screen shows, so the two never disagree: the count on the card is the number of exercises on the screen.
export function workoutCardFromDetails(workout: WorkoutDetailsData): WorkoutCardData {
  return {
    id: workout.id,
    title: workout.title,
    description: workout.description,
    durationMinutes: workout.durationMinutes,
    exerciseCount: workout.exercises.length,
    categories: workout.categories,
  };
}

export type SectionGroup = {
  id: PlanSection;
  title: string;
  exercises: PlannedExercise[];
  // the section's length in minutes, when the workout gives one
  minutes: number | null;
};

export const positiveInteger = (value: number | null | undefined): value is number =>
  typeof value === 'number' && Number.isInteger(value) && value >= 1;

// The exercises in their three sections, in the order the workout is done (warm-up, main, cool-down)
// whatever order they arrive in, and each section in its exercises' own order (equal places keep the order
// they arrived in). A section with no exercises is left out: there is no empty heading.
export function groupBySection(
  exercises: readonly PlannedExercise[],
  sectionMinutes?: WorkoutDetailsData['sectionMinutes'],
): SectionGroup[] {
  return PLAN_SECTIONS.map(({ id, title }) => ({
    id,
    title,
    minutes: positiveInteger(sectionMinutes?.[id]) ? sectionMinutes![id]! : null,
    exercises: exercises
      .map((exercise, arrived) => ({ exercise, arrived }))
      .filter(({ exercise }) => exercise.section === id)
      .sort((a, b) => a.exercise.order - b.exercise.order || a.arrived - b.arrived)
      .map(({ exercise }) => exercise),
  })).filter((group) => group.exercises.length > 0);
}

const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`;

// "1 exercise", "6 exercises"
export const exerciseCountLabel = (count: number) => plural(count, 'exercise', 'exercises');

// "23 minutes" (the workout's length at the top of the screen); null when the length is not a positive whole
// number of minutes
export function formatMinutes(minutes: number | null | undefined): string | null {
  if (typeof minutes !== 'number' || !Number.isFinite(minutes) || Math.round(minutes) < 1) return null;
  return plural(Math.round(minutes), 'minute', 'minutes');
}

// A section's heading line: "2 exercises • 3 min", or just "2 exercises" when its length is not known
export function sectionSummary(group: Pick<SectionGroup, 'exercises' | 'minutes'>): string {
  const count = exerciseCountLabel(group.exercises.length);
  return group.minutes ? `${count} • ${group.minutes} min` : count;
}

// "30 seconds", "1 minute", "1 min 30 sec": a held or timed set, in the units a person counts it in
export function formatDuration(seconds: number): string {
  const whole = Math.round(seconds);
  if (whole < 60) return plural(whole, 'second', 'seconds');
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;
  return rest === 0 ? plural(minutes, 'minute', 'minutes') : `${minutes} min ${rest} sec`;
}

// What one exercise asks for, from the plan's own numbers: "2 sets • 30 seconds", "3 sets • 20 reps (each side)",
// "1 set • 30 seconds". Null when the plan gives neither sets nor a target. Nothing is worked out or guessed:
// a missing number is left out.
export function formatPrescription(
  exercise: Pick<PlannedExercise, 'sets' | 'reps' | 'durationSeconds' | 'eachSide'>,
): string | null {
  const sets = positiveInteger(exercise.sets) ? plural(exercise.sets, 'set', 'sets') : null;
  const target = positiveInteger(exercise.reps)
    ? plural(exercise.reps, 'rep', 'reps')
    : positiveInteger(exercise.durationSeconds)
      ? formatDuration(exercise.durationSeconds)
      : null;
  if (!target) return sets;
  const each = exercise.eachSide ? `${target} (each side)` : target;
  return sets ? `${sets} • ${each}` : each;
}

// The words a warm-up or cool-down exercise's movement pattern goes by (the catalog's other patterns, the ones
// of the main workout, are not shown as a tag)
const MOVEMENT_LABELS: Partial<Record<ExerciseMovement, string>> = {
  MOBILITY: 'Mobility',
  CARDIO: 'Cardio',
  STRETCH: 'Flexibility',
};

export type ExerciseTag = {
  text: string;
  // `section` wears the section's own colors; `plain` the neutral ones
  tone: 'section' | 'plain';
};

// "Bodyweight" for an exercise that needs no equipment (the catalog's empty list), its first piece otherwise,
// and nothing when it is not known
function equipmentLabel(equipment: PlannedExercise['equipment']): string | null {
  if (!equipment) return null;
  const first = equipment.map((name) => name.trim()).find(Boolean);
  return first ?? (equipment.length === 0 ? 'Bodyweight' : null);
}

// The two small tags of a row. The first wears the section's color: the section's name for a warm-up or a
// cool-down exercise, and the main muscle the exercise trains for one of the main workout. The second is
// plain: the kind of movement for a warm-up or a cool-down (falling back to the equipment), and the equipment
// for the main workout. A tag whose source the exercise does not carry is left out.
export function exerciseTags(exercise: Pick<PlannedExercise, 'section' | 'movementPattern' | 'equipment' | 'muscles'>): ExerciseTag[] {
  const tags: ExerciseTag[] = [];
  const equipment = equipmentLabel(exercise.equipment);
  if (exercise.section === 'MAIN_WORKOUT') {
    const primary = (exercise.muscles ?? []).find((muscle) => muscle.role === 'PRIMARY')?.name.trim();
    if (primary) tags.push({ text: primary, tone: 'section' });
    if (equipment) tags.push({ text: equipment, tone: 'plain' });
    return tags;
  }
  const title = PLAN_SECTIONS.find((section) => section.id === exercise.section)?.title;
  if (title) tags.push({ text: title, tone: 'section' });
  const movement = exercise.movementPattern ? MOVEMENT_LABELS[exercise.movementPattern] : undefined;
  const plain = movement ?? equipment;
  if (plain) tags.push({ text: plain, tone: 'plain' });
  return tags;
}

export type MuscleFocus = {
  primary: string[];
  secondary: string[];
};

// The most muscles the focus shows, so it stays one compact row
const MAX_PRIMARY_MUSCLES = 3;
const MAX_FOCUS_MUSCLES = 4;

// The muscles a workout trains, from the catalog's muscles on its exercises: those of the main workout
// (a workout with no main exercise that carries muscles uses all of them). The ones trained as a primary
// muscle most often come first, and the rest are the secondary ones. Null when no exercise carries muscles:
// the screen then shows no indicator, as the plan itself says nothing about muscles.
export function muscleFocus(exercises: readonly PlannedExercise[]): MuscleFocus | null {
  const withMuscles = exercises.filter((exercise) => (exercise.muscles ?? []).length > 0);
  const main = withMuscles.filter((exercise) => exercise.section === 'MAIN_WORKOUT');
  const pool = main.length > 0 ? main : withMuscles;
  if (pool.length === 0) return null;

  const tally = (role: ExerciseMuscle['role']) => {
    const counts = new Map<string, number>();
    for (const exercise of pool) {
      for (const muscle of exercise.muscles ?? []) {
        if (muscle.role === role) counts.set(muscle.name, (counts.get(muscle.name) ?? 0) + 1);
      }
    }
    // Map keeps the order muscles first appeared in, and the sort is stable: ties keep that order
    return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([name]) => name);
  };

  const primaryAll = tally('PRIMARY');
  const primary = primaryAll.slice(0, MAX_PRIMARY_MUSCLES);
  const secondary = tally('SECONDARY')
    .filter((name) => !primaryAll.includes(name))
    .slice(0, MAX_FOCUS_MUSCLES - primary.length);
  if (primary.length === 0 && secondary.length === 0) return null;
  return { primary, secondary };
}

// "Covers core", "Covers core, glutes": what the workout mainly trains, in the words of the pill at the top
// of the screen. Null when there is no primary muscle to name.
export function coversPhrase(focus: MuscleFocus | null): string | null {
  if (!focus || focus.primary.length === 0) return null;
  return `Covers ${focus.primary.map((name) => name.toLowerCase()).join(', ')}`;
}
