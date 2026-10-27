// MOCK DATA: nothing in this file comes from the Formiq backend or from a language model.
//
// Mock mode and the tests of the AI Coach's workout card use these made-up proposals, so its states and its
// lifecycle can be looked at without a backend. They have the exact SHAPE of the backend's answers
// (WorkoutProposal, WorkoutPlan: src/api/types.ts), so the card is fed by the same types in the connected app.
// Nothing in them is a user's workout.
//
// Four proposals, matching the four things a person does:
//   new           "Create a 25-minute upper-body workout": a new workout (no `revision`)
//   new-refined   what the coach answers when that one is changed ("use no equipment"): still a new workout
//   edit          "Suggest a different ab workout for today": revises the saved plan below (`revision` set)
//   edit-refined  what the coach answers when that is changed ("easier on my knees"): revises the same plan
//
// The minutes are what the backend's own formula gives for these exercises (app/tools/comparison.py
// `section_minutes`: each set and the rest after it; 45 s a set of reps, 3 s a rep when longer, 90 s default main
// rest), so the figures are ones Formiq could produce. The saved plan the edits revise takes 18 minutes by that
// formula, which the proposals say (`revision.replaces_plan_estimated_minutes`) as the backend does.
//
// `changes` is what the backend's comparison would answer for each edit against the saved plan below (the backend
// works it out, never the app): MOCK stand-in, so the card can be looked at and tested without a backend. It is
// built here from the same specs, by the same section-and-name matching and the same one-line wording of a
// prescription, and nowhere else: no screen or reducer of the app compares workouts.
//
// What the replies say about the proposals is what a real reply may say: that here is a workout, how long it
// takes, what it swaps, and that it replaces a saved one only if applied. Never that it was made, saved or
// changed. Those claims are refused by the backend's own reply checks (docs/agent-production-contract.md).

import type {
  ExerciseChange,
  PendingProposal,
  PlanExercise,
  PlanSectionName,
  Prescription,
  ProposalChanges,
  ProposedExercise,
  SessionFocus,
  WorkoutPlan,
  WorkoutProposal,
} from '../api';
import { localDateKey } from '../home/format';

export type MockScenario = 'new' | 'new-refined' | 'edit' | 'edit-refined';

// The saved plan the two edits revise. It is the workout Home's mock shows as today's.
export const MOCK_REPLACED_PLAN_ID = 41;
export const MOCK_REPLACED_PLAN_NAME = 'Core & Abs Focus';

// the catalog ids of the exercises used below: the same exercise has the same id in every plan
const EXERCISE_IDS: Record<string, number> = {
  'Arm Circles': 301,
  'Jumping Jacks': 302,
  'Push-Up': 303,
  'Dumbbell Bent-Over Row': 304,
  'Dumbbell Shoulder Press': 305,
  'Dumbbell Biceps Curl': 306,
  'Doorway Chest Stretch': 307,
  'Cross-Body Shoulder Stretch': 308,
  'Pike Push-Up': 309,
  'Plank Shoulder Tap': 310,
  'Diamond Push-Up': 311,
  'Mountain Climbers': 101,
  Lunges: 102,
  Plank: 103,
  'Bicycle Crunches': 104,
  'Leg Raises': 105,
  'Hamstring Stretch': 106,
  'Dead Bug': 107,
  'Side Plank': 108,
  'Cat-Cow Stretch': 109,
  'Glute Bridge': 110,
  'Reverse Crunch': 111,
};

type Spec = {
  section: PlanSectionName;
  name: string;
  sets: number;
  // one target per set: reps, or seconds
  reps?: number;
  seconds?: number;
  rest?: number;
  equipment?: string[];
};

const warm = (name: string, sets: number, target: Pick<Spec, 'reps' | 'seconds'>): Spec => ({ section: 'WARM_UP', name, sets, ...target });
const main = (name: string, sets: number, target: Pick<Spec, 'reps' | 'seconds'>, rest: number, equipment: string[] = []): Spec => ({
  section: 'MAIN_WORKOUT',
  name,
  sets,
  rest,
  equipment,
  ...target,
});
const cool = (name: string, sets: number, target: Pick<Spec, 'reps' | 'seconds'>): Spec => ({ section: 'COOL_DOWN', name, sets, ...target });

const WORKOUTS: Record<
  MockScenario,
  { name: string; focus: SessionFocus; minutes: [number, number, number]; specs: Spec[]; revises: boolean; kept: string[]; reply: string }
