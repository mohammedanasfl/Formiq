import type { ProposedExercise, WorkoutProposal } from '../src/api';
import { MOCK_TYPED_REPLIES } from '../src/mock/coachMock';
import {
  MOCK_REPLACED_PLAN_MINUTES,
  mockIncompleteProposal,
  mockPendingProposal,
  mockProposal,
  mockReplacedPlan,
  mockReplyFor,
  mockSavedPlan,
  mockUncomparedProposal,
  mockWeightDropProposal,
  type MockScenario,
} from '../src/mock/coachProposalsMock';

const NOW = new Date(2026, 9, 22, 9, 0, 0);
const SCENARIOS: MockScenario[] = ['new', 'new-refined', 'edit', 'edit-refined'];

// the backend's own estimate (app/tools/limits.py and formiq_tools.section_minutes): each set and the rest after
// it; a timed set lasts its duration, a set of reps 45 s or 3 s a rep when longer; a main exercise without a rest
// gets 90 s, a warm-up or cool-down activity none
const SET_SECONDS = 45;
const SECONDS_PER_REP = 3;
const DEFAULT_REST_SECONDS = 90;
function sectionMinutes(exercises: ProposedExercise[]): number {
  let seconds = 0;
  for (const item of exercises) {
    const rest = item.rest_seconds ?? (item.section === 'MAIN_WORKOUT' ? DEFAULT_REST_SECONDS : 0);
    const work = item.duration_seconds || Math.max(SET_SECONDS, (item.reps ?? 0) * SECONDS_PER_REP);
    seconds += item.sets * (work + rest);
  }
  return Math.ceil(seconds / 60);
}

