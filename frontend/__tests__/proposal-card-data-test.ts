import type { ExerciseChange, Prescription, SessionFocus, WorkoutProposal } from '../src/api';
import { proposalCardData } from '../src/coach/proposalCard';
import {
  mockIncompleteProposal,
  mockProposal,
  mockUncomparedProposal,
  mockWeightDropProposal,
  MOCK_REPLACED_PLAN_ID,
} from '../src/mock/coachProposalsMock';

const NOW = new Date(2026, 9, 22, 9, 0, 0);

describe('a new workout', () => {
  const card = proposalCardData(mockProposal('new', NOW, 1), NOW);

  test('is a "new" card with the proposal\'s own title, length and number of exercises', () => {
    expect(card.kind).toBe('new');
    expect(card.title).toBe('Upper Body Strength');
    expect(card.minutes).toBe(24);
    expect(card.exerciseCount).toBe(8);
    expect(card.exerciseCountLabel).toBe('8 exercises');
  });

  test('compares with nothing, lists no changes and replaces nothing', () => {
    expect(card.comparison).toBe('none');
    expect(card.keyChanges).toEqual([]);
    expect(card.keyChangeLines).toEqual([]);
    expect(card.replaces).toBeNull();
  });

  test('has the three sections in the order they are done, with the proposal\'s own minutes', () => {
    expect(card.sections.map((section) => [section.id, section.title, section.minutes, section.exercises.length])).toEqual([
      ['WARM_UP', 'Warm-up', 2, 2],
      ['MAIN_WORKOUT', 'Main Workout', 21, 4],
      ['COOL_DOWN', 'Cool-down', 1, 2],
    ]);
  });

  test('says what the proposal says about the workout, which is its focus and its day', () => {
    expect(card.subtitle).toBe('Upper body focus • Today');
    expect(card.focusLabel).toBe('Upper body');
  });

  test('has no description or difficulty: the proposal has neither, so there is nothing to show', () => {
    expect(Object.keys(card)).not.toEqual(expect.arrayContaining(['description']));
    expect(Object.keys(card)).not.toEqual(expect.arrayContaining(['difficulty']));
    expect(JSON.stringify(card)).not.toMatch(/difficulty|moderate|beginner|advanced/i);
  });

  test('marks no exercise as new or changed: there is no workout to be new against', () => {
    expect(card.sections.flatMap((section) => section.exercises).every((exercise) => exercise.mark === null)).toBe(true);
  });

  test('writes each exercise as the proposal prescribes it, with its equipment or "Bodyweight"', () => {
    const main = card.sections.find((section) => section.id === 'MAIN_WORKOUT')!.exercises;
    expect(main.map((exercise) => [exercise.name, exercise.prescription, exercise.equipment])).toEqual([
      ['Push-Up', '3 sets • 12 reps • 60 s rest', 'Bodyweight'],
      ['Dumbbell Bent-Over Row', '3 sets • 12 reps • 60 s rest', 'Dumbbell'],
      ['Dumbbell Shoulder Press', '3 sets • 10 reps • 60 s rest', 'Dumbbell'],
      ['Dumbbell Biceps Curl', '3 sets • 12 reps • 60 s rest', 'Dumbbell'],
    ]);
    const warm = card.sections.find((section) => section.id === 'WARM_UP')!.exercises;
    expect(warm[0].prescription).toBe('2 sets • 30 seconds');
  });
});

describe('the day', () => {
  test('is "Tomorrow" for the next day and written out for any other', () => {
    const tomorrow = { ...mockProposal('new', NOW, 1), scheduled_date: '2026-10-23' };
    const later = { ...mockProposal('new', NOW, 1), scheduled_date: '2026-10-30' };

    expect(proposalCardData(tomorrow, NOW).subtitle).toBe('Upper body focus • Tomorrow');
    expect(proposalCardData(later, NOW).subtitle).toBe('Upper body focus • Fri, 30 Oct');
  });

  test('is left out when it is not a real day', () => {
    const odd = { ...mockProposal('new', NOW, 1), scheduled_date: 'soon' };

    expect(proposalCardData(odd, NOW).subtitle).toBe('Upper body focus');
  });
});

