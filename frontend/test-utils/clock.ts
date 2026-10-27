// Fixes the clock a test reads (`new Date()`, `Date.now()`) and leaves every timer running: React's and the test
// library's timers must keep going, and so must the API client's request timeout.
const REAL_TIMERS = [
  'setTimeout',
  'clearTimeout',
  'setInterval',
  'clearInterval',
  'setImmediate',
  'clearImmediate',
  'nextTick',
  'queueMicrotask',
  'requestAnimationFrame',
  'cancelAnimationFrame',
  'requestIdleCallback',
  'cancelIdleCallback',
  'hrtime',
  'performance',
] as const;

export function fixClockAt(now: Date) {
  jest.useFakeTimers({ now, doNotFake: [...REAL_TIMERS] });
  return {
    // moves the clock, as time passing or the device's day changing would
    set: (next: Date) => jest.setSystemTime(next),
    restore: () => jest.useRealTimers(),
  };
}
