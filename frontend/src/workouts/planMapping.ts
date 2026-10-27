import type { WorkoutPlan } from '../api';
import type { WorkoutDetailsData } from './planDetails';
import type { WorkoutCardData } from './types';

// A saved plan as the app's screens take it. Only what the plan response (WorkoutPlanResponse) carries is
// copied: its length, its category, each section's length and each exercise's movement, equipment, muscles,
// picture and animation are not in it, so they are left out, and the screens leave them out too (see
// types.ts and planDetails.ts). Nothing is worked out or guessed.

export function workoutCardFromPlan(plan: WorkoutPlan): WorkoutCardData {
  return {
    id: plan.id,
    title: plan.name,
    description: plan.description,
    // every exercise of the plan, warm-up and cool-down included, as its own screen counts them
    exerciseCount: plan.exercises.length,
  };
}

export function workoutDetailsFromPlan(plan: WorkoutPlan): WorkoutDetailsData {
  return {
    id: plan.id,
    title: plan.name,
    description: plan.description,
    exercises: plan.exercises.map((entry) => ({
      id: entry.id,
      order: entry.exercise_order,
      section: entry.section,
      name: entry.exercise.name,
      sets: entry.sets,
      reps: entry.reps,
      durationSeconds: entry.duration_seconds,
      weightKg: entry.weight_kg,
      restSeconds: entry.rest_seconds,
      notes: entry.notes,
      instructions: entry.exercise.instructions,
      description: entry.exercise.description,
    })),
  };
}
