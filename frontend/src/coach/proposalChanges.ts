import type { PlanSectionName, Prescription, WorkoutProposal } from '../api';
import { formatDay } from './days';

// How the card WORDS what a proposal changes in the workout it replaces. The comparison itself is the backend's
// (`proposal.changes`, app/tools/comparison.py: the one the coach is held to): which exercises were added, removed or
// prescribed differently, and what the length and the day were. Nothing here decides what differs or reads the
// backend's `summary` sentences for logic; it only puts the backend's lists in the order a person reads a workout
// and says, for an exercise the backend lists as changed, which of its numbers moved.
//
// Nothing is guessed. A change is worded only if the backend listed it, the length is said to differ or to stay only
// when the backend gave both lengths, and when the backend could not compare (`changes` is null) there are no lines.
//
// What counts as a change: an exercise added, removed or prescribed differently (`added`, `removed`, `changed`), a new
// day (`scheduled_date_changed`) and a new name (`name_changed`). `identical` is NOT one of them and is never read to
// say that nothing changed: it means only that the exercises are prescribed alike, so a proposal that moves the workout
// to another day, or renames it, and keeps every exercise, arrives as `identical: true` and still has a change to show.

export type KeyChange =
  // one exercise of a section taken out and another put in its place (the backend lists a removal and an addition;
  // putting the two side by side is how the card words them)
  | { kind: 'replaced'; section: PlanSectionName; from: string; to: string }
  | { kind: 'added'; section: PlanSectionName; name: string }
  | { kind: 'removed'; section: PlanSectionName; name: string }
  // the same exercise, prescribed differently: `details` says what differs ("30 s → 40 s", "20 kg → no weight")
  | { kind: 'changed'; section: PlanSectionName; name: string; details: string[] }
  // only when both lengths are known: `before === after` is a verified "same length"
  | { kind: 'duration'; before: number; after: number }
  // `before` is null when the saved plan had no day
  | { kind: 'date'; before: string | null; after: string }
  // the proposal's name is not the saved plan's (`name_changed`)
  | { kind: 'renamed'; before: string; after: string };

export type Comparison = {
  changes: KeyChange[];
  // how each exercise of the proposal stands against the plan, by `${section}:${exercise name}`: the ones in no entry
  // are the same in both
  marks: Map<string, 'new' | 'changed'>;
};

const SECTION_ORDER: readonly PlanSectionName[] = ['WARM_UP', 'MAIN_WORKOUT', 'COOL_DOWN'];

// The proposal's exercise and the backend's change for it are one when the section and the name are the same: the
// backend writes the proposal's own name on an added or changed one.
export const markKey = (section: PlanSectionName, name: string) => `${section}:${name}`;

const isMinutes = (value: number | null | undefined): value is number =>
  typeof value === 'number' && Number.isInteger(value) && value >= 1;

const nameWords = (name: string) => name.toLowerCase().split(/[^\p{L}\p{N}]+/u).filter(Boolean);

// Whether the words of `inner` come one after another somewhere in `outer`.
const containsWords = (outer: string[], inner: string[]) =>
  inner.length > 0 && outer.some((_, start) => inner.every((word, offset) => outer[start + offset] === word));

// Whether a new name tells the reader something the card's title does not already: a different name, as against the
// same name in another case or spelling of its punctuation, or the old name with a word added or taken away
// ("Core & Abs Focus" to "Core & Abs Focus (Harder)" or "Shorter Core & Abs Focus"), which the coach does to almost every
// revision it makes. The backend says only that the name differs (`name_changed`), so this is the card's own judgement
// of whether to say it. The app is not told what the user asked, so a rename the user asked for is shown when it is a
// different name and left to the title when it only decorates the old one.
export function isMeaningfulRename(before: string, after: string): boolean {
  const was = nameWords(before);
  const now = nameWords(after);
  if (was.length === 0 || now.length === 0) return true;
  return !containsWords(now, was) && !containsWords(was, now);
}

const setsText = (sets: number) => `${sets} ${sets === 1 ? 'set' : 'sets'}`;
const targetText = (item: Prescription) => (item.reps !== null ? `${item.reps} reps` : `${item.duration_seconds ?? 0} s`);
const restText = (item: Prescription) => (item.rest_seconds ? `${item.rest_seconds} s rest` : 'no rest');
const weightText = (item: Prescription) => (item.weight_kg === null ? 'no weight' : `${item.weight_kg} kg`);

