import {
  exerciseImage,
  EXERCISE_IMAGE_FILES,
  EXERCISE_IMAGE_FRAMING,
  EXERCISE_IMAGES,
  isExerciseImageKey,
  type ExerciseImageKey,
} from '../src/workouts/exerciseImages';

const KEYS = Object.keys(EXERCISE_IMAGE_FILES) as ExerciseImageKey[];
// the test reads the folder with Node's own fs; the project does not load Node's types, so it is typed here
const { existsSync, readdirSync, readFileSync } = jest.requireActual('fs') as {
  existsSync: (path: string) => boolean;
  readdirSync: (path: string) => string[];
  readFileSync: (path: string) => { readUInt32BE: (offset: number) => number; subarray: (a: number, b: number) => { toString: (encoding: string) => string } };
};
const PHOTO_DIR = `${process.cwd()}/assets/images/exercises`;

describe('the exercise pictures', () => {
  test('are the fifteen the design supplied, by their own file names', () => {
    expect(EXERCISE_IMAGE_FILES).toEqual({
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
    });
    expect(KEYS).toHaveLength(15);
  });

  test('every key has a bundled picture, framing and file, and no two keys share a picture', () => {
    expect(Object.keys(EXERCISE_IMAGES).sort()).toEqual([...KEYS].sort());
    expect(Object.keys(EXERCISE_IMAGE_FRAMING).sort()).toEqual([...KEYS].sort());
    for (const key of KEYS) expect(EXERCISE_IMAGES[key]).toBeDefined();
    expect(new Set(KEYS.map((key) => EXERCISE_IMAGES[key])).size).toBe(KEYS.length);
  });

  test('every key has a file in assets/images/exercises, and the folder holds those fifteen and nothing else', () => {
    expect(existsSync(PHOTO_DIR)).toBe(true);
    const present = readdirSync(PHOTO_DIR);

    for (const key of KEYS) expect(present).toContain(EXERCISE_IMAGE_FILES[key]);
    expect([...present].sort()).toEqual(Object.values(EXERCISE_IMAGE_FILES).sort());
  });

  describe('the files', () => {
    const PNG_SIGNATURE = '\u0089PNG\r\n\u001a\n';

    test.each(KEYS.map((key) => [key]))('%s is a real PNG of the size the framing says it is', (key) => {
      const file = readFileSync(`${PHOTO_DIR}/${EXERCISE_IMAGE_FILES[key]}`);

      expect(file.subarray(0, 8).toString('latin1')).toBe(PNG_SIGNATURE);
      expect(file.subarray(12, 16).toString('latin1')).toBe('IHDR');
      expect({ width: file.readUInt32BE(16), height: file.readUInt32BE(20) }).toEqual({
        width: EXERCISE_IMAGE_FRAMING[key].width,
        height: EXERCISE_IMAGE_FRAMING[key].height,
      });
    });

    test('every picture is a wide strip, the shape the thumbnail frames', () => {
      for (const key of KEYS) {
        const { width, height } = EXERCISE_IMAGE_FRAMING[key];
        expect(width / height).toBeGreaterThan(2);
      }
    });

    test("each picture's subject point lies inside it, with room for the thumbnail to show it either side", () => {
      // the thumbnail also holds the picture back from either edge (framedImageStyleInBox), so this only
      // keeps the point somewhere a thumbnail can centre on it
      for (const key of KEYS) {
        expect(EXERCISE_IMAGE_FRAMING[key].focus).toBeGreaterThan(0.3);
        expect(EXERCISE_IMAGE_FRAMING[key].focus).toBeLessThan(0.7);
      }
    });
  });
});

describe('exerciseImage', () => {
  test.each(KEYS.map((key) => [key]))('%s gives its picture and its framing', (key) => {
    expect(exerciseImage(key)).toEqual({ source: EXERCISE_IMAGES[key], framing: EXERCISE_IMAGE_FRAMING[key] });
  });

  test.each([
    ['a key the app has no picture for', 'burpees'],
    ['an empty key', ''],
    ['null', null],
    ['undefined', undefined],
    ['a name from the object prototype', 'toString'],
  ])('%s gives nothing: no picture is borrowed from another exercise', (_name, key) => {
    expect(exerciseImage(key)).toBeNull();
  });

  test('isExerciseImageKey tells the fifteen from anything else', () => {
    for (const key of KEYS) expect(isExerciseImageKey(key)).toBe(true);
    for (const value of ['burpees', 'constructor', '', 7, null, undefined, {}]) expect(isExerciseImageKey(value)).toBe(false);
  });
});
