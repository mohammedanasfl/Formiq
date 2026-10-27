// Written out by hand, not with Intl: the same words on every device and in the tests.
export const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
export const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

// "Tue, 20 Oct 2026", in the device's own time zone.
export function formatLongDate(date: Date): string {
  return `${WEEKDAYS[date.getDay()]}, ${date.getDate()} ${MONTHS[date.getMonth()]} ${date.getFullYear()}`;
}

// "9:30 am", "6:05 pm", "12:00 pm" (noon) and "12:00 am" (midnight), in the device's own time zone.
export function formatClock(date: Date): string {
  const hour = date.getHours();
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${hour % 12 === 0 ? 12 : hour % 12}:${minutes} ${hour < 12 ? 'am' : 'pm'}`;
}

// "2026-10-20": the calendar day of a moment in the device's own time zone, the form the backend names a
// plan's day in (its scheduled_date has no time zone).
export function localDateKey(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${date.getFullYear()}-${month}-${day}`;
}

// When something happened, for a line of text: "today at 9:30 am" if it was on the same day as `now`, the date
// ("Mon, 19 Oct 2026") if it was on another, both in the device's own time zone. Null when `iso` is not a time:
// a time that cannot be read is left out, never replaced by a made-up one.
export function formatWhen(iso: string, now: Date): string | null {
  const moment = new Date(iso);
  if (Number.isNaN(moment.getTime())) return null;
  return localDateKey(moment) === localDateKey(now)
    ? `today at ${formatClock(moment)}`
    : formatLongDate(moment);
}

// "Good morning" from 05:00, "Good afternoon" from 12:00, "Good evening" from 17:00, in the device's own time
// zone. The small hours count as evening: nobody wants "Good morning" at 02:00.
export function timeOfDayGreeting(date: Date): string {
  const hour = date.getHours();
  if (hour >= 5 && hour < 12) return 'Good morning';
  if (hour >= 12 && hour < 17) return 'Good afternoon';
  return 'Good evening';
}

// The greeting with the name after a comma, or alone when there is no name to use: a missing or blank name
// is left out, never filled in.
export function greetingText(date: Date, name?: string | null): string {
  const greeting = timeOfDayGreeting(date);
  const trimmed = name?.trim();
  return trimmed ? `${greeting}, ${trimmed}` : greeting;
}

// 1850 -> "1,850"
export function formatThousands(value: number): string {
  return String(Math.round(value)).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

// 0.6 -> "60%"
export function formatPercent(share: number): string {
  return `${Math.round(Math.min(1, Math.max(0, share)) * 100)}%`;
}
