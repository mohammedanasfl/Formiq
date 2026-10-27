import {
  exerciseGif,
  EXERCISE_GIF_FILES,
  EXERCISE_GIF_SIZE,
  EXERCISE_GIFS,
  isExerciseGifKey,
  type ExerciseGifKey,
} from '../src/workouts/exerciseGifs';

const KEYS = Object.keys(EXERCISE_GIF_FILES) as ExerciseGifKey[];
// the test reads the folder with Node's own fs; the project does not load Node's types, so it is typed here
type Bytes = { length: number; [index: number]: number; subarray: (a: number, b: number) => { toString: (encoding: string) => string } };
const { existsSync, readdirSync, readFileSync } = jest.requireActual('fs') as {
  existsSync: (path: string) => boolean;
  readdirSync: (path: string) => string[];
  readFileSync: (path: string) => Bytes;
};
const GIF_DIR = `${process.cwd()}/assets/images/exercise-gifs`;

// What a GIF file says about itself, read from its blocks (https://www.w3.org/Graphics/GIF/spec-gif89a.txt):
// its size, how many frames it has, and whether it asks to loop forever (the NETSCAPE2.0 extension, loop 0).
function describeGif(file: Bytes) {
  const word = (at: number) => file[at] | (file[at + 1] << 8);
  const width = word(6);
  const height = word(8);
  let at = 13;
  if (file[10] & 0x80) at += 3 * 2 ** ((file[10] & 7) + 1);
  let frames = 0;
  let loopsForever = false;
  while (at < file.length && file[at] !== 0x3b) {
    if (file[at] === 0x21) {
      const label = file[at + 1];
      const isLoop = label === 0xff && file.subarray(at + 3, at + 14).toString('latin1') === 'NETSCAPE2.0';
      if (isLoop) loopsForever = word(at + 16) === 0;
      at += 2;
    } else if (file[at] === 0x2c) {
      frames += 1;
      const flags = file[at + 9];
      at += 10;
      if (flags & 0x80) at += 3 * 2 ** ((flags & 7) + 1);
      at += 1; // the LZW minimum code size
    } else {
      throw new Error(`unexpected block 0x${file[at].toString(16)} at ${at}`);
    }
    while (file[at] !== 0) at += file[at] + 1; // the data sub-blocks
    at += 1;
  }
  return { width, height, frames, loopsForever, signature: file.subarray(0, 6).toString('latin1') };
}

describe('the exercise animations', () => {
  test('are the six the design supplied, by their own file names', () => {
    expect(EXERCISE_GIF_FILES).toEqual({
      plank: 'plank.gif',
      squat: 'squat.gif',
      'push-up': 'push-up.gif',
      'sit-up': 'sit-up.gif',
      'jumping-jack': 'jumping-jack.gif',
      lunge: 'lunge.gif',
    });
    expect(KEYS).toHaveLength(6);
  });

  test('every key has a bundled animation, and no two keys share one', () => {
    expect(Object.keys(EXERCISE_GIFS).sort()).toEqual([...KEYS].sort());
    expect(new Set(KEYS.map((key) => EXERCISE_GIFS[key])).size).toBe(KEYS.length);
  });

  test('every key has a file in assets/images/exercise-gifs, and the folder holds those six and the README that came with them', () => {
    expect(existsSync(GIF_DIR)).toBe(true);
    const present = readdirSync(GIF_DIR);

    for (const key of KEYS) expect(present).toContain(EXERCISE_GIF_FILES[key]);
    expect(present.filter((name) => name.endsWith('.gif')).sort()).toEqual(Object.values(EXERCISE_GIF_FILES).sort());
    expect(present.filter((name) => !name.endsWith('.gif'))).toEqual(['README.txt']);
  });

  describe('the files', () => {
    test.each(KEYS.map((key) => [key]))('%s is a real animated GIF that loops forever, in the shape the screen draws', (key) => {
      const gif = describeGif(readFileSync(`${GIF_DIR}/${EXERCISE_GIF_FILES[key]}`));

      expect(gif.signature).toBe('GIF89a');
      expect({ width: gif.width, height: gif.height }).toEqual(EXERCISE_GIF_SIZE);
      expect(gif.frames).toBeGreaterThan(1);
      expect(gif.loopsForever).toBe(true);
    });
  });
});

describe('exerciseGif', () => {
  test.each(KEYS.map((key) => [key]))('%s gives its animation, marked as a development placeholder', (key) => {
    expect(exerciseGif(key)).toEqual({ source: EXERCISE_GIFS[key], placeholder: true });
  });

  test.each([
    ['a key the app has no animation for', 'burpees'],
    ['the name of an exercise that has one: a name is not a key', 'Plank'],
    ['an empty key', ''],
    ['null', null],
    ['undefined', undefined],
    ['a name from the object prototype', 'toString'],
  ])('%s gives nothing: no animation is borrowed from another exercise', (_name, key) => {
    expect(exerciseGif(key)).toBeNull();
  });

  test('isExerciseGifKey tells the six from anything else', () => {
    for (const key of KEYS) expect(isExerciseGifKey(key)).toBe(true);
    for (const value of ['burpees', 'constructor', '', 7, null, undefined, {}]) expect(isExerciseGifKey(value)).toBe(false);
  });
});