// Which of an exercise's numbers moved between the two prescriptions the backend gave, one entry each, in the order
// "3 sets → 4 sets", "30 s → 40 s", "45 s rest → 60 s rest", "20 kg → no weight". If none of them differs (the
// backend listed a change these numbers do not show) the backend's own one-line wording of both is shown, so a change
// it listed is never left out.
export function prescriptionDetails(before: Prescription, after: Prescription): string[] {
  const details: string[] = [];
  if (before.sets !== after.sets) details.push(`${setsText(before.sets)} → ${setsText(after.sets)}`);
  if (targetText(before) !== targetText(after)) details.push(`${targetText(before)} → ${targetText(after)}`);
  if ((before.rest_seconds || 0) !== (after.rest_seconds || 0)) details.push(`${restText(before)} → ${restText(after)}`);
  if (before.weight_kg !== after.weight_kg) details.push(`${weightText(before)} → ${weightText(after)}`);
  return details.length > 0 ? details : [`${before.summary} → ${after.summary}`];
}

// The differences the backend found between a proposal and the plan it replaces, in the order a person reads a
// workout: the warm-up, the main workout, the cool-down, and then the length and the day. Empty for a new workout and
// when the backend could not compare.
export function compareWithOriginal(proposal: WorkoutProposal): Comparison {
  const marks = new Map<string, 'new' | 'changed'>();
  const { changes } = proposal;
  if (changes === null) return { changes: [], marks };

  for (const item of changes.added) marks.set(markKey(item.section, item.exercise_name), 'new');
  for (const item of changes.changed) marks.set(markKey(item.section, item.exercise_name), 'changed');

  const lines: KeyChange[] = [];
  for (const section of SECTION_ORDER) {
    const gone = changes.removed.filter((item) => item.section === section);
    const came = changes.added.filter((item) => item.section === section);
    // the first taken out is the first put in its place: what is left over was added or removed on its own
    const pairs = Math.min(gone.length, came.length);
    for (let index = 0; index < pairs; index += 1) {
      lines.push({ kind: 'replaced', section, from: gone[index].exercise_name, to: came[index].exercise_name });
    }
    for (const item of came.slice(pairs)) lines.push({ kind: 'added', section, name: item.exercise_name });
    for (const item of gone.slice(pairs)) lines.push({ kind: 'removed', section, name: item.exercise_name });
    for (const item of changes.changed.filter((entry) => entry.section === section)) {
      const { before, after } = item;
      // a changed exercise has both sides (the reader refuses an answer where it does not)
      if (before && after) lines.push({ kind: 'changed', section, name: item.exercise_name, details: prescriptionDetails(before, after) });
    }
  }

  const before = proposal.revision?.replaces_plan_estimated_minutes;
  if (isMinutes(before) && isMinutes(proposal.estimated_minutes)) {
    lines.push({ kind: 'duration', before, after: proposal.estimated_minutes });
  }
  if (changes.scheduled_date_changed) {
    lines.push({ kind: 'date', before: changes.compared_with_scheduled_date, after: proposal.scheduled_date });
  }
  // last: the card's title already carries the new name, and what was done to the exercises is read first; a name that
  // only decorates the old one is not listed
  if (changes.name_changed && isMeaningfulRename(changes.compared_with_plan_name, proposal.name)) {
    lines.push({ kind: 'renamed', before: changes.compared_with_plan_name, after: proposal.name });
  }
  return { changes: lines, marks };
}

// Which of the changes the card lists when it has room for `max`: the first ones, in the order a person reads a
// workout, except that a change of day is always one of them. The day is listed after the exercises, so with more
// changes than room it would be the first to go, and a workout moved to another day must never hide behind "and N
// more". The indexes are in the changes' own order.
export function visibleChangeIndexes(changes: readonly KeyChange[], max: number): number[] {
  const all = changes.map((_, index) => index);
  if (changes.length <= max) return all;
  const days = all.filter((index) => changes[index].kind === 'date');
  const others = all.filter((index) => changes[index].kind !== 'date').slice(0, Math.max(max - days.length, 0));
  return [...others, ...days].sort((a, b) => a - b);
}

const SECTION_PLACE: Record<PlanSectionName, string> = {
  WARM_UP: 'the warm-up',
  MAIN_WORKOUT: 'the main workout',
  COOL_DOWN: 'the cool-down',
};

// One line of the Key Changes list.
export function keyChangeText(change: KeyChange): string {
  switch (change.kind) {
    case 'replaced':
      return `Replaced ${change.from} with ${change.to}${change.section === 'MAIN_WORKOUT' ? '' : ` in ${SECTION_PLACE[change.section]}`}`;
    case 'added':
      return `Added ${change.name} to ${SECTION_PLACE[change.section]}`;
    case 'removed':
      return `Removed ${change.name} from ${SECTION_PLACE[change.section]}`;
    case 'changed':
      return `${change.name}: ${change.details.join(', ')}`;
    case 'duration':
      return change.before === change.after
        ? `Kept the same duration (${change.after} min)`
        : `Duration changed from ${change.before} to ${change.after} min`;
    case 'date': {
      const after = formatDay(change.after) ?? change.after;
      if (change.before === null) return `Scheduled for ${after}`;
      return `Moved from ${formatDay(change.before) ?? change.before} to ${after}`;
    }
    case 'renamed':
      return `Renamed from “${change.before}” to “${change.after}”`;
  }
}
