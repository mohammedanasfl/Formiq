import { formatDuration, positiveInteger, type PlannedExercise } from './planDetails';

// The plain rules that turn one planned exercise into what its details screen shows. Each rule reads only what
// the exercise carries (see PlannedExercise for where each field comes from): a field it does not have gives
// nothing here, and the screen then says it is not available. Nothing is worked out, borrowed or made up.

// The three tabs under the animation, in the order shown.
export type ExerciseTab = 'instructions' | 'muscles' | 'tips';

export const EXERCISE_TABS: readonly { id: ExerciseTab; label: string }[] = [
  { id: 'instructions', label: 'Instructions' },
  { id: 'muscles', label: 'Muscles' },
  { id: 'tips', label: 'Tips' },
];

// What each tab says when the exercise has nothing for it.
export const UNAVAILABLE: Record<ExerciseTab, string> = {
  instructions: 'No instructions for this exercise yet.',
  muscles: "Muscle details aren't available for this exercise.",
  tips: 'No tips for this exercise yet.',
};

const clean = (text: string | null | undefined) => text?.trim() ?? '';

// the names of a list with blanks and repeats left out, in the order given
const names = (list: readonly string[] | null | undefined) => [
  ...new Set((list ?? []).map((name) => clean(name)).filter(Boolean)),
];

// The most labels under the title, so it stays one compact row: two muscles and two pieces of equipment
const MAX_MUSCLE_LABELS = 2;
const MAX_EQUIPMENT_LABELS = 2;

// The compact labels under the title: the primary muscle groups, then the equipment ("Bodyweight" for an
// exercise that needs none, the catalog's empty list). An exercise whose muscles or equipment are not known
// gets none of that kind.
export function detailLabels(exercise: Pick<PlannedExercise, 'muscles' | 'equipment'>): string[] {
  const muscles = names((exercise.muscles ?? []).filter((muscle) => muscle.role === 'PRIMARY').map((muscle) => muscle.name));
  const equipment = exercise.equipment ? names(exercise.equipment) : null;
  const gear = equipment === null ? [] : equipment.length === 0 ? ['Bodyweight'] : equipment.slice(0, MAX_EQUIPMENT_LABELS);
  return [...new Set([...muscles.slice(0, MAX_MUSCLE_LABELS), ...gear])];
}

export type InstructionsContent =
  // the catalog's steps, in order
  | { kind: 'steps'; steps: string[] }
  // no steps, but a description: shown as it is written (it is free text, not a list)
  | { kind: 'description'; text: string }
  | { kind: 'none' };

// What the Instructions tab shows: the steps when the exercise has any, else its description (Formiq's own
// exercises keep their steps in the description), else nothing.
export function instructionsContent(exercise: Pick<PlannedExercise, 'instructions' | 'description'>): InstructionsContent {
  const steps = (exercise.instructions ?? []).map(clean).filter(Boolean);
  if (steps.length > 0) return { kind: 'steps', steps };
  const text = clean(exercise.description);
  return text ? { kind: 'description', text } : { kind: 'none' };
}

export type ExerciseMuscles = {
  primary: string[];
  secondary: string[];
};

// What the Muscles tab shows: the muscles the exercise trains, the main ones first. A muscle listed in both
// roles is a main one. Null when the exercise carries none.
export function exerciseMuscles(exercise: Pick<PlannedExercise, 'muscles'>): ExerciseMuscles | null {
  const all = exercise.muscles ?? [];
  const primary = names(all.filter((muscle) => muscle.role === 'PRIMARY').map((muscle) => muscle.name));
  const secondary = names(all.filter((muscle) => muscle.role === 'SECONDARY').map((muscle) => muscle.name)).filter(
    (name) => !primary.includes(name),
  );
  return primary.length === 0 && secondary.length === 0 ? null : { primary, secondary };
}

export type TipItem = {
  id: 'notes' | 'rest' | 'weight' | 'about';
  // what the line is, in words: the data has no field of tips, so each line says where it comes from
  label: string;
  text: string;
};

