import type { ExerciseChange, Prescription, ProposalChanges, WorkoutProposal } from '../src/api';
import {
  compareWithOriginal,
  isMeaningfulRename,
  keyChangeText,
  markKey,
  prescriptionDetails,
  visibleChangeIndexes,
  type KeyChange,
} from '../src/coach/proposalChanges';
import { mockPrescription, mockProposal } from '../src/mock/coachProposalsMock';

// The comparison is the backend's (`proposal.changes`): these tests are about how it is worded and ordered, and that
// the app adds nothing to it and takes nothing from it.

const NOW = new Date(2026, 9, 22, 9, 0, 0);

const rx = (overrides: Partial<Prescription> = {}): Prescription => ({
  sets: 3,
  reps: null,
  duration_seconds: 30,
  rest_seconds: 45,
  weight_kg: null,
  summary: '3 sets of 30 s, 45 s rest',
  ...overrides,
});

const added = (section: ExerciseChange['section'], name: string): ExerciseChange => ({ section, exercise_name: name, before: null, after: rx() });
const removed = (section: ExerciseChange['section'], name: string): ExerciseChange => ({ section, exercise_name: name, before: rx(), after: null });
const changed = (section: ExerciseChange['section'], name: string, before: Partial<Prescription>, after: Partial<Prescription>): ExerciseChange => ({
  section,
  exercise_name: name,
  before: rx(before),
  after: rx(after),
});

// a proposal with the backend's changes as the test writes them
function proposalWith(overrides: Partial<ProposalChanges>, proposal: Partial<WorkoutProposal> = {}): WorkoutProposal {
  const base = mockProposal('edit', NOW, 9);
  return {
    ...base,
    ...proposal,
    changes: {
      compared_with_plan_id: 41,
      compared_with_plan_name: 'Core & Abs Focus',
      compared_with_scheduled_date: base.scheduled_date,
      added: [],
      removed: [],
      changed: [],
      unchanged: [],
      name_changed: false,
      scheduled_date_changed: false,
      identical: false,
      ...overrides,
    },
  };
}

// the proposal with no length for the plan it replaces, so no length line is in the way
const withoutLength = (proposal: WorkoutProposal): WorkoutProposal => ({
  ...proposal,
  revision: proposal.revision && { ...proposal.revision, replaces_plan_estimated_minutes: null },
});

describe('prescriptionDetails: which of an exercise\'s numbers moved, from the two prescriptions the backend gave', () => {
  test('a longer hold changes only the target', () => {
    expect(prescriptionDetails(rx(), rx({ duration_seconds: 40 }))).toEqual(['30 s → 40 s']);
  });

  test('sets, target and rest are each named when they differ', () => {
    expect(
      prescriptionDetails(
        rx({ sets: 3, reps: 10, duration_seconds: null, rest_seconds: 45 }),
        rx({ sets: 4, reps: 12, duration_seconds: null, rest_seconds: 60 }),
      ),
    ).toEqual(['3 sets → 4 sets', '10 reps → 12 reps', '45 s rest → 60 s rest']);
  });

  test('a single set is "1 set"', () => {
    expect(prescriptionDetails(rx({ sets: 1 }), rx({ sets: 2 }))).toEqual(['1 set → 2 sets']);
  });

  test('going from reps to a hold, and from no rest to a rest, are changes too', () => {
    expect(prescriptionDetails(rx({ reps: 10, duration_seconds: null, rest_seconds: null }), rx({ rest_seconds: 30 }))).toEqual([
      '10 reps → 30 s',
      'no rest → 30 s rest',
    ]);
  });

  test('no rest and a rest of 0 are the same', () => {
    expect(prescriptionDetails(rx({ rest_seconds: null, summary: 'a' }), rx({ rest_seconds: 0, summary: 'b' }))).toEqual(['a → b']);
  });

  // the case the app used to miss: a saved plan's weight, which a proposal never sets
  test('a weight the saved plan has and the proposal does not is named', () => {
    expect(prescriptionDetails(rx({ weight_kg: 20 }), rx())).toEqual(['20 kg → no weight']);
    expect(prescriptionDetails(rx(), rx({ weight_kg: 22.5 }))).toEqual(['no weight → 22.5 kg']);
    expect(prescriptionDetails(rx({ weight_kg: 20 }), rx({ weight_kg: 25 }))).toEqual(['20 kg → 25 kg']);
  });

  test('says each thing that differs, in one line: sets, target, rest, weight', () => {
    expect(prescriptionDetails(rx({ weight_kg: 20 }), rx({ sets: 4, duration_seconds: 40, rest_seconds: 60 }))).toEqual([
      '3 sets → 4 sets',
      '30 s → 40 s',
      '45 s rest → 60 s rest',
      '20 kg → no weight',
    ]);
  });

  test("when none of the numbers differs, the backend's own wording of both is shown, so a change it listed is never dropped", () => {
    expect(prescriptionDetails(rx({ summary: 'before words' }), rx({ summary: 'after words' }))).toEqual(['before words → after words']);
  });

  test('the prescription the mock builds says the same as the backend does', () => {
    expect(mockPrescription({ sets: 3, reps: 10, rest: 60 }, 20).summary).toBe('3 sets of 10 reps at 20 kg, 60 s rest');
    expect(mockPrescription({ sets: 1, seconds: 30 }).summary).toBe('1 set of 30 s');
  });
});

