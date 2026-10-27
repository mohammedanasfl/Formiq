import { localDateKey, MONTHS, WEEKDAYS } from '../home/format';

const DAY_KEY = /^(\d{4})-(\d{2})-(\d{2})$/;

// "Thu, 22 Oct" for "2026-10-22": a calendar day as the backend names a plan's day (no time zone), so it reads the
// same wherever the device is. Null when the text is not a real day: it is left out, never replaced by a made-up one.
export function formatDay(key: string): string | null {
  const match = DAY_KEY.exec(key);
  if (!match) return null;
  const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const date = new Date(Date.UTC(year, month - 1, day));
  if (date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return null;
  return `${WEEKDAYS[date.getUTCDay()]}, ${day} ${MONTHS[month - 1]}`;
}

// "Today" or "Tomorrow" for those days in the device's own time zone (the same "today" Home asks the backend for),
// and the day written out otherwise. Null when the text is not a real day.
export function dayLabel(key: string, now: Date): string | null {
  if (formatDay(key) === null) return null;
  if (key === localDateKey(now)) return 'Today';
  const tomorrow = new Date(now);
  tomorrow.setDate(tomorrow.getDate() + 1);
  return key === localDateKey(tomorrow) ? 'Tomorrow' : formatDay(key);
}

const MINUTE_MS = 60_000;

// How long ago something was, for a proposal fetched from before the conversation: "just now", "12 min ago",
// "1 h 5 min ago", "3 h ago". Null when the time cannot be read, so nothing is said rather than a made-up age.
export function agoLabel(iso: string, now: Date): string | null {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return null;
  const minutes = Math.max(0, Math.floor((now.getTime() - then) / MINUTE_MS));
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest === 0 ? `${hours} h ago` : `${hours} h ${rest} min ago`;
}

// How long a proposal still waits for the person: "in 18 min", "in less than a minute", "now" once it has passed (the
// backend is the authority: it refuses an approval after that). Null when the time cannot be read.
export function expiresLabel(iso: string, now: Date): string | null {
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return null;
  const left = at - now.getTime();
  if (left <= 0) return 'now';
  const minutes = Math.ceil(left / MINUTE_MS);
  return minutes <= 1 ? 'in less than a minute' : `in ${minutes} min`;
}