describe.each(SCENARIOS)('the %s proposal', (scenario) => {
  const proposal: WorkoutProposal = mockProposal(scenario, NOW, 1);

  test('has the backend\'s own estimate for each section and for the whole workout', () => {
    const of = (section: ProposedExercise['section']) => sectionMinutes(proposal.exercises.filter((exercise) => exercise.section === section));

    expect([proposal.warm_up_minutes, proposal.main_minutes, proposal.cool_down_minutes]).toEqual([of('WARM_UP'), of('MAIN_WORKOUT'), of('COOL_DOWN')]);
    expect(proposal.estimated_minutes).toBe(proposal.warm_up_minutes + proposal.main_minutes + proposal.cool_down_minutes);
  });

  test('carries a weight on every exercise, as the backend now always does: null, since the mock sets none', () => {
    for (const exercise of proposal.exercises) expect(exercise).toHaveProperty('weight_kg', null);
  });

  test('gives every set one target, reps or seconds, never both', () => {
    for (const exercise of proposal.exercises) expect((exercise.reps === null) !== (exercise.duration_seconds === null)).toBe(true);
  });

  test('numbers its exercises 1 to n in order, with a warm-up, a main workout and a cool-down', () => {
    expect(proposal.exercises.map((exercise) => exercise.exercise_order)).toEqual(proposal.exercises.map((_, index) => index + 1));
    expect(new Set(proposal.exercises.map((exercise) => exercise.section))).toEqual(new Set(['WARM_UP', 'MAIN_WORKOUT', 'COOL_DOWN']));
  });

  test('is complete, and says what the main exercises cover', () => {
    expect(proposal.coverage).toMatchObject({ complete: true, missing_regions: [], limitations: [] });
    expect(proposal.coverage.main_exercises_counted).toBeGreaterThanOrEqual(proposal.coverage.main_exercises_required);
  });

  test('revises the saved plan only when it is an edit, and says what it keeps', () => {
    const edits = scenario.startsWith('edit');

    expect(proposal.revision !== null).toBe(edits);
    if (proposal.revision) {
      expect(proposal.revision).toMatchObject({
        replaces_plan_id: 41,
        replaces_plan_name: 'Core & Abs Focus',
        kept_exercises: ['Plank'],
        replaces_plan_estimated_minutes: MOCK_REPLACED_PLAN_MINUTES,
      });
    }
  });

  test('has the backend\'s comparison with the saved plan when it is an edit, and none when it is new', () => {
    expect(proposal.changes === null).toBe(!scenario.startsWith('edit'));
    if (proposal.changes) {
      expect(proposal.changes).toMatchObject({ compared_with_plan_id: 41, compared_with_plan_name: 'Core & Abs Focus', scheduled_date_changed: false });
      // everything the proposal has is added, changed or unchanged, and the rest of the plan is removed
      const proposed = proposal.exercises.map((exercise) => exercise.exercise_name).sort();
      const compared = [...proposal.changes.added, ...proposal.changes.changed].map((item) => item.exercise_name).concat(proposal.changes.unchanged).sort();
      expect(compared).toEqual(proposed);
    }
  });

  test('carries no description, difficulty or picture: the backend\'s proposal has none', () => {
    expect(Object.keys(proposal).sort()).toEqual(
      ['binding', 'changes', 'cool_down_minutes', 'coverage', 'estimated_minutes', 'exercises', 'expires_at', 'main_minutes', 'name', 'proposal_id', 'revision', 'scheduled_date', 'warm_up_minutes'].sort(),
    );
  });

  test('has a reply that claims no change, save or approval, and gives the length the proposal gives', () => {
    const reply = mockReplyFor(scenario);

    expect(reply).not.toMatch(/\b(I've|I have|I)\s+(created|built|made|saved|changed|updated|replaced|approved|applied)\b/i);
    expect(reply).not.toMatch(/\b(has|have) been (saved|applied|updated|changed|replaced)\b|\b(was|were) (saved|applied|updated|changed|replaced)\b/i);
    const minutes = reply.match(/(\d+) minutes/);
    if (minutes) expect(Math.abs(Number(minutes[1]) - proposal.estimated_minutes)).toBeLessThanOrEqual(2);
  });
});

test('the replies to typed messages claim no change, save or approval either, and say that this is a preview', () => {
  for (const reply of MOCK_TYPED_REPLIES) {
    expect(reply).not.toMatch(/\b(I've|I have|I)\s+(created|built|made|saved|changed|updated|replaced|approved|applied|checked|found)\b/i);
    expect(reply).toMatch(/preview|isn't connected|is connected|For now/i);
  }
});

describe('ids', () => {
  test('are the backend\'s forms: 32 hex digits for the proposal, 64 for its binding', () => {
    const proposal = mockProposal('edit', NOW, 255);

    expect(proposal.proposal_id).toBe('ff'.padStart(32, '0'));
    expect(proposal.binding).toBe('ff'.padStart(64, '0'));
  });
});

describe('the saved plan the edits revise', () => {
  const plan = mockReplacedPlan(NOW);

  test('is today\'s PLANNED Core & Abs Focus, as the backend returns a plan', () => {
    expect(plan).toMatchObject({ id: 41, name: 'Core & Abs Focus', status: 'PLANNED', scheduled_date: '2026-10-22' });
    expect(plan.exercises).toHaveLength(6);
  });

  test('takes 18 minutes by the backend\'s estimate, which is what the replies say of the edits', () => {
    const asProposed = plan.exercises.map<ProposedExercise>((item) => ({
      exercise_order: item.exercise_order,
      section: item.section,
      exercise_id: item.id,
      exercise_name: item.exercise.name,
      equipment: [],
      sets: item.sets,
      reps: item.reps,
      duration_seconds: item.duration_seconds,
      rest_seconds: item.rest_seconds,
      weight_kg: item.weight_kg,
      notes: null,
    }));

    // the workout's length is the sum of its sections', each rounded up on its own
    const total = (['WARM_UP', 'MAIN_WORKOUT', 'COOL_DOWN'] as const).reduce(
      (sum, section) => sum + sectionMinutes(asProposed.filter((item) => item.section === section)),
      0,
    );
    expect(total).toBe(18);
    expect(total).toBe(MOCK_REPLACED_PLAN_MINUTES);
    expect(mockProposal('edit', NOW, 1).estimated_minutes).toBe(18);
    expect(mockProposal('edit-refined', NOW, 1).estimated_minutes).toBe(18);
  });
});

describe("the backend's comparison, as the mock stands in for it", () => {
  const edit = mockProposal('edit', NOW, 1).changes!;

  test('lists what an edit adds, removes and prescribes differently, each with its prescription and its wording', () => {
    expect(edit.added.map((item) => [item.section, item.exercise_name, item.before, item.after?.summary])).toEqual([
      ['MAIN_WORKOUT', 'Dead Bug', null, '3 sets of 12 reps, 60 s rest'],
      ['MAIN_WORKOUT', 'Side Plank', null, '3 sets of 30 s, 60 s rest'],
    ]);
    expect(edit.removed.map((item) => [item.exercise_name, item.before?.summary, item.after])).toEqual([
      ['Bicycle Crunches', '3 sets of 20 reps, 45 s rest', null],
      ['Leg Raises', '3 sets of 15 reps, 45 s rest', null],
    ]);
    expect(edit.changed.map((item) => [item.exercise_name, item.before?.duration_seconds, item.after?.duration_seconds])).toEqual([['Plank', 30, 40]]);
    expect(edit.unchanged).toEqual(['Mountain Climbers', 'Lunges', 'Hamstring Stretch']);
    expect(edit.identical).toBe(false);
  });

  test('a prescription has the numbers and the wording, and a weight when the saved plan has one', () => {
    const dropped = mockWeightDropProposal(NOW, 2).changes!.changed.find((item) => item.exercise_name === 'Goblet Squat')!;

    expect(dropped.before).toEqual({ sets: 3, reps: 10, duration_seconds: null, rest_seconds: 60, weight_kg: 20, summary: '3 sets of 10 reps at 20 kg, 60 s rest' });
    expect(dropped.after).toMatchObject({ weight_kg: null, summary: '3 sets of 10 reps, 60 s rest' });
  });

  test('a proposal the backend could not compare says nothing of the plan or its length', () => {
    const unread = mockUncomparedProposal(NOW, 3);

    expect(unread.changes).toBeNull();
    expect(unread.revision?.replaces_plan_estimated_minutes).toBeNull();
    expect(unread.revision?.replaces_plan_id).toBe(41);
  });

  test('a waiting proposal is a proposal made earlier: it carries when, and expires 30 minutes after', () => {
    const waiting = mockPendingProposal('edit', NOW, 4, 12);

    expect(waiting.created_at).toBe(new Date(NOW.getTime() - 12 * 60_000).toISOString());
    expect(new Date(waiting.expires_at).getTime() - new Date(waiting.created_at).getTime()).toBe(30 * 60_000);
  });
});

describe('what approving a proposal saves', () => {
  test('is a PLANNED plan with the proposal\'s name, day and exercises as prescribed', () => {
    const proposal = mockProposal('new', NOW, 1);

    const saved = mockSavedPlan(proposal, 100);

    expect(saved).toMatchObject({ id: 100, name: proposal.name, status: 'PLANNED', scheduled_date: proposal.scheduled_date });
    expect(saved.exercises.map((item) => [item.section, item.exercise.name, item.sets, item.reps, item.duration_seconds, item.rest_seconds])).toEqual(
      proposal.exercises.map((item) => [item.section, item.exercise_name, item.sets, item.reps, item.duration_seconds, item.rest_seconds]),
    );
  });
});

describe('what approving a proposal with a weight saves', () => {
  test('keeps the weight the proposal prescribed on the exercise (null stays null)', () => {
    const proposal = mockProposal('new', NOW, 1);
    const weighted = { ...proposal, exercises: proposal.exercises.map((item, index) => (index === 3 ? { ...item, weight_kg: 12.5 } : item)) };

    const saved = mockSavedPlan(weighted, 100);

    expect(saved.exercises.map((item) => item.weight_kg)).toEqual(weighted.exercises.map((item, index) => (index === 3 ? 12.5 : null)));
  });
});

describe('the workout the catalog could not fully cover', () => {
  test('says so, as the backend does: not complete, a region missing, and why', () => {
    const proposal = mockIncompleteProposal(NOW, 5);

    expect(proposal.coverage.complete).toBe(false);
    expect(proposal.coverage.missing_regions).toEqual(['UPPER_PULL']);
    expect(proposal.coverage.limitations).toHaveLength(1);
  });
});
