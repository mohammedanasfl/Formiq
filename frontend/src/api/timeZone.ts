// The device's time zone as the coach needs it (Phase 2.7): the IANA name ("Asia/Kolkata") that its clock runs in. The coach's
// "today" and "tomorrow" are the user's own days in it (backend/app/tools/coach_calendar.py); without it the backend uses the
// UTC day and tells the coach so. The name is sent only if it has the shape of one: anything else is left out, because the
// backend refuses a name that is not a zone of its database, and a coach that cannot be asked is worse than UTC dates.
const IANA_NAME = /^[A-Za-z0-9_+\-/]{1,64}$/;

export function deviceTimeZone(): string | undefined {
  try {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return typeof zone === 'string' && IANA_NAME.test(zone) ? zone : undefined;
  } catch {
    return undefined;
  }
}
