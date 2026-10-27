// The choices the onboarding offers, and the exact values it sends to the backend.
//
// The profile's text fields are free text in the backend (backend/app/schemas/user_profile.py), so
// only the values it recognises are offered for the goal: backend/app/guidance/nutrition.py maps
// lose_weight, build_muscle and general_fitness to a goal; any other text counts as unrecognised and
// loses goal-specific guidance. `beginner` is the one experience the backend reads
// (backend/app/tools/completeness.py). Gender, activity level and location are plain text there and
// no code branches on them: these values follow the ones the backend's own tests use.

export type Option<Value extends string> = {
  value: Value;
  title: string;
  description?: string;
};

export const GOAL_OPTIONS = [
  {
    value: 'build_muscle',
    title: 'Build Muscle',
    description: 'Gain strength and build lean muscle mass.',
  },
  {
    value: 'lose_weight',
    title: 'Lose Weight',
    description: 'Reduce body fat and get leaner.',
  },
  {
    value: 'general_fitness',
    title: 'Improve Fitness',
    description: 'Improve endurance and overall fitness.',
  },
] as const satisfies readonly Option<string>[];
export type GoalValue = (typeof GOAL_OPTIONS)[number]['value'];

export const GENDER_OPTIONS = [
  { value: 'male', title: 'Male' },
  { value: 'female', title: 'Female' },
  { value: 'other', title: 'Other' },
] as const satisfies readonly Option<string>[];
export type GenderValue = (typeof GENDER_OPTIONS)[number]['value'];

export const EXPERIENCE_OPTIONS = [
  {
    value: 'beginner',
    title: 'Beginner',
    description: 'New to training, or coming back after a long break',
  },
  {
    value: 'intermediate',
    title: 'Intermediate',
    description: 'You train regularly and know most exercises',
  },
  { value: 'advanced', title: 'Advanced', description: 'Years of consistent training' },
] as const satisfies readonly Option<string>[];
export type ExperienceValue = (typeof EXPERIENCE_OPTIONS)[number]['value'];

export const ACTIVITY_OPTIONS = [
  { value: 'sedentary', title: 'Sedentary' },
  { value: 'light', title: 'Light' },
  { value: 'moderate', title: 'Moderate' },
  { value: 'very_active', title: 'Very active' },
] as const satisfies readonly Option<string>[];
export type ActivityValue = (typeof ACTIVITY_OPTIONS)[number]['value'];

export const LOCATION_OPTIONS = [
  {
    value: 'gym',
    title: 'Gym',
    description: 'You can use a gym: machines, barbells, dumbbells and more',
  },
  {
    value: 'home',
    title: 'Home',
    description: 'You train at home with your body weight and the equipment you own',
  },
] as const satisfies readonly Option<string>[];
export type LocationValue = (typeof LOCATION_OPTIONS)[number]['value'];

export const TRAINING_DAY_OPTIONS = [1, 2, 3, 4, 5, 6, 7] as const;

// The text shown for a stored value.
export function titleOf<Value extends string>(
  options: readonly Option<Value>[],
  value: Value | null,
): string {
  return options.find((option) => option.value === value)?.title ?? '';
}