> = {
  new: {
    name: 'Upper Body Strength',
    focus: 'UPPER_BODY',
    minutes: [2, 21, 1],
    revises: false,
    kept: [],
    specs: [
      warm('Arm Circles', 2, { seconds: 30 }),
      warm('Jumping Jacks', 2, { seconds: 30 }),
      main('Push-Up', 3, { reps: 12 }, 60),
      main('Dumbbell Bent-Over Row', 3, { reps: 12 }, 60, ['Dumbbell']),
      main('Dumbbell Shoulder Press', 3, { reps: 10 }, 60, ['Dumbbell']),
      main('Dumbbell Biceps Curl', 3, { reps: 12 }, 60, ['Dumbbell']),
      cool('Doorway Chest Stretch', 1, { seconds: 30 }),
      cool('Cross-Body Shoulder Stretch', 1, { seconds: 30 }),
    ],
    reply:
      "Here's an upper-body workout of about 24 minutes: a short warm-up, four main exercises for chest, back, shoulders and arms, and two stretches to finish. It isn't saved until you apply it.",
  },
  'new-refined': {
    name: 'Upper Body, No Equipment',
    focus: 'UPPER_BODY',
    minutes: [2, 22, 1],
    revises: false,
    kept: [],
    specs: [
      warm('Arm Circles', 2, { seconds: 30 }),
      warm('Jumping Jacks', 2, { seconds: 30 }),
      main('Push-Up', 3, { reps: 12 }, 60),
      main('Pike Push-Up', 3, { reps: 10 }, 60),
      main('Plank Shoulder Tap', 3, { reps: 16 }, 60),
      main('Diamond Push-Up', 3, { reps: 8 }, 60),
      cool('Doorway Chest Stretch', 1, { seconds: 30 }),
      cool('Cross-Body Shoulder Stretch', 1, { seconds: 30 }),
    ],
    reply:
      "Here's another version that needs no equipment, about 25 minutes. Nothing is saved until you apply it.",
  },
  edit: {
    name: 'Core Stability & Abs',
    focus: 'CORE',
    minutes: [3, 14, 1],
    revises: true,
    kept: ['Plank'],
    specs: [
      warm('Mountain Climbers', 2, { seconds: 30 }),
      warm('Lunges', 2, { reps: 10 }),
      main('Plank', 3, { seconds: 40 }, 45),
      main('Dead Bug', 3, { reps: 12 }, 60),
      main('Side Plank', 3, { seconds: 30 }, 60),
      cool('Hamstring Stretch', 1, { seconds: 30 }),
    ],
    reply:
      "Here's a different ab workout of about 18 minutes. It swaps two of the main exercises and holds the plank a little longer. It replaces Core & Abs Focus only if you apply it.",
  },
  'edit-refined': {
    name: 'Gentle Core & Abs',
    focus: 'CORE',
    minutes: [3, 14, 1],
    revises: true,
    kept: ['Plank'],
    specs: [
      warm('Cat-Cow Stretch', 2, { seconds: 30 }),
      warm('Glute Bridge', 2, { reps: 12 }),
      main('Plank', 3, { seconds: 30 }, 45),
      main('Dead Bug', 3, { reps: 12 }, 45),
      main('Reverse Crunch', 3, { reps: 12 }, 60),
      cool('Hamstring Stretch', 1, { seconds: 30 }),
    ],
    reply:
      "Here's a gentler version for your knees: no jumping and no lunges, and still about 18 minutes. It replaces Core & Abs Focus only if you apply it.",
  },
};

export const mockReplyFor = (scenario: MockScenario): string => WORKOUTS[scenario].reply;

// The saved plan the edits revise: today's "Core & Abs Focus", as the backend would return it.
const REPLACED_SPECS: Spec[] = [
  warm('Mountain Climbers', 2, { seconds: 30 }),
  warm('Lunges', 2, { reps: 10 }),
  main('Plank', 3, { seconds: 30 }, 45),
  main('Bicycle Crunches', 3, { reps: 20 }, 45),
  main('Leg Raises', 3, { reps: 15 }, 45),
  cool('Hamstring Stretch', 1, { seconds: 30 }),
];

// The minutes the backend's formula gives the saved plan above (app/tools/comparison.py): 3 + 14 + 1.
export const MOCK_REPLACED_PLAN_MINUTES = 18;

// The backend's one-line wording of a prescription: "3 sets of 30 s, 45 s rest".
function wording(spec: Pick<Spec, 'sets' | 'reps' | 'seconds' | 'rest'>, weightKg: number | null = null): string {
  const target = spec.reps !== undefined ? `${spec.reps} reps` : `${spec.seconds} s`;
  const weight = weightKg === null ? '' : ` at ${weightKg} kg`;
  return `${spec.sets} ${spec.sets === 1 ? 'set' : 'sets'} of ${target}${weight}${spec.rest ? `, ${spec.rest} s rest` : ''}`;
}

