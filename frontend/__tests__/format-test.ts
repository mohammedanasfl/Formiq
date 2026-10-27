import {
  formatClock,
  formatLongDate,
  formatPercent,
  formatThousands,
  formatWhen,
  greetingText,
  localDateKey,
  timeOfDayGreeting,
} from '../src/home/format';

describe('formatLongDate', () => {
  test('writes the weekday, the day, the month and the year, as the design shows', () => {
    expect(formatLongDate(new Date(2026, 9, 20))).toBe('Tue, 20 Oct 2026');
    expect(formatLongDate(new Date(2026, 9, 14))).toBe('Wed, 14 Oct 2026');
  });

  test('does not pad the day, and gets the ends of the year and of the week right', () => {
    expect(formatLongDate(new Date(2027, 0, 1))).toBe('Fri, 1 Jan 2027');
    expect(formatLongDate(new Date(2026, 11, 31))).toBe('Thu, 31 Dec 2026');
    expect(formatLongDate(new Date(2026, 9, 18))).toBe('Sun, 18 Oct 2026');
    expect(formatLongDate(new Date(2026, 9, 17))).toBe('Sat, 17 Oct 2026');
  });

  test('uses the device\'s own calendar day, whatever the time of day', () => {
    expect(formatLongDate(new Date(2026, 9, 20, 0, 5))).toBe('Tue, 20 Oct 2026');
    expect(formatLongDate(new Date(2026, 9, 20, 23, 55))).toBe('Tue, 20 Oct 2026');
  });
});

describe('formatThousands', () => {
  test.each([
    [0, '0'],
    [999, '999'],
    [1000, '1,000'],
    [1850, '1,850'],
    [1234567, '1,234,567'],
  ])('%d is written %s', (value, written) => {
    expect(formatThousands(value)).toBe(written);
  });

  test('rounds to a whole number', () => {
    expect(formatThousands(1849.6)).toBe('1,850');
  });
});

describe('formatPercent', () => {
  test.each([
    [0, '0%'],
    [0.6, '60%'],
    [0.666, '67%'],
    [1, '100%'],
  ])('%d is written %s', (share, written) => {
    expect(formatPercent(share)).toBe(written);
  });

  test('holds a share outside 0 to 1 to the ends', () => {
    expect(formatPercent(-0.2)).toBe('0%');
    expect(formatPercent(1.4)).toBe('100%');
  });
});

describe('timeOfDayGreeting', () => {
  const at = (hour: number, minute = 0) => new Date(2026, 9, 20, hour, minute);

  test.each([
    [5, 0, 'Good morning'],
    [11, 59, 'Good morning'],
    [12, 0, 'Good afternoon'],
    [16, 59, 'Good afternoon'],
    [17, 0, 'Good evening'],
    [21, 30, 'Good evening'],
    [0, 0, 'Good evening'],
    [4, 59, 'Good evening'],
  ])('at %i:%i it is "%s"', (hour, minute, expected) => {
    expect(timeOfDayGreeting(at(hour, minute))).toBe(expected);
  });
});

describe('greetingText', () => {
  const morning = new Date(2026, 9, 20, 8);

  test('puts the name after a comma', () => {
    expect(greetingText(morning, 'Anas')).toBe('Good morning, Anas');
  });

  test.each([[undefined], [null], [''], ['   ']])('leaves a missing or blank name (%p) out, with no comma', (name) => {
    expect(greetingText(morning, name)).toBe('Good morning');
  });

  test('trims the name', () => {
    expect(greetingText(morning, '  Priya ')).toBe('Good morning, Priya');
  });
});

describe('formatClock', () => {
  test.each([
    [new Date(2026, 9, 20, 9, 30), '9:30 am'],
    [new Date(2026, 9, 20, 18, 5), '6:05 pm'],
    [new Date(2026, 9, 20, 0, 0), '12:00 am'],
    [new Date(2026, 9, 20, 0, 59), '12:59 am'],
    [new Date(2026, 9, 20, 12, 0), '12:00 pm'],
    [new Date(2026, 9, 20, 12, 1), '12:01 pm'],
    [new Date(2026, 9, 20, 13, 0), '1:00 pm'],
    [new Date(2026, 9, 20, 23, 59), '11:59 pm'],
  ])('%s is %s, on the 12-hour clock with no padded hour', (date, text) => {
    expect(formatClock(date)).toBe(text);
  });
});

describe('localDateKey', () => {
  test('is the device\'s own calendar day as YYYY-MM-DD, with the month and day padded', () => {
    expect(localDateKey(new Date(2026, 9, 20, 9, 30))).toBe('2026-10-20');
    expect(localDateKey(new Date(2027, 0, 5))).toBe('2027-01-05');
  });

  test('does not move with the time of day: the first and the last minute are the same day', () => {
    expect(localDateKey(new Date(2026, 9, 20, 0, 0))).toBe('2026-10-20');
    expect(localDateKey(new Date(2026, 9, 20, 23, 59))).toBe('2026-10-20');
    expect(localDateKey(new Date(2026, 9, 21, 0, 0))).toBe('2026-10-21');
  });

  test('gets the ends of a month and of the year right', () => {
    expect(localDateKey(new Date(2026, 11, 31, 23, 59))).toBe('2026-12-31');
    expect(localDateKey(new Date(2027, 0, 1, 0, 0))).toBe('2027-01-01');
  });
});

describe('formatWhen', () => {
  const now = new Date(2026, 9, 20, 18, 0);

  test('says "today at" and the time for a moment on the same day', () => {
    expect(formatWhen(new Date(2026, 9, 20, 9, 30).toISOString(), now)).toBe('today at 9:30 am');
    expect(formatWhen(new Date(2026, 9, 20, 0, 5).toISOString(), now)).toBe('today at 12:05 am');
  });

  test('gives the date for a moment on another day, earlier or later', () => {
    expect(formatWhen(new Date(2026, 9, 19, 23, 50).toISOString(), now)).toBe('Mon, 19 Oct 2026');
    expect(formatWhen(new Date(2026, 9, 21, 0, 10).toISOString(), now)).toBe('Wed, 21 Oct 2026');
  });

  test('is null for text that is not a time: a time that cannot be read is not replaced by a made-up one', () => {
    expect(formatWhen('earlier today', now)).toBeNull();
    expect(formatWhen('', now)).toBeNull();
  });
});