describe('compareWithOriginal: the backend\'s changes, in the order a person reads a workout', () => {
  test('a new workout, or one the backend could not compare, has none: no changes and no marks', () => {
    for (const proposal of [mockProposal('new', NOW, 1), { ...mockProposal('edit', NOW, 2), changes: null }]) {
      const comparison = compareWithOriginal(proposal);

      expect(comparison.changes).toEqual([]);
      expect(comparison.marks.size).toBe(0);
    }
  });

  test('puts an exercise taken out and one put in its place side by side, per section', () => {
    const { changes } = compareWithOriginal(
      withoutLength(
        proposalWith({
          removed: [removed('MAIN_WORKOUT', 'Bicycle Crunches'), removed('MAIN_WORKOUT', 'Leg Raises'), removed('WARM_UP', 'Lunges')],
          added: [added('MAIN_WORKOUT', 'Dead Bug'), added('MAIN_WORKOUT', 'Side Plank'), added('WARM_UP', 'Glute Bridge')],
        }),
      ),
    );

    expect(changes).toEqual<KeyChange[]>([
      { kind: 'replaced', section: 'WARM_UP', from: 'Lunges', to: 'Glute Bridge' },
      { kind: 'replaced', section: 'MAIN_WORKOUT', from: 'Bicycle Crunches', to: 'Dead Bug' },
      { kind: 'replaced', section: 'MAIN_WORKOUT', from: 'Leg Raises', to: 'Side Plank' },
    ]);
  });

  test('what has no partner is added or removed on its own', () => {
    const { changes } = compareWithOriginal(
      withoutLength(
        proposalWith({
          removed: [removed('MAIN_WORKOUT', 'Leg Raises'), removed('COOL_DOWN', 'Hamstring Stretch')],
          added: [added('MAIN_WORKOUT', 'Dead Bug'), added('MAIN_WORKOUT', 'Side Plank'), added('WARM_UP', 'Arm Circles')],
        }),
      ),
    );

    expect(changes).toEqual<KeyChange[]>([
      { kind: 'added', section: 'WARM_UP', name: 'Arm Circles' },
      { kind: 'replaced', section: 'MAIN_WORKOUT', from: 'Leg Raises', to: 'Dead Bug' },
      { kind: 'added', section: 'MAIN_WORKOUT', name: 'Side Plank' },
      { kind: 'removed', section: 'COOL_DOWN', name: 'Hamstring Stretch' },
    ]);
  });

  test('a changed exercise says which of its numbers moved, after the swaps of its section', () => {
    const { changes } = compareWithOriginal(
      withoutLength(
        proposalWith({
          removed: [removed('MAIN_WORKOUT', 'Leg Raises')],
          added: [added('MAIN_WORKOUT', 'Dead Bug')],
          changed: [changed('MAIN_WORKOUT', 'Plank', {}, { duration_seconds: 40 }), changed('MAIN_WORKOUT', 'Goblet Squat', { weight_kg: 20 }, {})],
        }),
      ),
    );

    expect(changes).toEqual<KeyChange[]>([
      { kind: 'replaced', section: 'MAIN_WORKOUT', from: 'Leg Raises', to: 'Dead Bug' },
      { kind: 'changed', section: 'MAIN_WORKOUT', name: 'Plank', details: ['30 s → 40 s'] },
      { kind: 'changed', section: 'MAIN_WORKOUT', name: 'Goblet Squat', details: ['20 kg → no weight'] },
    ]);
  });

  test('lists nothing the backend did not list: the unchanged exercises are no lines', () => {
    const { changes } = compareWithOriginal(withoutLength(proposalWith({ unchanged: ['Plank', 'Dead Bug'] })));

    expect(changes).toEqual([]);
  });

  test('marks the proposal\'s exercises the backend lists as added or changed, by section and exact name', () => {
    const { marks } = compareWithOriginal(
      proposalWith({
        added: [added('MAIN_WORKOUT', 'Dead Bug')],
        changed: [changed('WARM_UP', 'Plank', {}, { duration_seconds: 40 })],
        removed: [removed('MAIN_WORKOUT', 'Leg Raises')],
      }),
    );

    expect(marks.get(markKey('MAIN_WORKOUT', 'Dead Bug'))).toBe('new');
    expect(marks.get(markKey('WARM_UP', 'Plank'))).toBe('changed');
    // a removed exercise is not in the proposal, so there is nothing to mark
    expect(marks.has(markKey('MAIN_WORKOUT', 'Leg Raises'))).toBe(false);
    // the same name in another section is another exercise
    expect(marks.has(markKey('MAIN_WORKOUT', 'Plank'))).toBe(false);
  });

  test('matches names exactly as the backend wrote them: a spelling the app would have treated alike is not marked', () => {
    const { marks } = compareWithOriginal(proposalWith({ added: [added('MAIN_WORKOUT', 'Pushups')] }));

    expect(marks.has(markKey('MAIN_WORKOUT', 'Push-Up'))).toBe(false);
  });

  describe('the length', () => {
    test('is said to stay only when the backend gave the replaced plan\'s length and it is the same', () => {
      const proposal = proposalWith({});
      const same = { ...proposal, revision: proposal.revision && { ...proposal.revision, replaces_plan_estimated_minutes: proposal.estimated_minutes } };

      expect(compareWithOriginal(same).changes.at(-1)).toEqual({ kind: 'duration', before: 18, after: 18 });
    });

    test('is said to change when the lengths differ', () => {
      const proposal = proposalWith({});
      const longer = { ...proposal, revision: proposal.revision && { ...proposal.revision, replaces_plan_estimated_minutes: 23 } };

      expect(compareWithOriginal(longer).changes.at(-1)).toEqual({ kind: 'duration', before: 23, after: 18 });
    });

    test('is not said at all when the backend did not give the replaced plan\'s length', () => {
      expect(compareWithOriginal(withoutLength(proposalWith({}))).changes.some((change) => change.kind === 'duration')).toBe(false);
    });

    test.each([0, -2])('is not said for a replaced plan length of %s, which is no length', (minutes) => {
      const proposal = proposalWith({});
      const odd = { ...proposal, revision: proposal.revision && { ...proposal.revision, replaces_plan_estimated_minutes: minutes } };

      expect(compareWithOriginal(odd).changes.some((change) => change.kind === 'duration')).toBe(false);
    });
  });

  describe('the day', () => {
    test('is said to move when the backend says it did, from the plan\'s day to the proposal\'s', () => {
      const { changes } = compareWithOriginal(
        withoutLength(proposalWith({ scheduled_date_changed: true, compared_with_scheduled_date: '2026-10-21' }, { scheduled_date: '2026-10-23' })),
      );

      expect(changes).toEqual<KeyChange[]>([{ kind: 'date', before: '2026-10-21', after: '2026-10-23' }]);
    });

    test('is not said when the backend says it did not move', () => {
      expect(compareWithOriginal(withoutLength(proposalWith({ compared_with_scheduled_date: '2026-10-21' }, { scheduled_date: '2026-10-23' }))).changes).toEqual([]);
    });

    test('comes last, after the length', () => {
      const { changes } = compareWithOriginal(proposalWith({ scheduled_date_changed: true, compared_with_scheduled_date: '2026-10-21' }));

      expect(changes.map((change) => change.kind)).toEqual(['duration', 'date']);
    });
  });
});

