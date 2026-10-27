// The kinds of workout the app has a picture for, and how a workout's categories become one.
//
// The backend's workout plan has NO category field (WorkoutPlanResponse: id, name, description,
// status, scheduled_date, exercises), so nothing here is read from it. A card gets its categories
// from whoever builds its data: the design phase's mock data now, and in the integration phase either
// a rule over the catalog (movement patterns, muscle groups) or a backend field. Until then a real
// plan simply has none, and its card shows the neutral picture and no category label.

export const WORKOUT_CATEGORIES = [
  'core',
  'upper-body',
  'lower-body',
  'full-body',
  'cardio',
  'mobility',
  'recovery',
  'beginner',
] as const;

export type WorkoutCategory = (typeof WORKOUT_CATEGORIES)[number];

// The small heading above a card's title. Core, upper-body and lower-body workouts are all
// "Strength", as the design groups them: the picture tells them apart, so the label does not have to.
export const WORKOUT_CATEGORY_LABELS: Record<WorkoutCategory, string> = {
  core: 'Strength',
  'upper-body': 'Strength',
  'lower-body': 'Strength',
  'full-body': 'Full body',
  cardio: 'Cardio',
  mobility: 'Mobility',
  recovery: 'Recovery',
  beginner: 'Beginner',
};

// Which category wins when a workout lists several and none is clearly the main one. A fixed order, so
// the same workout always gets the same picture whatever order its categories arrive in: the broadest
// kind of training first, and "beginner" last, so that it names a workout only when nothing else does
// (a known workout is never relabelled just because it suits a beginner).
const PRIORITY: readonly WorkoutCategory[] = [
  'full-body',
  'lower-body',
  'upper-body',
  'core',
  'cardio',
  'mobility',
  'recovery',
  'beginner',
];

export function isWorkoutCategory(value: unknown): value is WorkoutCategory {
  return typeof value === 'string' && (WORKOUT_CATEGORIES as readonly string[]).includes(value);
}

// The one category a workout is shown as, or null when it has no known one. Values this app does not
// know are ignored (data from outside may carry them), never guessed at.
export function primaryCategory(
  categories: readonly WorkoutCategory[] | null | undefined,
): WorkoutCategory | null {
  const known = new Set((categories ?? []).filter(isWorkoutCategory));
  if (known.size === 0) return null;
  // training the upper and the lower body in one workout is a full-body workout
  if (known.has('upper-body') && known.has('lower-body')) return 'full-body';
  return PRIORITY.find((category) => known.has(category)) ?? null;
}
