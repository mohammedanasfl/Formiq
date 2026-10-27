import type { PendingProposal } from '../api';
import { formatClock } from '../home/format';
import { dayLabel } from './days';

// Waiting workouts that carry the same name cannot be told apart by it. For those only, the list says what else the
// backend's own answer tells them apart by, and nothing that moves while the list is open: the day the workout is for
// (`scheduled_date`) and, for two of one name on the same day, the time it was proposed (`created_at`), to the second
// when two were proposed in the same minute. A workout with a name of its own gets no detail: it needs none.
// Names are compared as a person reads them: spaces around them and capitals do not make two names different.
const nameOf = (entry: PendingProposal) => entry.name.trim().toLowerCase();

// "9:12 am", or "9:12:07 am" when the seconds are needed to tell two apart. Null when the time cannot be read.
function proposedAt(iso: string, withSeconds: boolean): string | null {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return null;
  const clock = formatClock(at);
  return withSeconds ? clock.replace(/ (am|pm)$/, `:${String(at.getSeconds()).padStart(2, '0')} $1`) : clock;
}

// The detail line of each entry that needs one, by proposal id (an entry that needs none is not in it).
export function waitingDetails(entries: readonly PendingProposal[], now: Date): Map<string, string> {
  const details = new Map<string, string>();
  const groups = new Map<string, PendingProposal[]>();
  for (const entry of entries) groups.set(nameOf(entry), [...(groups.get(nameOf(entry)) ?? []), entry]);

  for (const group of groups.values()) {
    if (group.length < 2) continue;
    for (const entry of group) {
      const day = dayLabel(entry.scheduled_date, now);
      const parts: string[] = [];
      if (day) parts.push(`For ${day === 'Today' || day === 'Tomorrow' ? day.toLowerCase() : day}`);
      // another of this name on the same day: the day does not tell them apart
      const sameDay = group.filter((other) => other.scheduled_date === entry.scheduled_date);
      if (sameDay.length > 1) {
        const minute = proposedAt(entry.created_at, false);
        const sameMinute = sameDay.filter((other) => proposedAt(other.created_at, false) === minute).length > 1;
        const made = proposedAt(entry.created_at, sameMinute);
        if (made) parts.push(`Proposed at ${made}`);
      }
      if (parts.length > 0) details.set(entry.proposal_id, parts.join(' • '));
    }
  }
  return details;
}