// "20 kg", "22.5 kg": the plan's own number, without trailing zeros
const formatKilograms = (kilograms: number) => `${Number(kilograms.toFixed(2))} kg`;

// What the Tips tab shows. The data contract has no tips, so it is made only of what the plan and the catalog
// do say about doing the exercise: the plan's note on it, the rest between sets, the weight, and (when the
// Instructions tab already shows the steps) the catalog's description. Each line is labelled with what it is.
export function tipItems(
  exercise: Pick<PlannedExercise, 'notes' | 'restSeconds' | 'weightKg' | 'description' | 'instructions'>,
): TipItem[] {
  const items: TipItem[] = [];
  const notes = clean(exercise.notes);
  if (notes) items.push({ id: 'notes', label: 'Plan note', text: notes });
  if (positiveInteger(exercise.restSeconds)) {
    items.push({ id: 'rest', label: 'Rest between sets', text: formatDuration(exercise.restSeconds) });
  }
  if (typeof exercise.weightKg === 'number' && Number.isFinite(exercise.weightKg) && exercise.weightKg > 0) {
    items.push({ id: 'weight', label: 'Weight', text: formatKilograms(exercise.weightKg) });
  }
  // a description that is already the Instructions tab's (no steps) is not said twice
  const about = clean(exercise.description);
  if (about && instructionsContent(exercise).kind === 'steps') {
    items.push({ id: 'about', label: 'About this exercise', text: about });
  }
  return items;
}

// ---- the active set -------------------------------------------------------------------------------------

// What one set asks for, and how far the person may change it. The numbers are this screen's limits, not the
// plan's or the backend's (which only ask for a positive whole number): 1 to 100 reps, and 5 seconds to 10
// minutes in steps of 5. A target outside them (a plan may ask for more) keeps its own value as the edge.
const REPS_LIMITS = { min: 1, max: 100, step: 1 } as const;
const SECONDS_LIMITS = { min: 5, max: 600, step: 5 } as const;

export type SetTarget = {
  unit: 'reps' | 'seconds';
  min: number;
  max: number;
  step: number;
  // the plan's number, where the control starts
  initial: number;
};

// The target the plan gives each set, with the limits it may be changed within. Reps win if a source gives both
// (a plan never does). Null when the plan gives no target: the screen then shows none and invents none.
export function setTarget(exercise: Pick<PlannedExercise, 'reps' | 'durationSeconds'>): SetTarget | null {
  if (positiveInteger(exercise.reps)) return withLimits('reps', exercise.reps, REPS_LIMITS);
  if (positiveInteger(exercise.durationSeconds)) return withLimits('seconds', exercise.durationSeconds, SECONDS_LIMITS);
  return null;
}

function withLimits(unit: SetTarget['unit'], initial: number, limits: { min: number; max: number; step: number }): SetTarget {
  return { unit, initial, step: limits.step, min: Math.min(limits.min, initial), max: Math.max(limits.max, initial) };
}

// One step up (+1) or down (-1) from `value`, never past the limits
export function stepTarget(target: SetTarget, value: number, direction: 1 | -1): number {
  return Math.min(target.max, Math.max(target.min, value + direction * target.step));
}

// "12 reps", "1 rep", "30 seconds", "1 min 30 sec": the number in the units a person counts it in
export function targetLabel(unit: SetTarget['unit'], value: number): string {
  if (unit === 'seconds') return formatDuration(value);
  return `${value} ${value === 1 ? 'rep' : 'reps'}`;
}

// How many sets the plan asks for; null when it does not say
export function totalSets(exercise: Pick<PlannedExercise, 'sets'>): number | null {
  return positiveInteger(exercise.sets) ? exercise.sets : null;
}

// "Set 2 of 3", or "Set 2" when the plan gives no number of sets
export function setProgressLabel(current: number, total: number | null): string {
  return total === null ? `Set ${current}` : `Set ${current} of ${total}`;
}

// What is said when a set is marked done. The app has no workout session to put it in, so it says plainly that
// it is kept on this screen only.
export function setDoneNotice(done: number, total: number | null): string {
  return `${setProgressLabel(done, total)} marked done on this screen only. Nothing was saved.`;
}