// What the backend now sends for a proposal that changes only a weight, or only the day, or only the name. `identical` means
// the exercises are prescribed alike and nothing more: a workout moved to another day arrives as identical: true with
// scheduled_date_changed: true. The card never decides "nothing changed" from `identical`.
describe('a change of weight alone', () => {
  const lines = (change: ExerciseChange) => compareWithOriginal(withoutLength(proposalWith({ changed: [change], unchanged: ['Plank'] }))).changes.map(keyChangeText);

  test('from one weight to another says both, in kilograms', () => {
    expect(lines(changed('MAIN_WORKOUT', 'Goblet Squat', { weight_kg: 15 }, { weight_kg: 20 }))).toEqual(['Goblet Squat: 15 kg → 20 kg']);
    expect(lines(changed('MAIN_WORKOUT', 'Goblet Squat', { weight_kg: 12.5 }, { weight_kg: 17.5 }))).toEqual(['Goblet Squat: 12.5 kg → 17.5 kg']);
  });

  test('from no weight to one says a weight was added', () => {
    expect(lines(changed('MAIN_WORKOUT', 'Goblet Squat', {}, { weight_kg: 20 }))).toEqual(['Goblet Squat: no weight → 20 kg']);
  });

  test('from a weight to none says it was dropped (as it already did)', () => {
    expect(lines(changed('MAIN_WORKOUT', 'Goblet Squat', { weight_kg: 15 }, {}))).toEqual(['Goblet Squat: 15 kg → no weight']);
  });

  test('is a change only the weight shows: nothing else of the exercise is said to have moved', () => {
    const change = changed('MAIN_WORKOUT', 'Goblet Squat', { weight_kg: 15, summary: '3 sets of 10 reps at 15 kg' }, { weight_kg: 20, summary: '3 sets of 10 reps at 20 kg' });

    expect(prescriptionDetails(change.before!, change.after!)).toEqual(['15 kg → 20 kg']);
  });

  test('marks the exercise as changed, and lists nothing else (the other exercises are as they were)', () => {
    const comparison = compareWithOriginal(
      withoutLength(proposalWith({ changed: [changed('MAIN_WORKOUT', 'Goblet Squat', { weight_kg: 15 }, { weight_kg: 20 })], unchanged: ['Plank'], identical: false })),
    );

    expect(comparison.marks.get(markKey('MAIN_WORKOUT', 'Goblet Squat'))).toBe('changed');
    expect(comparison.changes).toHaveLength(1);
  });
});

