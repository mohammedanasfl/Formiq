import type { WorkoutCategory } from './categories';

// What a workout card is given. Each field says where its value comes from, because the backend's
// workout plan (backend/app/schemas/workout_plan.py) has fewer fields than a card can show: a field it
// does not have is optional here and the card leaves it out, never filling it in.
export type WorkoutCardData = {
  // WorkoutPlanResponse.id: the card's stable identity, and the React key of its row
  id: number | string;
  // WorkoutPlanResponse.name
  title: string;
  // WorkoutPlanResponse.description (null when the plan has none)
  description?: string | null;
  // NOT in the backend contract: the plan stores no length. Shown only when a source supplies one.
  durationMinutes?: number | null;
  // WorkoutPlanResponse.exercises.length. Left out when absent or not a positive whole number.
  exerciseCount?: number | null;
  // NOT in the backend contract: see categories.ts. Absent means "unknown", not "none".
  categories?: readonly WorkoutCategory[] | null;
};