export function mockPrescription(spec: Pick<Spec, 'sets' | 'reps' | 'seconds' | 'rest'>, weightKg: number | null = null): Prescription {
  return {
    sets: spec.sets,
    reps: spec.reps ?? null,
    duration_seconds: spec.seconds ?? null,
    rest_seconds: spec.rest ?? null,
    weight_kg: weightKg,
    summary: wording(spec, weightKg),
  };
}

// What the backend's comparison answers for an edit with these exercises against the saved plan above.
function mockChanges(specs: readonly Spec[], name: string, scheduledDate: string, now: Date): ProposalChanges {
  const unmatched = [...REPLACED_SPECS];
  const added: ExerciseChange[] = [];
  const changed: ExerciseChange[] = [];
  const unchanged: string[] = [];
  for (const spec of specs) {
    const at = unmatched.findIndex((item) => item.section === spec.section && item.name === spec.name);
    if (at < 0) {
      added.push({ section: spec.section, exercise_name: spec.name, before: null, after: mockPrescription(spec) });
      continue;
    }
    const [same] = unmatched.splice(at, 1);
    if (wording(same) === wording(spec)) unchanged.push(spec.name);
    else changed.push({ section: spec.section, exercise_name: spec.name, before: mockPrescription(same), after: mockPrescription(spec) });
  }
  const removed = unmatched.map((item): ExerciseChange => ({ section: item.section, exercise_name: item.name, before: mockPrescription(item), after: null }));
  const date = localDateKey(now);
  return {
    compared_with_plan_id: MOCK_REPLACED_PLAN_ID,
    compared_with_plan_name: MOCK_REPLACED_PLAN_NAME,
    compared_with_scheduled_date: date,
    added,
    removed,
    changed,
    unchanged,
    name_changed: name !== MOCK_REPLACED_PLAN_NAME,
    scheduled_date_changed: scheduledDate !== date,
    identical: added.length === 0 && removed.length === 0 && changed.length === 0,
  };
}

const hex = (value: number, length: number) => value.toString(16).padStart(length, '0');

const isoAfter = (now: Date, minutes: number) => new Date(now.getTime() + minutes * 60_000).toISOString();

// The proposal for a scenario, scheduled for the device's today and open for 30 minutes (the backend's own
// term). `sequence` makes each proposal's id and binding its own, as the backend's are.
export function mockProposal(scenario: MockScenario, now: Date, sequence: number): WorkoutProposal {
  const workout = WORKOUTS[scenario];
  const exercises: ProposedExercise[] = workout.specs.map((spec, index) => ({
    exercise_order: index + 1,
    section: spec.section,
    exercise_id: EXERCISE_IDS[spec.name],
    exercise_name: spec.name,
    equipment: spec.equipment ?? [],
    sets: spec.sets,
    reps: spec.reps ?? null,
    duration_seconds: spec.seconds ?? null,
    rest_seconds: spec.rest ?? null,
    // a proposal made by this mock sets no weight
    weight_kg: null,
    notes: null,
  }));
  const [warmUp, mainMinutes, coolDown] = workout.minutes;
  return {
    proposal_id: hex(sequence, 32),
    binding: hex(sequence, 64),
    expires_at: isoAfter(now, 30),
    name: workout.name,
    scheduled_date: localDateKey(now),
    exercises,
    warm_up_minutes: warmUp,
    main_minutes: mainMinutes,
    cool_down_minutes: coolDown,
    estimated_minutes: warmUp + mainMinutes + coolDown,
    coverage: {
      complete: true,
      focus: workout.focus,
      trained_regions: workout.focus === 'CORE' ? ['CORE'] : ['UPPER_PUSH', 'UPPER_PULL'],
      missing_regions: [],
      main_exercises_counted: workout.specs.filter((spec) => spec.section === 'MAIN_WORKOUT').length,
      main_exercises_required: 3,
      limitations: [],
    },
    revision: workout.revises
      ? {
          replaces_plan_id: MOCK_REPLACED_PLAN_ID,
          replaces_plan_name: MOCK_REPLACED_PLAN_NAME,
          kind: 'ALTERNATIVE',
          kept_exercises: workout.kept,
          replaces_plan_estimated_minutes: MOCK_REPLACED_PLAN_MINUTES,
        }
      : null,
    changes: workout.revises ? mockChanges(workout.specs, workout.name, localDateKey(now), now) : null,
  };
}

// A proposal as the backend would answer when it could not compare it with the plan it replaces (the plan is not as it
// was when proposed): the revision is there, its length and the comparison are not.
export function mockUncomparedProposal(now: Date, sequence: number): WorkoutProposal {
  const proposal = mockProposal('edit', now, sequence);
  return {
    ...proposal,
    revision: proposal.revision && { ...proposal.revision, replaces_plan_estimated_minutes: null },
    changes: null,
  };
}