describe('a change of day or name with every exercise kept (identical: true)', () => {
  const keptAll = { unchanged: ['Plank', 'Dead Bug'], identical: true };

  test('a day-only move says the day moved, from the plan\'s day to the proposal\'s', () => {
    const { changes } = compareWithOriginal(
      withoutLength(proposalWith({ ...keptAll, scheduled_date_changed: true, compared_with_scheduled_date: '2026-10-21' }, { scheduled_date: '2026-10-23' })),
    );

    expect(changes).toEqual<KeyChange[]>([{ kind: 'date', before: '2026-10-21', after: '2026-10-23' }]);
    expect(changes.map(keyChangeText)).toEqual(['Moved from Wed, 21 Oct to Fri, 23 Oct']);
  });

  test('a day-only move from a plan with no day says it is scheduled for the new one', () => {
    const { changes } = compareWithOriginal(
      withoutLength(proposalWith({ ...keptAll, scheduled_date_changed: true, compared_with_scheduled_date: null }, { scheduled_date: '2026-10-23' })),
    );

    expect(changes.map(keyChangeText)).toEqual(['Scheduled for Fri, 23 Oct']);
  });

  test('a rename alone says the old and the new name', () => {
    const { changes } = compareWithOriginal(withoutLength(proposalWith({ ...keptAll, name_changed: true }, { name: 'Core Basics' })));

    expect(changes).toEqual<KeyChange[]>([{ kind: 'renamed', before: 'Core & Abs Focus', after: 'Core Basics' }]);
    expect(changes.map(keyChangeText)).toEqual(['Renamed from “Core & Abs Focus” to “Core Basics”']);
  });

  test('a move and a rename say both, the day first', () => {
    const { changes } = compareWithOriginal(
      withoutLength(proposalWith({ ...keptAll, name_changed: true, scheduled_date_changed: true, compared_with_scheduled_date: '2026-10-21' }, { name: 'Core Basics', scheduled_date: '2026-10-23' })),
    );

    expect(changes.map((change) => change.kind)).toEqual(['date', 'renamed']);
  });

  test('with the replaced plan\'s length known, the length is said to stay beside the new day', () => {
    const proposal = proposalWith({ ...keptAll, scheduled_date_changed: true, compared_with_scheduled_date: '2026-10-21' }, { scheduled_date: '2026-10-23' });
    const same = { ...proposal, revision: proposal.revision && { ...proposal.revision, replaces_plan_estimated_minutes: proposal.estimated_minutes } };

    expect(compareWithOriginal(same).changes.map(keyChangeText)).toEqual(['Kept the same duration (18 min)', 'Moved from Wed, 21 Oct to Fri, 23 Oct']);
  });
});