describe('what the picture and the label come from', () => {
  test.each<[SessionFocus, string, string]>([
    ['CORE', 'Core', 'core'],
    ['UPPER_BODY', 'Upper body', 'upper-body'],
    ['PUSH', 'Push', 'upper-body'],
    ['PULL', 'Pull', 'upper-body'],
    ['LOWER_BODY', 'Lower body', 'lower-body'],
    ['FULL_BODY', 'Full body', 'full-body'],
  ])("the proposal's focus %s is the label %s and the %s picture", (focus, label, category) => {
    const proposal = mockProposal('new', NOW, 1);
    const card = proposalCardData({ ...proposal, coverage: { ...proposal.coverage, focus } }, NOW);

    expect(card.focusLabel).toBe(label);
    expect(card.categories).toEqual([category]);
  });
});

describe('an updated workout', () => {
  const card = proposalCardData(mockProposal('edit', NOW, 2), NOW);

  test('is an "updated" card that says which saved workout it would replace, and what it keeps', () => {
    expect(card.kind).toBe('updated');
    expect(card.replaces).toEqual({ planId: MOCK_REPLACED_PLAN_ID, name: 'Core & Abs Focus', keptExercises: ['Plank'] });
  });

  test("lists the differences the backend found by comparing the two workouts, and only those", () => {
    expect(card.comparison).toBe('compared');
    expect(card.keyChangeLines).toEqual([
      'Replaced Bicycle Crunches with Dead Bug',
      'Replaced Leg Raises with Side Plank',
      'Plank: 30 s → 40 s',
      'Kept the same duration (18 min)',
      // the proposal is named differently from the saved workout, and the backend says so (`name_changed`)
      'Renamed from “Core & Abs Focus” to “Core Stability & Abs”',
    ]);
  });

  test('says the length stayed or changed only because the backend said how long the replaced workout takes', () => {
    const proposal = mockProposal('edit', NOW, 2);
    const different = { ...proposal, revision: proposal.revision && { ...proposal.revision, replaces_plan_estimated_minutes: 23 } };
    const unknown = mockUncomparedProposal(NOW, 3);

    expect(proposalCardData(different, NOW).keyChangeLines).toContain('Duration changed from 23 to 18 min');
    expect(proposalCardData({ ...unknown, changes: proposal.changes }, NOW).keyChangeLines.join(' ')).not.toMatch(/duration/i);
  });

  test('marks each exercise that is new or changed against the saved one, and not the rest', () => {
    const main = card.sections.find((section) => section.id === 'MAIN_WORKOUT')!.exercises;
    expect(main.map((exercise) => [exercise.name, exercise.mark])).toEqual([
      ['Plank', 'changed'],
      ['Dead Bug', 'new'],
      ['Side Plank', 'new'],
    ]);
    const warm = card.sections.find((section) => section.id === 'WARM_UP')!.exercises;
    expect(warm.every((exercise) => exercise.mark === null)).toBe(true);
  });

  test("a refinement is compared with the original saved workout, which is what the backend's changes say, not with the first proposal", () => {
    const refined = proposalCardData(mockProposal('edit-refined', NOW, 3), NOW);

    expect(refined.keyChangeLines).toContain('Replaced Mountain Climbers with Cat-Cow Stretch in the warm-up');
    expect(refined.keyChangeLines).not.toContain('Plank: 30 s → 40 s');
  });

  test('lists a weight the saved workout has and the proposal drops, and marks the exercise as changed', () => {
    const dropped = proposalCardData(mockWeightDropProposal(NOW, 4), NOW);

    expect(dropped.keyChangeLines).toContain('Goblet Squat: 20 kg → no weight');
    const squat = dropped.sections.find((section) => section.id === 'MAIN_WORKOUT')!.exercises.find((exercise) => exercise.name === 'Goblet Squat');
    expect(squat?.mark).toBe('changed');
  });

  test("takes everything from the backend's answer: the card of a proposal with no changes lists none, whatever else it holds", () => {
    const proposal = mockProposal('edit', NOW, 2);
    // nothing differs: no exercise, not the name, not the day
    const nothing = proposalCardData(
      { ...proposal, changes: { ...proposal.changes!, added: [], removed: [], changed: [], name_changed: false, scheduled_date_changed: false, identical: true } },
      NOW,
    );

    expect(nothing.keyChanges.filter((change) => change.kind !== 'duration')).toEqual([]);
  });

  describe('when the backend could not compare it with the saved workout', () => {
    const unread = proposalCardData(mockUncomparedProposal(NOW, 2), NOW);

    test('says so, lists no changes and marks no exercise, but still shows the proposal and what it replaces', () => {
      expect(unread.comparison).toBe('unavailable');
      expect(unread.keyChanges).toEqual([]);
      expect(unread.sections.flatMap((section) => section.exercises).every((exercise) => exercise.mark === null)).toBe(true);
      expect(unread.replaces?.name).toBe('Core & Abs Focus');
      expect(unread.title).toBe('Core Stability & Abs');
    });

    test('says nothing of the length either', () => {
      expect(unread.keyChangeLines).toEqual([]);
    });
  });
});

