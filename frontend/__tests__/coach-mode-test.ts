// Which coach the tab talks to follows EXPO_PUBLIC_COACH_MODE, read once when the app is bundled.
function modeWith(value: string | undefined) {
  const before = process.env.EXPO_PUBLIC_COACH_MODE;
  if (value === undefined) delete process.env.EXPO_PUBLIC_COACH_MODE;
  else process.env.EXPO_PUBLIC_COACH_MODE = value;
  try {
    let mode = '';
    jest.isolateModules(() => {
      mode = require('../src/coach/mode').DEFAULT_COACH_MODE;
    });
    return mode;
  } finally {
    if (before === undefined) delete process.env.EXPO_PUBLIC_COACH_MODE;
    else process.env.EXPO_PUBLIC_COACH_MODE = before;
  }
}

describe('DEFAULT_COACH_MODE', () => {
  test('is the backend unless the mock is asked for by name', () => {
    expect(modeWith(undefined)).toBe('api');
    expect(modeWith('')).toBe('api');
    expect(modeWith('api')).toBe('api');
    expect(modeWith('MOCK ')).toBe('api');
    expect(modeWith('true')).toBe('api');
  });

  test('is the made-up coach for EXPO_PUBLIC_COACH_MODE=mock', () => {
    expect(modeWith('mock')).toBe('mock');
  });
});