describe('a rename is listed only when it is a different name (Phase 2.6)', () => {
  const keptAll = { unchanged: ['Plank', 'Dead Bug'], identical: true };

  test.each<[string, string]>([
    ['Core & Abs Focus', 'Core & Abs Focus (Harder)'],
    ['Core & Abs Focus', 'Core & Abs Focus (No Weight)'],
    ['Core & Abs Focus', 'Shorter Core & Abs Focus'],
    ['Core & Abs Focus', 'Core & Abs Focus 2'],
    ['Saturday Core', 'Saturday Core - Easier'],
    ['Core & Abs Focus', 'core & abs focus'],
    ['Core & Abs Focus', 'Core & Abs Focus'],
    ['Core & Abs Focus', 'Core  &  Abs-Focus'],
    ['Core & Abs Focus', 'Core & Abs'],
  ])('%j to %j only decorates the name: the title carries it, no line', (before, after) => {
    expect(isMeaningfulRename(before, after)).toBe(false);
  });

  test.each<[string, string]>([
    ['Core & Abs Focus', 'Core Basics'],
    ['Core & Abs Focus', 'Core Stability & Abs'],
    ['Core & Abs Focus', 'Monday Strength'],
    ['Core', 'Hardcore Basics'],
    ['Upper Body', 'Lower Body'],
    ['Core & Abs Focus', '30-Minute Full Body'],
  ])('%j to %j is a different name: it is listed', (before, after) => {
    expect(isMeaningfulRename(before, after)).toBe(true);
  });

  test('a name made of nothing a word can be read from is listed, not guessed at', () => {
    expect(isMeaningfulRename('', 'Core Basics')).toBe(true);
    expect(isMeaningfulRename('Core Basics', '???')).toBe(true);
  });

  test('a decorated name with every exercise kept lists nothing at all', () => {
    const { changes } = compareWithOriginal(withoutLength(proposalWith({ ...keptAll, name_changed: true }, { name: 'Core & Abs Focus (Harder)' })));

    expect(changes).toEqual([]);
  });

  test('a decorated name does not take the place of a real change: the exercises are still listed', () => {
    const { changes } = compareWithOriginal(
      withoutLength(
        proposalWith({ name_changed: true, changed: [changed('MAIN_WORKOUT', 'Plank', {}, { duration_seconds: 40 })] }, { name: 'Core & Abs Focus (Harder)' }),
      ),
    );

    expect(changes.map(keyChangeText)).toEqual(['Plank: 30 s → 40 s']);
  });

  test('a decorated name does not hide the day: a move and a decorated name list only the move', () => {
    const { changes } = compareWithOriginal(
      withoutLength(
        proposalWith({ ...keptAll, name_changed: true, scheduled_date_changed: true, compared_with_scheduled_date: '2026-10-21' }, { name: 'Core & Abs Focus (Moved)', scheduled_date: '2026-10-23' }),
      ),
    );

    expect(changes.map((change) => change.kind)).toEqual(['date']);
  });

  test('a different name is still listed after the day, as before', () => {
    const { changes } = compareWithOriginal(
      withoutLength(
        proposalWith({ ...keptAll, name_changed: true, scheduled_date_changed: true, compared_with_scheduled_date: '2026-10-21' }, { name: 'Monday Strength', scheduled_date: '2026-10-23' }),
      ),
    );

    expect(changes.map((change) => change.kind)).toEqual(['date', 'renamed']);
  });

  test('the backend not saying the name changed lists no rename, whatever the two names look like', () => {
    const { changes } = compareWithOriginal(withoutLength(proposalWith({ ...keptAll, name_changed: false }, { name: 'Monday Strength' })));

    expect(changes).toEqual([]);
  });
});