describe('a workout the catalog could not fully cover', () => {
  test('carries the backend\'s own words for what is missing', () => {
    const card = proposalCardData(mockIncompleteProposal(NOW, 5), NOW);

    expect(card.coverageNotes).toEqual(["Formiq's catalog has no pulling exercise you can do without a pull-up bar."]);
  });

  test('has no note when the workout is complete, even if limitations were listed', () => {
    const proposal = mockProposal('new', NOW, 1);
    const card = proposalCardData(
      { ...proposal, coverage: { ...proposal.coverage, complete: true, limitations: [{ code: 'NO_SUITABLE_EXERCISE', region: null, message: 'x' }] } },
      NOW,
    );

    expect(card.coverageNotes).toEqual([]);
  });
});

describe('numbers the proposal gives that cannot be shown', () => {
  test('a length that is not a positive whole number is left out, and so is a section\'s', () => {
    const proposal = mockProposal('new', NOW, 1);
    const card = proposalCardData({ ...proposal, estimated_minutes: 0, cool_down_minutes: 0 }, NOW);

    expect(card.minutes).toBeNull();
    expect(card.sections.find((section) => section.id === 'COOL_DOWN')!.minutes).toBeNull();
  });

  test('a section with no exercise is not shown', () => {
    const proposal = mockProposal('new', NOW, 1);
    const card = proposalCardData({ ...proposal, exercises: proposal.exercises.filter((exercise) => exercise.section !== 'COOL_DOWN') }, NOW);

    expect(card.sections.map((section) => section.id)).toEqual(['WARM_UP', 'MAIN_WORKOUT']);
  });
});

describe('the workout the conversation is about', () => {
  const edit = mockProposal('edit', NOW, 2);

  test('is named when the proposal replaces a different saved workout, so the card can say it is not that one', () => {
    const card = proposalCardData(edit, NOW, { planId: MOCK_REPLACED_PLAN_ID + 1, title: 'Leg Day' });

    expect(card.offTarget).toBe('Leg Day');
    expect(card.replaces?.planId).toBe(MOCK_REPLACED_PLAN_ID);
  });

  test('is not mentioned when the proposal replaces that very workout', () => {
    expect(proposalCardData(edit, NOW, { planId: MOCK_REPLACED_PLAN_ID, title: 'Core & Abs Focus' }).offTarget).toBeNull();
  });

  test('is not mentioned for a new workout, which replaces nothing', () => {
    expect(proposalCardData(mockProposal('new', NOW, 1), NOW, { planId: 9, title: 'Leg Day' }).offTarget).toBeNull();
  });

  test('is not mentioned when the conversation is about no workout', () => {
    expect(proposalCardData(edit, NOW).offTarget).toBeNull();
  });
});