// An edit that also drops a weight the saved plan has on an exercise it keeps: the backend lists it as a change, as it
// would any other (a proposal sets no weight).
export function mockWeightDropProposal(now: Date, sequence: number): WorkoutProposal {
  const proposal = mockProposal('edit', now, sequence);
  const squat: Spec = main('Goblet Squat', 3, { reps: 10 }, 60, ['Kettlebell']);
  const exercises: ProposedExercise[] = [
    ...proposal.exercises,
    {
      exercise_order: proposal.exercises.length + 1,
      section: 'MAIN_WORKOUT',
      exercise_id: 312,
      exercise_name: squat.name,
      equipment: squat.equipment ?? [],
      sets: squat.sets,
      reps: squat.reps ?? null,
      duration_seconds: null,
      rest_seconds: squat.rest ?? null,
      weight_kg: null,
      notes: null,
    },
  ];
  const changes = proposal.changes as ProposalChanges;
  return {
    ...proposal,
    exercises,
    changes: {
      ...changes,
      changed: [
        ...changes.changed,
        { section: 'MAIN_WORKOUT', exercise_name: squat.name, before: mockPrescription(squat, 20), after: mockPrescription(squat) },
      ],
      unchanged: changes.unchanged.filter((name) => name !== squat.name),
    },
  };
}

// A proposal as GET /coach/proposals/pending lists it: the proposal and when it was made. It was made `minutesAgo`
// before `now`, so it expires 30 minutes after that.
export function mockPendingProposal(scenario: MockScenario, now: Date, sequence: number, minutesAgo: number): PendingProposal {
  const madeAt = new Date(now.getTime() - minutesAgo * 60_000);
  return { ...mockProposal(scenario, madeAt, sequence), created_at: madeAt.toISOString() };
}

const planExercise = (id: number, order: number, spec: Spec): PlanExercise => ({
  id,
  exercise_order: order,
  section: spec.section,
  sets: spec.sets,
  reps: spec.reps ?? null,
  duration_seconds: spec.seconds ?? null,
  weight_kg: null,
  rest_seconds: spec.rest ?? null,
  notes: null,
  exercise: { name: spec.name, description: null, instructions: [] },
});

// The saved plan the edits revise: today's "Core & Abs Focus", PLANNED, as the backend would return it.
export function mockReplacedPlan(now: Date): WorkoutPlan {
  const specs = REPLACED_SPECS;
  return {
    id: MOCK_REPLACED_PLAN_ID,
    name: MOCK_REPLACED_PLAN_NAME,
    description: 'Strengthen your core and improve stability.',
    status: 'PLANNED',
    scheduled_date: localDateKey(now),
    exercises: specs.map((spec, index) => planExercise(4100 + index + 1, index + 1, spec)),
  };
}

// What approving a proposal saves: a new PLANNED plan with the proposal's own exercises, as the backend returns it.
export function mockSavedPlan(proposal: WorkoutProposal, planId: number): WorkoutPlan {
  return {
    id: planId,
    name: proposal.name,
    description: null,
    status: 'PLANNED',
    scheduled_date: proposal.scheduled_date,
    exercises: proposal.exercises.map((exercise, index) => ({
      id: planId * 100 + index + 1,
      exercise_order: exercise.exercise_order,
      section: exercise.section,
      sets: exercise.sets,
      reps: exercise.reps,
      duration_seconds: exercise.duration_seconds,
      // the saved plan carries the weight the proposal prescribed
      weight_kg: exercise.weight_kg,
      rest_seconds: exercise.rest_seconds,
      notes: exercise.notes,
      exercise: { name: exercise.exercise_name, description: null, instructions: [] },
    })),
  };
}

// A proposal whose focus the catalog could not fully cover, as the backend says so (coverage.complete false), for
// the card's note about it.
export function mockIncompleteProposal(now: Date, sequence: number): WorkoutProposal {
  const proposal = mockProposal('new', now, sequence);
  return {
    ...proposal,
    exercises: proposal.exercises.filter((exercise) => exercise.exercise_name !== 'Dumbbell Biceps Curl'),
    coverage: {
      ...proposal.coverage,
      complete: false,
      trained_regions: ['UPPER_PUSH'],
      missing_regions: ['UPPER_PULL'],
      main_exercises_counted: 3,
      limitations: [
        {
          code: 'NO_SUITABLE_EXERCISE',
          region: 'UPPER_PULL',
          message: "Formiq's catalog has no pulling exercise you can do without a pull-up bar.",
        },
      ],
    },
  };
}
