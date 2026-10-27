// The looping animations of exercises, for the design phase. They are local files supplied with the design
// (assets/images/exercise-gifs/, with the README that came with them): six simple stylized illustrations
// made for UI integration and animation testing, which the README itself says are NOT instructional or
// reference-quality demonstrations, so every one of them is marked `placeholder` and the screen says so. The
// backend's catalog serves no animation at all (ExerciseResponse.images are still pictures, and none are
// imported), so a real animation, when there is one, goes ahead of this lookup as a `{ uri }` source, not
// into it.
//
// An exercise is matched to its animation by the stable key written on it (`animation`, below), never by its
// name: the key is what a mapper from the catalog will set, from the exercise's id, once real media exists.

// The six animations, named by their files.
export type ExerciseGifKey = 'plank' | 'squat' | 'push-up' | 'sit-up' | 'jumping-jack' | 'lunge';

// The file each key expects, so a test can notice an animation added to the folder and not registered.
export const EXERCISE_GIF_FILES: Record<ExerciseGifKey, string> = {
  plank: 'plank.gif',
  squat: 'squat.gif',
  'push-up': 'push-up.gif',
  'sit-up': 'sit-up.gif',
  'jumping-jack': 'jumping-jack.gif',
  lunge: 'lunge.gif',
};

// Every file is 480 x 270 (16 : 9), a test checks it: the animation area is drawn in that shape.
export const EXERCISE_GIF_SIZE = { width: 480, height: 270 } as const;

// The bundled animations. Metro needs each `require` written out. A Record over every key: a key without a
// file is a type error.
export const EXERCISE_GIFS: Record<ExerciseGifKey, GifSource> = {
  plank: require('../../assets/images/exercise-gifs/plank.gif'),
  squat: require('../../assets/images/exercise-gifs/squat.gif'),
  'push-up': require('../../assets/images/exercise-gifs/push-up.gif'),
  'sit-up': require('../../assets/images/exercise-gifs/sit-up.gif'),
  'jumping-jack': require('../../assets/images/exercise-gifs/jumping-jack.gif'),
  lunge: require('../../assets/images/exercise-gifs/lunge.gif'),
};

// A bundled file (what `require` gives) or a web address
export type GifSource = number | { uri: string };

// What the animation area plays.
export type ExerciseGif = {
  source: GifSource;
  // true for the development set above: the screen labels it as a placeholder. False for real exercise media.
  placeholder: boolean;
};

export function isExerciseGifKey(value: unknown): value is ExerciseGifKey {
  return typeof value === 'string' && Object.prototype.hasOwnProperty.call(EXERCISE_GIF_FILES, value);
}

// The animation for one of the six keys, or null for a key this app has none for (the screen then shows the
// exercise's still picture or its placeholder, and says there is no animation: nothing is borrowed from
// another exercise).
export function exerciseGif(key: string | null | undefined): ExerciseGif | null {
  if (!isExerciseGifKey(key)) return null;
  return { source: EXERCISE_GIFS[key], placeholder: true };
}