describe('visibleChangeIndexes: a change of day is never left behind "and N more" (Phase 2.6)', () => {
  const exercise = (index: number): KeyChange => ({ kind: 'added', section: 'MAIN_WORKOUT', name: `Exercise ${index}` });
  const day: KeyChange = { kind: 'date', before: '2026-10-21', after: '2026-10-23' };
  const length: KeyChange = { kind: 'duration', before: 18, after: 18 };
  const exercises = (count: number) => Array.from({ length: count }, (_, index) => exercise(index + 1));

  test('with room for all of them, all are listed in order', () => {
    expect(visibleChangeIndexes([...exercises(3), day], 6)).toEqual([0, 1, 2, 3]);
    expect(visibleChangeIndexes([...exercises(5), day], 6)).toEqual([0, 1, 2, 3, 4, 5]);
    expect(visibleChangeIndexes([], 6)).toEqual([]);
  });

  test('with more than there is room for, the first ones are listed and the day takes the last place', () => {
    // seven exercise changes and the day: the day is the eighth change, after the length
    const changes = [...exercises(7), length, day];

    expect(visibleChangeIndexes(changes, 6)).toEqual([0, 1, 2, 3, 4, 8]);
  });

  test('the day keeps its place among the lines it is listed with', () => {
    const changes = [...exercises(4), length, day, ...exercises(3)];

    const shown = visibleChangeIndexes(changes, 6);

    expect(shown).toEqual([0, 1, 2, 3, 4, 5]);
    expect(shown.map((index) => changes[index].kind)).toContain('date');
  });

  test('without a day, the first few are listed as they always were', () => {
    expect(visibleChangeIndexes([...exercises(9)], 6)).toEqual([0, 1, 2, 3, 4, 5]);
  });

  test('the day alone with room for one is listed', () => {
    expect(visibleChangeIndexes([...exercises(3), day], 1)).toEqual([3]);
  });

  test('the count never goes above the room, and never loses the day', () => {
    for (let count = 0; count <= 12; count += 1) {
      for (const max of [1, 2, 6, 8]) {
        const changes = [...exercises(count), length, day];
        const shown = visibleChangeIndexes(changes, max);

        expect(shown.length).toBeLessThanOrEqual(Math.max(max, 1));
        expect(shown).toContain(changes.length - 1);
        expect([...shown].sort((a, b) => a - b)).toEqual(shown);
        expect(new Set(shown).size).toBe(shown.length);
      }
    }
  });
});