describe('the weight of an exercise', () => {
  // the proposal's main exercises, with the weights the test gives them (kilograms; null is no weight)
  const withWeights = (weights: Record<string, number | null>): WorkoutProposal => {
    const proposal = mockProposal('new', NOW, 1);
    return { ...proposal, exercises: proposal.exercises.map((exercise) => ({ ...exercise, weight_kg: weights[exercise.exercise_name] ?? null })) };
  };
  const lineOf = (proposal: WorkoutProposal, name: string) =>
    proposalCardData(proposal, NOW).sections.flatMap((section) => section.exercises).find((exercise) => exercise.name === name)!.prescription;

  test('is shown after the target and before the rest, in kilograms', () => {
    const proposal = withWeights({ 'Dumbbell Shoulder Press': 20, 'Dumbbell Biceps Curl': 12.5 });

    expect(lineOf(proposal, 'Dumbbell Shoulder Press')).toBe('3 sets • 10 reps • 20 kg • 60 s rest');
    expect(lineOf(proposal, 'Dumbbell Biceps Curl')).toBe('3 sets • 12 reps • 12.5 kg • 60 s rest');
  });

  test('goes with a timed target as well, and with no rest', () => {
    const proposal = mockProposal('new', NOW, 1);
    const timed = { ...proposal, exercises: proposal.exercises.map((exercise) => (exercise.exercise_name === 'Arm Circles' ? { ...exercise, weight_kg: 2 } : exercise)) };

    expect(lineOf(timed, 'Arm Circles')).toBe('2 sets • 30 seconds • 2 kg');
  });

  test('with none, the line is as it always was', () => {
    const proposal = withWeights({});

    expect(lineOf(proposal, 'Push-Up')).toBe('3 sets • 12 reps • 60 s rest');
    expect(lineOf(proposal, 'Dumbbell Shoulder Press')).toBe('3 sets • 10 reps • 60 s rest');
    expect(JSON.stringify(proposalCardData(proposal, NOW).sections)).not.toMatch(/\bkg\b/);
  });

  test('a weight change the backend lists reads as the exercise changed, with the new weight on its row', () => {
    const proposal = mockProposal('edit', NOW, 2);
    const before: Prescription = { sets: 3, reps: null, duration_seconds: 40, rest_seconds: 45, weight_kg: 15, summary: '3 sets of 40 s at 15 kg, 45 s rest' };
    const after: Prescription = { ...before, weight_kg: 20, summary: '3 sets of 40 s at 20 kg, 45 s rest' };
    const change: ExerciseChange = { section: 'MAIN_WORKOUT', exercise_name: 'Plank', before, after };
    const weightOnly: WorkoutProposal = {
      ...proposal,
      exercises: proposal.exercises.map((exercise) => (exercise.exercise_name === 'Plank' ? { ...exercise, weight_kg: 20 } : exercise)),
      changes: { ...proposal.changes!, added: [], removed: [], changed: [change], unchanged: ['Mountain Climbers', 'Lunges', 'Dead Bug', 'Side Plank', 'Hamstring Stretch'], name_changed: false, identical: false },
    };

    const card = proposalCardData(weightOnly, NOW);

    expect(card.keyChangeLines).toEqual(['Plank: 15 kg → 20 kg', 'Kept the same duration (18 min)']);
    const plank = card.sections.find((section) => section.id === 'MAIN_WORKOUT')!.exercises.find((exercise) => exercise.name === 'Plank')!;
    expect(plank.mark).toBe('changed');
    expect(plank.prescription).toBe('3 sets • 40 seconds • 20 kg • 45 s rest');
  });
});

describe('a proposal that only moves the workout to another day, or only renames it', () => {
  const edit = mockProposal('edit', NOW, 2);
  // every exercise is as the saved plan has it: the backend says identical: true, with the day or the name flagged
  const sameExercises = (overrides: Partial<NonNullable<WorkoutProposal['changes']>>, proposal: Partial<WorkoutProposal> = {}): WorkoutProposal => ({
    ...edit,
    ...proposal,
    changes: {
      ...edit.changes!,
      added: [],
      removed: [],
      changed: [],
      unchanged: edit.exercises.map((exercise) => exercise.exercise_name),
      name_changed: false,
      scheduled_date_changed: false,
      identical: true,
      ...overrides,
    },
  });

  test('a day-only move lists the move, and is not a card with no changes', () => {
    const card = proposalCardData(sameExercises({ scheduled_date_changed: true, compared_with_scheduled_date: '2026-10-21' }, { name: 'Core & Abs Focus', scheduled_date: '2026-10-23' }), NOW);

    expect(card.comparison).toBe('compared');
    expect(card.keyChangeLines).toEqual(['Kept the same duration (18 min)', 'Moved from Wed, 21 Oct to Fri, 23 Oct']);
    expect(card.sections.flatMap((section) => section.exercises).every((exercise) => exercise.mark === null)).toBe(true);
  });

  test('a rename alone lists the rename', () => {
    const card = proposalCardData(sameExercises({ name_changed: true }), NOW);

    expect(card.keyChangeLines).toEqual(['Kept the same duration (18 min)', 'Renamed from “Core & Abs Focus” to “Core Stability & Abs”']);
  });

  test('a name that only decorates the saved one is not listed as a rename (the title carries it)', () => {
    const card = proposalCardData(sameExercises({ name_changed: true }, { name: 'Core & Abs Focus (Harder)' }), NOW);

    expect(card.title).toBe('Core & Abs Focus (Harder)');
    expect(card.keyChangeLines).toEqual(['Kept the same duration (18 min)']);
  });

  test('no change at all (identical true or false) lists none, except the length it kept', () => {
    for (const identical of [true, false]) {
      const card = proposalCardData(sameExercises({ identical }), NOW);

      expect(card.keyChangeLines).toEqual(['Kept the same duration (18 min)']);
    }
  });
});
