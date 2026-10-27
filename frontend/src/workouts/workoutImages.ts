import type { ImageSourcePropType } from 'react-native';

import { primaryCategory, WORKOUT_CATEGORY_LABELS, type WorkoutCategory } from './categories';
import type { ImageFraming } from './framing';

// The one place that decides which picture a workout gets. Everything else asks `resolveWorkoutVisual`.
//
// The backend sends no image or image identifier for a workout (nothing like it in
// backend/app/schemas/workout_plan.py), so there is no server picture to prefer: the pictures are local.
// If the backend ever supplies one, it goes ahead of this lookup, not into it.

// The eight photos, named by their files in assets/images/workouts/.
export type WorkoutImageKey =
  | 'core-abs'
  | 'upper-body'
  | 'lower-body'
  | 'full-body'
  | 'cardio-hiit'
  | 'mobility'
  | 'recovery-stretch'
  | 'beginner';

// The files each key expects. Used by the test that notices a photo added to the folder but not
// registered below.
export const WORKOUT_IMAGE_FILES: Record<WorkoutImageKey, string> = {
  'core-abs': 'core-abs.png',
  'upper-body': 'upper-body.png',
  'lower-body': 'lower-body.png',
  'full-body': 'full-body.png',
  'cardio-hiit': 'cardio-hiit.png',
  mobility: 'mobility.png',
  'recovery-stretch': 'recovery-stretch.png',
  beginner: 'beginner.png',
};

// What the card needs to know to frame each photo: the file's size in pixels (a test checks it against
// the files) and how far across it the subject is, from 0 at the left edge to 1 at the right. The files
// are wide strips and the card shows only about a third to a half of them, so the card keeps that point
// in view, to the right of the text, instead of cropping the middle and cutting a head off.
export type WorkoutImageFraming = ImageFraming;

export const WORKOUT_IMAGE_FRAMING: Record<WorkoutImageKey, WorkoutImageFraming> = {
  'core-abs': { width: 737, height: 215, focus: 0.57 },
  'upper-body': { width: 739, height: 215, focus: 0.64 },
  'lower-body': { width: 737, height: 184, focus: 0.51 },
  'full-body': { width: 739, height: 184, focus: 0.53 },
  'cardio-hiit': { width: 733, height: 154, focus: 0.52 },
  mobility: { width: 735, height: 154, focus: 0.66 },
  'recovery-stretch': { width: 733, height: 138, focus: 0.62 },
  beginner: { width: 735, height: 138, focus: 0.60 },
};

// Which photo shows a category. A Record over every category: a category added without a picture is a
// type error.
const CATEGORY_IMAGE: Record<WorkoutCategory, WorkoutImageKey> = {
  core: 'core-abs', // core, abs and plank-focused workouts
  'upper-body': 'upper-body', // chest, back, shoulders, biceps and triceps
  'lower-body': 'lower-body', // legs, glutes and squat-focused workouts
  'full-body': 'full-body', // full-body compound workouts
  cardio: 'cardio-hiit', // cardio, running and interval training
  mobility: 'mobility', // mobility and flexibility
  recovery: 'recovery-stretch', // cool-downs, stretching and recovery
  beginner: 'beginner', // beginner-focused workouts whose kind is not otherwise known
};

// The photos that are bundled. Metro needs each `require` written out, so a photo is registered by
// adding its line here once its file is in assets/images/workouts/. A key without a bundled photo shows
// the neutral picture below, so a photo can be added or replaced on its own.
export const WORKOUT_IMAGES: Partial<Record<WorkoutImageKey, ImageSourcePropType>> = {
  'core-abs': require('../../assets/images/workouts/core-abs.png'),
  'upper-body': require('../../assets/images/workouts/upper-body.png'),
  'lower-body': require('../../assets/images/workouts/lower-body.png'),
  'full-body': require('../../assets/images/workouts/full-body.png'),
  'cardio-hiit': require('../../assets/images/workouts/cardio-hiit.png'),
  mobility: require('../../assets/images/workouts/mobility.png'),
  'recovery-stretch': require('../../assets/images/workouts/recovery-stretch.png'),
  beginner: require('../../assets/images/workouts/beginner.png'),
};

// The neutral picture for a workout of unknown kind, or whose photo is not bundled: the same dark gym
// as the rest of the app, with nobody in it, so it suggests no kind of exercise.
export const WORKOUT_FALLBACK_IMAGE: ImageSourcePropType = require('../../assets/images/signup-background.png');

export type WorkoutVisual = {
  // the category the workout is shown as; null when it has no known one
  category: WorkoutCategory | null;
  // the small heading for it; null when there is no category: nothing is made up
  label: string | null;
  // which photo the category calls for; null when there is no category
  imageKey: WorkoutImageKey | null;
  // what to draw: the photo, or the neutral picture
  source: ImageSourcePropType;
  // how to frame the photo; null for the neutral picture, which is simply cropped to fit
  framing: WorkoutImageFraming | null;
  // true when `source` is the neutral picture (no category, or its photo is not bundled)
  isFallback: boolean;
};

export function workoutImageKey(category: WorkoutCategory): WorkoutImageKey {
  return CATEGORY_IMAGE[category];
}

export function resolveWorkoutVisual(workout: {
  categories?: readonly WorkoutCategory[] | null;
}): WorkoutVisual {
  const category = primaryCategory(workout.categories);
  if (!category) {
    return {
      category: null,
      label: null,
      imageKey: null,
      source: WORKOUT_FALLBACK_IMAGE,
      framing: null,
      isFallback: true,
    };
  }
  const imageKey = CATEGORY_IMAGE[category];
  const photo = WORKOUT_IMAGES[imageKey];
  return {
    category,
    label: WORKOUT_CATEGORY_LABELS[category],
    imageKey,
    source: photo ?? WORKOUT_FALLBACK_IMAGE,
    framing: photo === undefined ? null : WORKOUT_IMAGE_FRAMING[imageKey],
    isFallback: photo === undefined,
  };
}