describe('nothing changed is judged from everything the backend says, never from `identical`', () => {
  const nothing = { unchanged: ['Plank', 'Dead Bug'] };

  test.each([true, false])('no exercise, name or day changed (identical %s) lists no change', (identical) => {
    expect(compareWithOriginal(withoutLength(proposalWith({ ...nothing, identical }))).changes).toEqual([]);
  });

  test('identical: true does not hide a day that moved or a name that changed', () => {
    expect(compareWithOriginal(withoutLength(proposalWith({ ...nothing, identical: true, scheduled_date_changed: true }))).changes).toHaveLength(1);
    expect(compareWithOriginal(withoutLength(proposalWith({ ...nothing, identical: true, name_changed: true }))).changes).toHaveLength(1);
  });

  test('identical: true does not hide an exercise the backend lists as changed (the lists are what is read)', () => {
    const { changes } = compareWithOriginal(
      withoutLength(proposalWith({ identical: true, changed: [changed('MAIN_WORKOUT', 'Plank', {}, { duration_seconds: 40 })] })),
    );

    expect(changes.map(keyChangeText)).toEqual(['Plank: 30 s → 40 s']);
  });

  test('identical: false with nothing listed does not make a change up', () => {
    expect(compareWithOriginal(withoutLength(proposalWith({ identical: false }))).changes).toEqual([]);
  });
});

describe('keyChangeText: one line each', () => {
  test.each<[KeyChange, string]>([
    [{ kind: 'replaced', section: 'MAIN_WORKOUT', from: 'Leg Raises', to: 'Side Plank' }, 'Replaced Leg Raises with Side Plank'],
    [{ kind: 'replaced', section: 'WARM_UP', from: 'Lunges', to: 'Glute Bridge' }, 'Replaced Lunges with Glute Bridge in the warm-up'],
    [{ kind: 'replaced', section: 'COOL_DOWN', from: 'A', to: 'B' }, 'Replaced A with B in the cool-down'],
    [{ kind: 'added', section: 'WARM_UP', name: 'Arm Circles' }, 'Added Arm Circles to the warm-up'],
    [{ kind: 'added', section: 'MAIN_WORKOUT', name: 'Dead Bug' }, 'Added Dead Bug to the main workout'],
    [{ kind: 'removed', section: 'COOL_DOWN', name: 'Hamstring Stretch' }, 'Removed Hamstring Stretch from the cool-down'],
    [{ kind: 'changed', section: 'MAIN_WORKOUT', name: 'Plank', details: ['3 sets → 4 sets', '30 s → 40 s'] }, 'Plank: 3 sets → 4 sets, 30 s → 40 s'],
    [{ kind: 'changed', section: 'MAIN_WORKOUT', name: 'Goblet Squat', details: ['20 kg → no weight'] }, 'Goblet Squat: 20 kg → no weight'],
    [{ kind: 'duration', before: 18, after: 18 }, 'Kept the same duration (18 min)'],
    [{ kind: 'duration', before: 23, after: 18 }, 'Duration changed from 23 to 18 min'],
    [{ kind: 'date', before: '2026-10-21', after: '2026-10-23' }, 'Moved from Wed, 21 Oct to Fri, 23 Oct'],
    [{ kind: 'date', before: null, after: '2026-10-23' }, 'Scheduled for Fri, 23 Oct'],
    [{ kind: 'renamed', before: 'Core & Abs Focus', after: 'Core Basics' }, 'Renamed from “Core & Abs Focus” to “Core Basics”'],
  ])('%j', (change, text) => {
    expect(keyChangeText(change)).toBe(text);
  });
});
