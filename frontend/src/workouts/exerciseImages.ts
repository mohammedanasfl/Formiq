import type { ImageSourcePropType } from 'react-native';

import type { ImageFraming } from './framing';

// The pictures of exercises, for the design phase. They are local files: the backend's catalog serves its
// own images for an imported exercise (ExerciseResponse.images: a path such as /exercises/{id}/images/0),
// but a workout plan carries none (PlannedExerciseDetailsResponse has a name, a description and the
// steps), and these fifteen are the development set the design was drawn with. A real exercise's picture
// goes ahead of this lookup, as a `{ uri }` source, not into it.

// The fifteen pictures, named by their files in assets/images/exercises/.
export type ExerciseImageKey =
  | 'plank'
  | 'bicycle-crunches'
  | 'leg-raises'
  | 'russian-twists'
  | 'push-ups'
  | 'dumbbell-rows'
  | 'squats'
  | 'lunges'
  | 'shoulder-press'
  | 'bicep-curls'
  | 'tricep-dips'
  | 'mountain-climbers'
  | 'hamstring-stretch'
  | 'quad-stretch'
  | 'childs-pose';

// The file each key expects, so a test can notice a picture added to the folder and not registered.
export const EXERCISE_IMAGE_FILES: Record<ExerciseImageKey, string> = {
  plank: 'plank.png',
  'bicycle-crunches': 'bicycle-crunches.png',
  'leg-raises': 'leg-raises.png',
  'russian-twists': 'russian-twists.png',
  'push-ups': 'push-ups.png',
  'dumbbell-rows': 'dumbbell-rows.png',
  squats: 'squats.png',
  lunges: 'lunges.png',
  'shoulder-press': 'shoulder-press.png',
  'bicep-curls': 'bicep-curls.png',
  'tricep-dips': 'tricep-dips.png',
  'mountain-climbers': 'mountain-climbers.png',
  'hamstring-stretch': 'hamstring-stretch.png',
  'quad-stretch': 'quad-stretch.png',
  'childs-pose': 'childs-pose.png',
};

// Each file's size in pixels (a test checks it against the files) and how far across it the athlete is,
// from 0 at the left edge to 1 at the right. The files are wide strips and a thumbnail shows about half of
// one, so the thumbnail keeps that point in view. The files were trimmed of a dark border band on one or
// two sides (the sizes are those of the trimmed files; the supplied ZIP keeps the originals).
export const EXERCISE_IMAGE_FRAMING: Record<ExerciseImageKey, ImageFraming> = {
  plank: { width: 324, height: 138, focus: 0.45 },
  'bicycle-crunches': { width: 333, height: 138, focus: 0.58 },
  'leg-raises': { width: 315, height: 138, focus: 0.43 },
  'russian-twists': { width: 321, height: 129, focus: 0.5 },
  'push-ups': { width: 333, height: 129, focus: 0.45 },
  'dumbbell-rows': { width: 315, height: 129, focus: 0.62 },
  squats: { width: 321, height: 140, focus: 0.51 },
  lunges: { width: 333, height: 140, focus: 0.53 },
  'shoulder-press': { width: 316, height: 140, focus: 0.47 },
  'bicep-curls': { width: 323, height: 133, focus: 0.5 },
  'tricep-dips': { width: 333, height: 133, focus: 0.55 },
  'mountain-climbers': { width: 316, height: 133, focus: 0.5 },
  'hamstring-stretch': { width: 323, height: 132, focus: 0.51 },
  'quad-stretch': { width: 333, height: 133, focus: 0.51 },
  'childs-pose': { width: 316, height: 132, focus: 0.58 },
};

// The bundled pictures. Metro needs each `require` written out. A Record over every key: a key without a
// picture is a type error.
export const EXERCISE_IMAGES: Record<ExerciseImageKey, ImageSourcePropType> = {
  plank: require('../../assets/images/exercises/plank.png'),
  'bicycle-crunches': require('../../assets/images/exercises/bicycle-crunches.png'),
  'leg-raises': require('../../assets/images/exercises/leg-raises.png'),
  'russian-twists': require('../../assets/images/exercises/russian-twists.png'),
  'push-ups': require('../../assets/images/exercises/push-ups.png'),
  'dumbbell-rows': require('../../assets/images/exercises/dumbbell-rows.png'),
  squats: require('../../assets/images/exercises/squats.png'),
  lunges: require('../../assets/images/exercises/lunges.png'),
  'shoulder-press': require('../../assets/images/exercises/shoulder-press.png'),
  'bicep-curls': require('../../assets/images/exercises/bicep-curls.png'),
  'tricep-dips': require('../../assets/images/exercises/tricep-dips.png'),
  'mountain-climbers': require('../../assets/images/exercises/mountain-climbers.png'),
  'hamstring-stretch': require('../../assets/images/exercises/hamstring-stretch.png'),
  'quad-stretch': require('../../assets/images/exercises/quad-stretch.png'),
  'childs-pose': require('../../assets/images/exercises/childs-pose.png'),
};

// What an exercise row draws: a picture and how to frame it. `framing` is null for a picture that is
// simply cropped to fill its box (any picture that is not one of the fifteen).
export type ExerciseImage = {
  source: ImageSourcePropType;
  framing: ImageFraming | null;
};

export function isExerciseImageKey(value: unknown): value is ExerciseImageKey {
  return typeof value === 'string' && Object.prototype.hasOwnProperty.call(EXERCISE_IMAGE_FILES, value);
}

// The picture for one of the fifteen keys, or null for a key this app has no picture for (a row without a
// picture shows its placeholder: nothing is borrowed from another exercise).
export function exerciseImage(key: string | null | undefined): ExerciseImage | null {
  if (!isExerciseImageKey(key)) return null;
  return { source: EXERCISE_IMAGES[key], framing: EXERCISE_IMAGE_FRAMING[key] };
}
