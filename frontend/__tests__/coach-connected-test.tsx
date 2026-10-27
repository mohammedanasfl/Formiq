import { act, fireEvent, screen, waitFor, within } from '@testing-library/react-native';

import { AppShell } from '../src/shell/AppShell';
import { fixClockAt } from '../test-utils/clock';
import { fakeToken, installMockFetch, type MockFetch, type Reply } from '../test-utils/mockFetch';
import { renderWithTheme } from '../test-utils/renderWithTheme';
import { backendWorkouts, corePlan, NOW, readsMade, TODAY, type WorkoutAnswers } from '../test-utils/workoutFixtures';
import golden from './fixtures/coach-message-responses.json';
import pendings from './fixtures/pending-proposals-responses.json';
import savedPlan from './fixtures/saved-plan-response.json';

// The device's time zone goes with every coach message (Phase 2.7). A fixed one here, so what is sent is the same on every
// machine; `Intl` itself is left alone because the screens format dates with it.
const ZONE = 'Asia/Kolkata';
jest.mock('../src/api/timeZone', () => ({ deviceTimeZone: () => 'Asia/Kolkata' }));

// The AI Coach tab on the backend, end to end up to the network: the real screen, the real gateway and the real API
// client, with a scripted `fetch` standing in for Formiq. No test here reaches a backend, a language model or a
// database.

const SESSION = { token: fakeToken(7), userId: 7 };
const PLANS = '/users/7/workout-plans';
const REVISION_ID = 'a'.repeat(32);
const REVISION_BINDING = 'b'.repeat(64);
const NEW_ID = 'c'.repeat(32);
const NEW_BINDING = 'd'.repeat(64);
const REFINED_ID = 'e'.repeat(32);
const REFINED_BINDING = 'f'.repeat(64);
const approvePath = (id: string) => `/coach/proposals/${id}/approve`;
const rejectPath = (id: string) => `/coach/proposals/${id}/reject`;
const PENDING = '/coach/proposals/pending';

let backend: MockFetch;
let clock: ReturnType<typeof fixClockAt>;
// what the reads Home makes answer: a test changes it to say what the backend holds after something was saved
let homeAnswers: WorkoutAnswers;
// what the list of proposals waiting answers, read when each request arrives: nothing, unless a test says so
type PendingAnswer = Reply | (() => Reply | Promise<Reply>);
let pendingAnswer: PendingAnswer;
const answerPending = (answer: PendingAnswer) => {
  pendingAnswer = answer;
};

beforeEach(() => {
  backend = installMockFetch();
  clock = fixClockAt(NOW);
  homeAnswers = backendWorkouts(backend, SESSION.userId, { plans: [corePlan()] });
  pendingAnswer = { status: 200, body: { proposals: [] } };
  backend.on('GET', PENDING, () => (typeof pendingAnswer === 'function' ? pendingAnswer() : pendingAnswer));
});

afterEach(() => {
  jest.restoreAllMocks();
  clock.restore();
});

type Exercise = (typeof golden.reply_with_revision.proposal.exercises)[number];
const exercise = (order: number, section: Exercise['section'], id: number, name: string, sets: number, target: { reps?: number; seconds?: number }): Exercise => ({
  exercise_order: order,
  section,
  exercise_id: id,
  exercise_name: name,
  equipment: [],
  sets,
  reps: (target.reps ?? null) as never,
  duration_seconds: (target.seconds ?? null) as never,
  rest_seconds: 60 as never,
  weight_kg: null as never,
  notes: null as never,
});

const prescription = (sets: number, target: { reps?: number; seconds?: number }) => ({
  sets,
  reps: target.reps ?? null,
  duration_seconds: target.seconds ?? null,
  rest_seconds: 60,
  weight_kg: null,
  summary: `${sets} sets of ${target.reps !== undefined ? `${target.reps} reps` : `${target.seconds} s`}, 60 s rest`,
});

// What the coach proposes for "Core & Abs Focus" (the plan Home shows, id 41): Plank held longer, Bicycle Crunch
// replaced by Side Plank, the rest as it was. The backend's own response model wrote the fixture; only the exercises,
// the day and the ids are the test's. `changes` is what the backend's comparison would say about exactly this (the app
// works none of it out: it is part of the proposal), and `replaces_plan_estimated_minutes` how long Core & Abs Focus takes.
function revisionReply(options: { id?: string; binding?: string; plankSeconds?: number; reply?: string } = {}) {
  const body = JSON.parse(JSON.stringify(golden.reply_with_revision));
  const plank = options.plankSeconds ?? 40;
  body.reply = options.reply ?? 'Here is an updated version.';
  body.proposal.proposal_id = options.id ?? REVISION_ID;
  body.proposal.binding = options.binding ?? REVISION_BINDING;
  body.proposal.scheduled_date = TODAY;
  body.proposal.exercises = [
    exercise(1, 'WARM_UP', 1, 'Mountain Climbers', 2, { seconds: 30 }),
    exercise(2, 'WARM_UP', 2, 'Lunges', 2, { reps: 10 }),
    exercise(3, 'MAIN_WORKOUT', 3, 'Plank', 3, { seconds: plank }),
    exercise(4, 'MAIN_WORKOUT', 4, 'Dead Bug', 3, { reps: 12 }),
    exercise(5, 'MAIN_WORKOUT', 6, 'Side Plank', 3, { seconds: 30 }),
    exercise(6, 'COOL_DOWN', 7, 'Hamstring Stretch', 1, { seconds: 30 }),
  ];
  body.proposal.coverage.focus = 'CORE';
  body.proposal.revision.replaces_plan_estimated_minutes = 17;
  body.proposal.changes = {
    compared_with_plan_id: 41,
    compared_with_plan_name: 'Core & Abs Focus',
    compared_with_scheduled_date: TODAY,
    added: [{ section: 'MAIN_WORKOUT', exercise_name: 'Side Plank', before: null, after: prescription(3, { seconds: 30 }) }],
    removed: [{ section: 'MAIN_WORKOUT', exercise_name: 'Bicycle Crunch', before: prescription(3, { reps: 16 }), after: null }],
    changed:
      plank === 30 ? [] : [{ section: 'MAIN_WORKOUT', exercise_name: 'Plank', before: prescription(3, { seconds: 30 }), after: prescription(3, { seconds: plank }) }],
    unchanged: ['Mountain Climbers', 'Lunges', 'Dead Bug', 'Hamstring Stretch'],
    name_changed: true,
    scheduled_date_changed: false,
    identical: false,
  };
  return body;
}

// A revision that keeps every exercise of "Core & Abs Focus" as it is, so what differs is one thing the test chooses. The
// proposal's exercises are the saved plan's (and the saved plan is 17 minutes, as the other revision's reply says).
function sameExercisesReply(overrides: { name?: string; day?: string; changes?: Record<string, unknown>; exercises?: (items: Exercise[]) => Exercise[] } = {}) {
  const body = revisionReply({ plankSeconds: 30 });
  const exercises = [
    exercise(1, 'WARM_UP', 1, 'Mountain Climbers', 2, { seconds: 30 }),
    exercise(2, 'WARM_UP', 2, 'Lunges', 2, { reps: 10 }),
    exercise(3, 'MAIN_WORKOUT', 3, 'Plank', 3, { seconds: 30 }),
    exercise(4, 'MAIN_WORKOUT', 5, 'Bicycle Crunch', 3, { reps: 16 }),
    exercise(5, 'MAIN_WORKOUT', 4, 'Dead Bug', 3, { reps: 12 }),
    exercise(6, 'COOL_DOWN', 7, 'Hamstring Stretch', 1, { seconds: 30 }),
  ];
  body.proposal.name = overrides.name ?? 'Core & Abs Focus';
  body.proposal.scheduled_date = overrides.day ?? TODAY;
  body.proposal.exercises = overrides.exercises ? overrides.exercises(exercises) : exercises;
  body.proposal.revision.replaces_plan_estimated_minutes = body.proposal.estimated_minutes;
  body.proposal.changes = {
    compared_with_plan_id: 41,
    compared_with_plan_name: 'Core & Abs Focus',
    compared_with_scheduled_date: TODAY,
    added: [],
    removed: [],
    changed: [],
    unchanged: exercises.map((item) => item.exercise_name),
    name_changed: false,
    scheduled_date_changed: false,
    identical: true,
    ...overrides.changes,
  };
  return body;
}

function newWorkoutReply() {
  const body = JSON.parse(JSON.stringify(golden.reply_with_new_workout));
  body.proposal.scheduled_date = TODAY;
  return body;
}

// a reply the test releases when it chooses, to look at the screen while the backend is still working
function held() {
  let release!: (reply: Reply) => void;
  const promise = new Promise<Reply>((resolve) => (release = resolve));
  return { responder: () => promise, release };
}

const savedAs = (name = 'Core Stability & Abs') => ({ ...savedPlan, name, scheduled_date: TODAY });

// lets what is already on its way (an answer that was released) arrive
const flush = () => new Promise<void>((resolve) => setImmediate(() => resolve()));

const tab = (name: string) => screen.getByRole('tab', { name });
const button = (name: string | RegExp) => screen.getByRole('button', { name });
const status = () => within(screen.getByTestId('proposal-status'));
const messagesToCoach = () => backend.requests.filter((request) => request.path === '/coach/message');
const approvals = () => backend.requests.filter((request) => request.path.endsWith('/approve'));
const rejections = () => backend.requests.filter((request) => request.path.endsWith('/reject'));
const listings = () => backend.requests.filter((request) => request.path === PENDING);
// anything the app sent that is not a read, a message to the coach, an approval or a rejection would be a write it made itself
const writes = () =>
  backend.requests.filter(
    (request) => request.method !== 'GET' && request.path !== '/coach/message' && !request.path.endsWith('/approve') && !request.path.endsWith('/reject'),
  );
// the reads of a saved plan by its id: the app makes none, since what a proposal changes comes in the proposal
const planReads = () => readsMade(backend).filter((read) => read.includes(`${PLANS}/`));

async function renderApp(scheme: 'dark' | 'light' = 'dark') {
  const view = await renderWithTheme(<AppShell session={SESSION} onSignOut={jest.fn()} coachMode="api" />, scheme);
  await screen.findByTestId('workout-card-41');
  return view;
}

async function openCoach() {
  await fireEvent.press(tab('AI Coach'));
}

// Home, today's workout, "Edit with AI"
async function editTodaysWorkout() {
  await fireEvent.press(screen.getByRole('button', { name: /^Core & Abs Focus/ }));
  await fireEvent.press(button('Edit with AI'));
}

async function say(text: string) {
  await fireEvent.changeText(screen.getByLabelText('Message'), text);
  await fireEvent.press(button('Send message'));
}

describe('opening the coach', () => {
  test('asks the coach nothing: it is only asked when the person says something, and the only read is of what is waiting', async () => {
    await renderApp();
    const before = backend.requests.length;

    await openCoach();

    expect(screen.getByTestId('coach-screen')).toBeOnTheScreen();
    expect(backend.requests.slice(before).map((request) => `${request.method} ${request.path}`)).toEqual([`GET ${PENDING}`]);
    expect(backend.requests.slice(before)[0].headers.Authorization).toBe(`Bearer ${SESSION.token}`);
    expect(messagesToCoach()).toHaveLength(0);
    expect(writes()).toEqual([]);
  });

  test('opens with a greeting of its own and ways to ask, and none of the design phase\'s made-up conversation', async () => {
    await renderApp();

    await openCoach();

    screen.getByText(/I'm Formiq Coach/);
    button('Create a 25-minute upper-body workout');
    button('Suggest a different workout for today');
    expect(screen.queryByText('Can I get a different ab workout?')).toBeNull();
    expect(screen.queryByText(/This is a preview/)).toBeNull();
  });
});

// Opening the coach for a workout shows the tab and hands it the workout in one render. Which proposals wait is read once
// for that opening, whether the coach is opened for the first time or was opened on its own earlier.
describe('opening the coach for a workout', () => {
  test('"Edit with AI", the first time the coach is opened, asks which proposals are waiting once', async () => {
    await renderApp();
    expect(listings()).toHaveLength(0);

    await editTodaysWorkout();
    await screen.findByTestId('coach-context');
    await flush();
    await flush();

    expect(listings()).toHaveLength(1);
  });

  test('"Edit with AI" after the coach was opened on its own asks once more, not twice', async () => {
    await renderApp();
    await openCoach();
    await waitFor(() => expect(listings()).toHaveLength(1));
    await fireEvent.press(tab('Home'));

    await editTodaysWorkout();
    await screen.findByTestId('coach-context');
    await flush();
    await flush();

    expect(listings()).toHaveLength(2);
    expect(messagesToCoach()).toHaveLength(0);
  });

  test('and what is waiting is shown from that one answer', async () => {
    await renderApp();
    await openCoach();
    await waitFor(() => expect(listings()).toHaveLength(1));
    await fireEvent.press(tab('Home'));
    listsWaiting(waitingRevision());

    await editTodaysWorkout();
    await screen.findByTestId('apply-button');
    await flush();

    expect(listings()).toHaveLength(2);
    expect(screen.getAllByTestId('proposal-card')).toHaveLength(1);
    within(screen.getByTestId('coach-context')).getByText('Opened from Core & Abs Focus');
  });
});

describe('Scenario A: a new workout', () => {
  test('asks the coach, shows the card loading, then a New Workout card with the two actions', async () => {
    const reply = held();
    backend.on('POST', '/coach/message', reply.responder);
    await renderApp();
    await openCoach();

    await fireEvent.press(button('Create a 25-minute upper-body workout'));

    expect(screen.getByTestId('proposal-loading')).toBeOnTheScreen();
    expect(messagesToCoach()).toHaveLength(1);
    expect(messagesToCoach()[0].body).toEqual({
      message: 'Create a 25-minute upper-body workout',
      history: [],
      timezone: ZONE,
    });
    expect(messagesToCoach()[0].headers.Authorization).toBe(`Bearer ${SESSION.token}`);

    reply.release({ status: 200, body: newWorkoutReply() });
    await screen.findByTestId('apply-button');

    expect(screen.queryByTestId('proposal-loading')).toBeNull();
    status().getByText('New Workout');
    const card = within(screen.getByTestId('proposal-card'));
    card.getByText('Bodyweight Basics');
    card.getByText('18 min');
    expect(card.queryByTestId('key-changes')).toBeNull();
    button('Apply This Workout');
    button('Ask for More Changes');
    button('Dismiss');
    expect(screen.getByTestId('proposal-caption')).toHaveTextContent("Not saved yet. It's added to your plan when you apply it.");
    // a proposal is not a saved workout: nothing was read about a plan to replace, and nothing was written
    expect(planReads()).toEqual([]);
    expect(approvals()).toHaveLength(0);
    expect(rejections()).toHaveLength(0);
  });

  test('applies only when asked, shows Applying until the backend answers, then Applied with what the backend saved', async () => {
    backend.on('POST', '/coach/message', { status: 200, body: newWorkoutReply() });
    const approval = held();
    backend.on('POST', approvePath(NEW_ID), approval.responder);
    await renderApp();
    await openCoach();
    await fireEvent.press(button('Create a 25-minute upper-body workout'));
    await screen.findByTestId('apply-button');

    await fireEvent.press(button('Apply This Workout'));

    expect(approvals()).toHaveLength(1);
    expect(approvals()[0].body).toEqual({ binding: NEW_BINDING });
    button('Applying…');
    expect(screen.queryByRole('button', { name: 'Applied' })).toBeNull();
    status().getByText('New Workout');

    approval.release({ status: 201, body: savedAs() });
    await screen.findByRole('button', { name: 'Applied' });

    status().getByText('Applied');
    expect(screen.getByTestId('proposal-caption')).toHaveTextContent('Added “Core Stability & Abs” to your plan for today.');
    expect(screen.queryByRole('button', { name: 'Ask for More Changes' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Dismiss' })).toBeNull();
    expect(writes()).toEqual([]);
  });

  test('a double press on Apply asks the backend once', async () => {
    backend.on('POST', '/coach/message', { status: 200, body: newWorkoutReply() });
    const approval = held();
    backend.on('POST', approvePath(NEW_ID), approval.responder);
    await renderApp();
    await openCoach();
    await fireEvent.press(button('Create a 25-minute upper-body workout'));
    await screen.findByTestId('apply-button');

    const apply = button('Apply This Workout');
    await fireEvent.press(apply);
    await fireEvent.press(apply);
    await fireEvent.press(screen.getByTestId('apply-button'));

    expect(approvals()).toHaveLength(1);
    approval.release({ status: 201, body: savedAs() });
    await screen.findByRole('button', { name: 'Applied' });
    expect(approvals()).toHaveLength(1);
  });
});

describe('Scenario B: editing a saved workout', () => {
  test('opens from the workout, shows which one, and sends the message naming it by its id', async () => {
    backend.on('POST', '/coach/message', { status: 200, body: revisionReply() });
    await renderApp();

    await editTodaysWorkout();

    const note = screen.getByTestId('coach-context');
    within(note).getByText('Opened from Core & Abs Focus');
    screen.getByText('What would you like to change in “Core & Abs Focus”?');
    expect(messagesToCoach()).toHaveLength(0);

    await say('Suggest a different ab workout for today.');
    await screen.findByTestId('apply-button');

    // the workout travels in its own field: the question the screen asked is not sent as something the coach said
    expect(messagesToCoach()[0].body).toEqual({
      message: 'Suggest a different ab workout for today.',
      history: [],
      workout_plan_id: 41,
      timezone: ZONE,
    });
  });

  test("shows an Updated Workout card whose Key Changes are the backend's comparison, which came in the proposal", async () => {
    backend.on('POST', '/coach/message', { status: 200, body: revisionReply() });
    await renderApp();
    await editTodaysWorkout();

    await say('Suggest a different ab workout for today.');
    await screen.findByTestId('apply-button');

    status().getByText('Updated Workout');
    // the saved workout is never read by the app: what differs is in the proposal
    expect(planReads()).toEqual([]);
    const changes = within(screen.getByTestId('key-changes'));
    changes.getByText('Replaced Bicycle Crunch with Side Plank');
    changes.getByText('Plank: 30 s → 40 s');
    // the backend said how long the saved workout takes (17 minutes) and this one takes 16
    changes.getByText('Duration changed from 17 to 16 min');
    button('Apply Updated Workout');
    button('Ask for More Changes');
    button('Dismiss');
    expect(screen.getByTestId('proposal-caption')).toHaveTextContent('Applying replaces “Core & Abs Focus”. Until then it stays as it is.');
    expect(approvals()).toHaveLength(0);
  });

  test('a revision that only moves the workout to another day shows the move, not "no changes"', async () => {
    // the backend says identical: true (the exercises are alike) and scheduled_date_changed: true
    const tomorrow = '2026-10-21';
    backend.on('POST', '/coach/message', { status: 200, body: sameExercisesReply({ day: tomorrow, changes: { scheduled_date_changed: true } }) });
    await renderApp();
    await editTodaysWorkout();

    await say('Move it to tomorrow.');
    await screen.findByTestId('apply-button');

    status().getByText('Updated Workout');
    const changes = within(screen.getByTestId('key-changes'));
    changes.getByText('Moved from Tue, 20 Oct to Wed, 21 Oct');
    changes.getByText('Kept the same duration (16 min)');
    expect(changes.queryByText(/No exercise changes|identical|no changes/i)).toBeNull();
    screen.getByText('Core & Abs Focus');
    screen.getByText('Core focus • Tomorrow');
    button('Apply Updated Workout');
  });

  test('a revision that only changes a weight lists it with the real numbers, and shows the weight on the exercise', async () => {
    const prescribed = (weight: number) => ({
      sets: 3,
      reps: 12,
      duration_seconds: null,
      rest_seconds: 60,
      weight_kg: weight,
      summary: `3 sets of 12 reps at ${weight} kg, 60 s rest`,
    });
    backend.on('POST', '/coach/message', {
      status: 200,
      body: sameExercisesReply({
        exercises: (items) => items.map((item) => (item.exercise_name === 'Dead Bug' ? { ...item, weight_kg: 20 as never } : item)),
        changes: {
          changed: [{ section: 'MAIN_WORKOUT', exercise_name: 'Dead Bug', before: prescribed(15), after: prescribed(20) }],
          unchanged: ['Mountain Climbers', 'Lunges', 'Plank', 'Bicycle Crunch', 'Hamstring Stretch'],
          identical: false,
        },
      }),
    });
    await renderApp();
    await editTodaysWorkout();

    await say('Make the dead bug heavier.');
    await screen.findByTestId('apply-button');

    within(screen.getByTestId('key-changes')).getByText('Dead Bug: 15 kg → 20 kg');
    await fireEvent.press(screen.getByTestId('proposal-section-MAIN_WORKOUT'));
    const main = within(screen.getByTestId('proposal-exercises-MAIN_WORKOUT'));
    main.getByText('3 sets • 12 reps • 20 kg • 60 s rest');
    expect(main.getAllByText('Changed')).toHaveLength(1);
  });

  test('applies it through the approval route, and only then says it replaced the saved workout', async () => {
    backend.on('POST', '/coach/message', { status: 200, body: revisionReply() });
    const approval = held();
    backend.on('POST', approvePath(REVISION_ID), approval.responder);
    await renderApp();
    await editTodaysWorkout();
    await say('Suggest a different ab workout for today.');
    await screen.findByTestId('apply-button');

    await fireEvent.press(button('Apply Updated Workout'));

    expect(approvals().map((request) => [request.method, request.path, request.body])).toEqual([
      ['POST', approvePath(REVISION_ID), { binding: REVISION_BINDING }],
    ]);
    button('Applying…');
    expect(screen.getByTestId('proposal-caption')).not.toHaveTextContent(/^Replaced/);

    approval.release({ status: 201, body: savedAs() });
    await screen.findByRole('button', { name: 'Applied' });

    expect(screen.getByTestId('proposal-caption')).toHaveTextContent('Replaced “Core & Abs Focus” with “Core Stability & Abs” for today.');
    // the app never cancelled or edited the saved workout itself: the backend's approval did, in its own transaction
    expect(writes()).toEqual([]);
  });

  test('Home asks the backend again after a workout was applied, so it shows what is saved', async () => {
    backend.on('POST', '/coach/message', { status: 200, body: revisionReply() });
    backend.on('POST', approvePath(REVISION_ID), { status: 201, body: savedAs() });
    await renderApp();
    const reads = () => readsMade(backend).filter((read) => read.startsWith(`GET ${PLANS}?`)).length;
    expect(reads()).toBe(1);
    await editTodaysWorkout();
    await say('Suggest a different ab workout for today.');
    await screen.findByTestId('apply-button');
    await fireEvent.press(button('Apply Updated Workout'));
    await screen.findByRole('button', { name: 'Applied' });

    // coming back within the 30 seconds in which Home reuses its answer
    await fireEvent.press(tab('Home'));

    await screen.findByTestId('home-screen');
    await screen.findByTestId('workout-card-41');
    expect(reads()).toBe(2);
  });

  test('when the backend could not compare, the card still shows the proposal and says so, with no changes and no length', async () => {
    const body = revisionReply();
    body.proposal.changes = null;
    body.proposal.revision.replaces_plan_estimated_minutes = null;
    backend.on('POST', '/coach/message', { status: 200, body });
    await renderApp();
    await editTodaysWorkout();

    await say('Suggest a different ab workout for today.');
    await screen.findByTestId('apply-button');

    status().getByText('Updated Workout');
    expect(screen.getByTestId('key-changes-unavailable')).toBeOnTheScreen();
    expect(screen.queryByText(/Replaced Bicycle Crunch/)).toBeNull();
    expect(screen.getByTestId('key-changes')).not.toHaveTextContent(/duration/i);
    expect(planReads()).toEqual([]);
  });

  test('says so when the proposal replaces a different workout than the one the coach was opened from', async () => {
    const body = revisionReply();
    body.proposal.revision.replaces_plan_id = 52;
    body.proposal.revision.replaces_plan_name = 'Leg Day';
    body.proposal.changes.compared_with_plan_id = 52;
    body.proposal.changes.compared_with_plan_name = 'Leg Day';
    backend.on('POST', '/coach/message', { status: 200, body });
    await renderApp();
    await editTodaysWorkout();

    await say('Make tomorrow’s workout shorter.');
    await screen.findByTestId('apply-button');

    expect(screen.getByTestId('off-target-note')).toHaveTextContent(/This replaces “Leg Day”, not “Core & Abs Focus”, which you opened the coach from\./);
  });
});

describe('Scenario C: asking for more changes', () => {
  async function firstProposal() {
    backend.on('POST', '/coach/message', { status: 200, body: revisionReply() });
    backend.on('POST', '/coach/message', { status: 200, body: revisionReply({ id: REFINED_ID, binding: REFINED_BINDING, plankSeconds: 20, reply: 'Here is a gentler version.' }) });
    await renderApp();
    await editTodaysWorkout();
    await say('Suggest a different ab workout for today.');
    await screen.findByTestId('apply-button');
  }

  test('"Ask for More Changes" puts the cursor in the message field, asking what to change', async () => {
    await firstProposal();

    await fireEvent.press(button('Ask for More Changes'));

    expect(screen.getByLabelText('Message')).toHaveProp('placeholder', 'What would you like to change?');
  });

  test('sends the whole conversation with the new message, in the coach API\'s own terms, and nothing about the card', async () => {
    await firstProposal();

    await say('Keep the same duration, but make it easier on my knees.');
    await screen.findByText('Here is a gentler version.');

    expect(messagesToCoach()).toHaveLength(2);
    // what was said, and the workout it is about: the screen's own question is not part of it
    expect(messagesToCoach()[1].body).toEqual({
      message: 'Keep the same duration, but make it easier on my knees.',
      history: [
        { role: 'user', text: 'Suggest a different ab workout for today.' },
        { role: 'coach', text: 'Here is an updated version.' },
      ],
      workout_plan_id: 41,
      timezone: ZONE,
    });
  });

  test('shows the new proposal in a new card, ends the old one, and compares with the saved workout, not with the first proposal', async () => {
    await firstProposal();

    await say('Keep the same duration, but make it easier on my knees.');
    await screen.findByText('Here is a gentler version.');
    await screen.findAllByTestId('proposal-card');

    const cards = screen.getAllByTestId('proposal-card');
    expect(cards).toHaveLength(2);
    expect(within(cards[0]).getByTestId('proposal-status')).toHaveTextContent(/Older version$/);
    expect(within(cards[0]).queryByTestId('apply-button')).toBeNull();
    expect(within(cards[1]).getByTestId('proposal-status')).toHaveTextContent(/Updated Workout$/);
    // each came with the backend's comparison with the same saved workout: it is the original that both are compared with
    expect(planReads()).toEqual([]);
    const changes = within(within(cards[1]).getByTestId('key-changes'));
    changes.getByText('Plank: 30 s → 20 s');
    changes.getByText('Replaced Bicycle Crunch with Side Plank');
    expect(approvals()).toHaveLength(0);
  });

  test('applying the refinement approves it, not the first proposal', async () => {
    await firstProposal();
    await say('Keep the same duration, but make it easier on my knees.');
    await screen.findByText('Here is a gentler version.');
    backend.on('POST', approvePath(REFINED_ID), { status: 201, body: savedAs('Gentle Core & Abs') });

    await fireEvent.press(button('Apply Updated Workout'));
    await screen.findByRole('button', { name: 'Applied' });

    expect(approvals().map((request) => [request.path, request.body])).toEqual([[approvePath(REFINED_ID), { binding: REFINED_BINDING }]]);
    expect(screen.getByTestId('proposal-caption')).toHaveTextContent(/^Replaced “Core & Abs Focus” with “Gentle Core & Abs” for today\.$/);
    expect(within(screen.getAllByTestId('proposal-card')[0]).getByTestId('proposal-status')).toHaveTextContent(/Older version$/);
  });
});

describe('when the coach cannot answer', () => {
  test('a lost connection shows a failed card with Try Again; trying again asks once, with the same message, and a duplicate card never appears', async () => {
    backend.on('POST', '/coach/message', 'network-error');
    backend.on('POST', '/coach/message', { status: 200, body: newWorkoutReply() });
    await renderApp();
    await openCoach();

    await fireEvent.press(button('Create a 25-minute upper-body workout'));
    await screen.findByTestId('proposal-generation-failed');

    screen.getByText("Can't reach Formiq. Check your connection and try again.");
    await fireEvent.press(button('Try Again'));
    await screen.findByTestId('apply-button');

    expect(messagesToCoach().map((request) => request.body)).toEqual([
      { message: 'Create a 25-minute upper-body workout', history: [], timezone: ZONE },
      { message: 'Create a 25-minute upper-body workout', history: [], timezone: ZONE },
    ]);
    expect(screen.getAllByText('Create a 25-minute upper-body workout')).toHaveLength(1);
    expect(screen.getAllByTestId('proposal-card')).toHaveLength(1);
  });

  test('the coach being unavailable (502) is said plainly, and nothing is shown as a workout', async () => {
    backend.on('POST', '/coach/message', { status: 502, body: { detail: 'the AI coach could not answer; try again later' } });
    await renderApp();
    await openCoach();

    await say('hello');
    await screen.findByTestId('request-failed');

    screen.getByText("The coach couldn't answer. Try again in a moment.");
    expect(screen.queryByTestId('apply-button')).toBeNull();
    button('Try Again');
  });

  test('an expired session says to log in again and offers no Try Again, which could not help', async () => {
    backend.on('POST', '/coach/message', { status: 401, body: { detail: 'could not validate credentials' } });
    await renderApp();
    await openCoach();

    await fireEvent.press(button('Create a 25-minute upper-body workout'));
    await screen.findByTestId('proposal-generation-failed');

    screen.getByText('Your session has expired. Log in again.');
    expect(screen.queryByRole('button', { name: 'Try Again' })).toBeNull();
  });

  test('an answer with no words and no workout is an error, not an empty bubble', async () => {
    backend.on('POST', '/coach/message', { status: 200, body: { reply: '' } });
    await renderApp();
    await openCoach();

    await say('hello');
    await screen.findByTestId('request-failed');

    screen.getByText('The coach sent an empty answer. Try again.');
  });

  test('an answer the app cannot read in full is refused: no workout is shown from a damaged proposal', async () => {
    const body = newWorkoutReply();
    delete body.proposal.coverage;
    backend.on('POST', '/coach/message', { status: 200, body });
    await renderApp();
    await openCoach();

    await fireEvent.press(button('Create a 25-minute upper-body workout'));
    await screen.findByTestId('proposal-generation-failed');

    screen.getByText('Formiq sent an answer the app could not read. Try again.');
    expect(screen.queryByTestId('apply-button')).toBeNull();
  });

  test('a reply that proposes nothing is just the coach talking: no card', async () => {
    backend.on('POST', '/coach/message', { status: 200, body: golden.reply_only });
    await renderApp();
    await openCoach();

    await say('which workout?');
    await screen.findByText('Which workout do you mean?');

    expect(screen.queryByTestId('proposal-card')).toBeNull();
  });
});

describe('when a workout cannot be applied', () => {
  async function proposalOnScreen() {
    backend.on('POST', '/coach/message', { status: 200, body: revisionReply() });
    await renderApp();
    await editTodaysWorkout();
    await say('Suggest a different ab workout for today.');
    await screen.findByTestId('apply-button');
  }

  test('a lost connection keeps the proposal and the saved workout, says so, and applying again works and saves once', async () => {
    await proposalOnScreen();
    backend.on('POST', approvePath(REVISION_ID), 'network-error');
    backend.on('POST', approvePath(REVISION_ID), { status: 201, body: savedAs() });

    await fireEvent.press(button('Apply Updated Workout'));
    await screen.findByTestId('apply-error');

    const alert = within(screen.getByTestId('apply-error'));
    alert.getByText("Can't reach Formiq. Check your connection and try again.");
    status().getByText('Updated Workout');
    expect(screen.queryByRole('button', { name: 'Applied' })).toBeNull();
    // still the same proposal, with the same Key Changes, and nothing written by the app itself
    within(screen.getByTestId('key-changes')).getByText('Plank: 30 s → 40 s');
    expect(screen.getByTestId('proposal-caption')).toHaveTextContent('Applying replaces “Core & Abs Focus”. Until then it stays as it is.');
    expect(writes()).toEqual([]);

    await fireEvent.press(button('Try Again'));
    await screen.findByRole('button', { name: 'Applied' });

    expect(approvals()).toHaveLength(2);
    expect(approvals().map((request) => request.body)).toEqual([{ binding: REVISION_BINDING }, { binding: REVISION_BINDING }]);
  });

  test('a timeout says the workout may or may not have been applied, and that trying again will tell', async () => {
    await proposalOnScreen();
    backend.on('POST', approvePath(REVISION_ID), { status: 200 });

    await fireEvent.press(button('Apply Updated Workout'));
    await screen.findByTestId('apply-error');

    expect(screen.getByTestId('apply-error')).toHaveTextContent(/may not have been applied/);
    expect(screen.queryByRole('button', { name: 'Applied' })).toBeNull();
    button('Try Again');
  });

  test.each([
    ['the proposal expired', 409, 'this proposal has expired: ask the coach for a new one', /has expired/],
    ['the saved workout changed since it was proposed', 409, 'the workout plan this proposal replaces was changed or cancelled since it was proposed: ask the coach for a new one', /would replace has changed/],
    ['it was already applied', 409, 'this proposal was already approved', /already applied/],
    ['the proposal is gone', 404, 'there is no workout plan proposal x', /can't find this proposal/],
  ])('%s: the proposal stays as shown, the card says why, and applying again is not offered', async (_name, code, detail, wording) => {
    await proposalOnScreen();
    backend.on('POST', approvePath(REVISION_ID), { status: code, body: { detail } });

    await fireEvent.press(button('Apply Updated Workout'));
    await screen.findByTestId('apply-error');

    expect(screen.getByTestId('apply-error')).toHaveTextContent(wording);
    status().getByText('Updated Workout');
    expect(screen.queryByRole('button', { name: 'Applied' })).toBeNull();
    expect(screen.getByTestId('apply-button')).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Try Again' })).toBeNull();
    expect(approvals()).toHaveLength(1);
  });

  test('an expired session says to log in again, and the workout is not shown as saved', async () => {
    await proposalOnScreen();
    backend.on('POST', approvePath(REVISION_ID), { status: 401, body: { detail: 'could not validate credentials' } });

    await fireEvent.press(button('Apply Updated Workout'));
    await screen.findByTestId('apply-error');

    expect(screen.getByTestId('apply-error')).toHaveTextContent(/Your session has expired\. Log in again\./);
    expect(screen.queryByRole('button', { name: 'Applied' })).toBeNull();
  });

  test('a 201 that cannot be read is not taken for a saved workout', async () => {
    await proposalOnScreen();
    backend.on('POST', approvePath(REVISION_ID), { status: 201, body: { id: 77 } });

    await fireEvent.press(button('Apply Updated Workout'));
    await screen.findByTestId('apply-error');

    expect(screen.queryByRole('button', { name: 'Applied' })).toBeNull();
    expect(screen.getByTestId('apply-error')).toHaveTextContent(/may not have been applied/);
  });
});

describe('the conversation across tabs', () => {
  test('an answer that arrives while the person looks at Home is there when they come back', async () => {
    const reply = held();
    backend.on('POST', '/coach/message', reply.responder);
    await renderApp();
    await openCoach();
    await fireEvent.press(button('Create a 25-minute upper-body workout'));
    expect(screen.getByTestId('proposal-loading')).toBeOnTheScreen();

    await fireEvent.press(tab('Home'));
    expect(screen.queryByTestId('coach-screen')).toBeNull();
    await act(async () => {
      reply.release({ status: 200, body: newWorkoutReply() });
      await flush();
    });
    await openCoach();

    await screen.findByTestId('apply-button');
    status().getByText('New Workout');
    expect(messagesToCoach()).toHaveLength(1);
  });

  test('Home, when it is the tab showing as a workout finishes applying, asks at once and shows what was saved', async () => {
    backend.on('POST', '/coach/message', { status: 200, body: newWorkoutReply() });
    const approval = held();
    backend.on('POST', approvePath(NEW_ID), approval.responder);
    await renderApp();
    const reads = () => readsMade(backend).filter((read) => read.startsWith(`GET ${PLANS}?`)).length;
    await openCoach();
    await fireEvent.press(button('Create a 25-minute upper-body workout'));
    await screen.findByTestId('apply-button');
    await fireEvent.press(button('Apply This Workout'));

    // the person goes to Home while it applies: Home reuses its answer, so asks nothing
    await fireEvent.press(tab('Home'));
    await screen.findByTestId('home-screen');
    expect(reads()).toBe(1);
    homeAnswers.plans = [savedAs()];
    await act(async () => {
      approval.release({ status: 201, body: savedAs() });
      await flush();
    });

    // it is the screen in focus, so it does not wait for them to leave and come back
    await waitFor(() => expect(reads()).toBe(2));
    await screen.findByTestId('workout-card-77');
    expect(screen.queryByTestId('workout-card-41')).toBeNull();
  });

  test('on another tab as it finishes, Home asks nothing then, and asks the next time it is shown', async () => {
    backend.on('POST', '/coach/message', { status: 200, body: newWorkoutReply() });
    const approval = held();
    backend.on('POST', approvePath(NEW_ID), approval.responder);
    await renderApp();
    const reads = () => readsMade(backend).filter((read) => read.startsWith(`GET ${PLANS}?`)).length;
    await openCoach();
    await fireEvent.press(button('Create a 25-minute upper-body workout'));
    await screen.findByTestId('apply-button');
    await fireEvent.press(button('Apply This Workout'));

    await fireEvent.press(tab('Discover'));
    homeAnswers.plans = [savedAs()];
    await act(async () => {
      approval.release({ status: 201, body: savedAs() });
      await flush();
    });
    expect(reads()).toBe(1);

    await fireEvent.press(tab('Home'));

    await screen.findByTestId('workout-card-77');
    expect(reads()).toBe(2);
  });

  test('a workout applying while the person looks at Home finishes: it is Applied when they come back, and sent once', async () => {
    backend.on('POST', '/coach/message', { status: 200, body: newWorkoutReply() });
    const approval = held();
    backend.on('POST', approvePath(NEW_ID), approval.responder);
    await renderApp();
    await openCoach();
    await fireEvent.press(button('Create a 25-minute upper-body workout'));
    await screen.findByTestId('apply-button');
    await fireEvent.press(button('Apply This Workout'));

    await fireEvent.press(tab('Home'));
    await act(async () => {
      approval.release({ status: 201, body: savedAs() });
      await flush();
    });
    await openCoach();

    await screen.findByRole('button', { name: 'Applied' });
    expect(approvals()).toHaveLength(1);
  });
});

describe('the menu', () => {
  test('"Start over" clears the conversation and only looks again for what is waiting', async () => {
    backend.on('POST', '/coach/message', { status: 200, body: newWorkoutReply() });
    await renderApp();
    await openCoach();
    await fireEvent.press(button('Create a 25-minute upper-body workout'));
    await screen.findByTestId('apply-button');
    const before = backend.requests.length;

    await fireEvent.press(button('More options'));
    await fireEvent.press(screen.getByRole('menuitem', { name: 'Start over' }));

    expect(screen.queryByTestId('proposal-card')).toBeNull();
    screen.getByText(/I'm Formiq Coach/);
    expect(backend.requests.slice(before).map((request) => `${request.method} ${request.path}`)).toEqual([`GET ${PENDING}`]);
  });

  test('offers the static preview of every card state in a development build, and it sends nothing', async () => {
    await renderApp();
    await openCoach();
    const before = backend.requests.length;

    await fireEvent.press(button('More options'));
    await fireEvent.press(screen.getByRole('menuitem', { name: 'Preview card states' }));

    expect(screen.getByTestId('coach-card-preview')).toBeOnTheScreen();
    expect(backend.requests).toHaveLength(before);
  });
});

describe('both themes', () => {
  test.each(['dark', 'light'] as const)('the whole edit flow works in the %s theme', async (scheme) => {
    backend.on('POST', '/coach/message', { status: 200, body: revisionReply() });
    backend.on('POST', approvePath(REVISION_ID), { status: 201, body: savedAs() });
    await renderApp(scheme);
    await editTodaysWorkout();

    await say('Suggest a different ab workout for today.');
    await screen.findByTestId('apply-button');
    status().getByText('Updated Workout');
    await fireEvent.press(button('Apply Updated Workout'));

    await screen.findByRole('button', { name: 'Applied' });
  });
});

// ---- Phase 2.1: dismissing, workouts waiting from before the conversation, and the workout the conversation is about

const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
const MIN = 60_000;

// a proposal the backend lists as waiting: made `minutesAgo` before the clock the tests run on
function waitingBody(source: object, minutesAgo: number) {
  return {
    ...clone(source),
    created_at: new Date(NOW.getTime() - minutesAgo * MIN).toISOString(),
    expires_at: new Date(NOW.getTime() + (30 - minutesAgo) * MIN).toISOString(),
  };
}
const waitingRevision = (minutesAgo = 12) => waitingBody(pendings.one.proposals[0], minutesAgo);
// the second of the two, a new workout (its id is 'c' repeated), made after the revision
const waitingNew = (minutesAgo = 5) => waitingBody(pendings.two.proposals[0], minutesAgo);
const listsWaiting = (...proposals: unknown[]) => answerPending({ status: 200, body: { proposals } });

describe('dismissing a workout', () => {
  async function newWorkoutOnScreen() {
    backend.on('POST', '/coach/message', { status: 200, body: newWorkoutReply() });
    await renderApp();
    await openCoach();
    await fireEvent.press(button('Create a 25-minute upper-body workout'));
    await screen.findByTestId('apply-button');
  }

  test('rejects it through the rejection route with its binding, shows Dismissing until the backend answers 204, then Dismissed', async () => {
    const rejection = held();
    backend.on('POST', rejectPath(NEW_ID), rejection.responder);
    await newWorkoutOnScreen();

    await fireEvent.press(button('Dismiss'));

    expect(rejections().map((request) => [request.method, request.path, request.body])).toEqual([['POST', rejectPath(NEW_ID), { binding: NEW_BINDING }]]);
    expect(rejections()[0].headers.Authorization).toBe(`Bearer ${SESSION.token}`);
    button('Dismissing…');
    status().getByText('New Workout');
    expect(screen.queryByText('Dismissed')).toBeNull();

    rejection.release({ status: 204 });
    await screen.findByText('Dismissed');

    expect(screen.getByTestId('proposal-note')).toHaveTextContent('Dismissed. Nothing was saved.');
    expect(screen.queryByRole('button', { name: /Apply|Dismiss|Ask for More/ })).toBeNull();
    // nothing was applied, and nothing was written by the app itself
    expect(approvals()).toHaveLength(0);
    expect(writes()).toEqual([]);
  });

  test('a double press rejects it once', async () => {
    const rejection = held();
    backend.on('POST', rejectPath(NEW_ID), rejection.responder);
    await newWorkoutOnScreen();

    const dismiss = button('Dismiss');
    await fireEvent.press(dismiss);
    await fireEvent.press(dismiss);
    await fireEvent.press(screen.getByTestId('dismiss-button'));
    rejection.release({ status: 204 });
    await screen.findByText('Dismissed');

    expect(rejections()).toHaveLength(1);
  });

  test('a lost connection keeps the workout waiting, says so, and Dismiss Again works', async () => {
    backend.on('POST', rejectPath(NEW_ID), 'network-error');
    backend.on('POST', rejectPath(NEW_ID), { status: 204 });
    await newWorkoutOnScreen();

    await fireEvent.press(button('Dismiss'));
    await screen.findByTestId('dismiss-error');

    within(screen.getByTestId('dismiss-error')).getByText("Can't reach Formiq. Check your connection and try again.");
    status().getByText('New Workout');
    expect(screen.queryByText('Dismissed')).toBeNull();
    // still there to apply
    expect(screen.getByTestId('apply-button')).toBeEnabled();

    await fireEvent.press(button('Dismiss Again'));
    await screen.findByText('Dismissed');
    expect(rejections().map((request) => request.body)).toEqual([{ binding: NEW_BINDING }, { binding: NEW_BINDING }]);
  });

  test('an answer that never comes says it may not have been dismissed, and trying again is safe', async () => {
    backend.on('POST', rejectPath(NEW_ID), 'hang');
    backend.on('POST', rejectPath(NEW_ID), { status: 204 });
    await newWorkoutOnScreen();
    jest.useFakeTimers({ now: NOW, doNotFake: ['nextTick', 'setImmediate', 'queueMicrotask'] });

    await fireEvent.press(button('Dismiss'));
    await act(async () => {
      await jest.advanceTimersByTimeAsync(15_001);
    });

    expect(screen.getByTestId('dismiss-error')).toHaveTextContent(/may not have been dismissed/);
    expect(screen.queryByText('Dismissed')).toBeNull();
    jest.useRealTimers();
    clock = fixClockAt(NOW);
    await fireEvent.press(button('Dismiss Again'));
    await screen.findByText('Dismissed');
  });

  test('a 404 says the proposal is no longer waiting, which is not the same as dismissed', async () => {
    backend.on('POST', rejectPath(NEW_ID), { status: 404, body: { detail: 'there is no workout plan proposal' } });
    await newWorkoutOnScreen();

    await fireEvent.press(button('Dismiss'));
    await screen.findByText('No longer waiting');

    expect(screen.queryByText('Dismissed')).toBeNull();
    expect(screen.getByTestId('proposal-note')).toHaveTextContent(/it expired/);
  });

  test('a 409 (already applied: the answer to its approval was lost) asks the approval again and shows the saved plan as applied', async () => {
    backend.on('POST', rejectPath(NEW_ID), { status: 409, body: { detail: 'this proposal was already approved: it cannot be rejected' } });
    backend.on('POST', approvePath(NEW_ID), { status: 200, body: savedAs() });
    await newWorkoutOnScreen();

    await fireEvent.press(button('Dismiss'));
    await waitFor(() => status().getByText('Applied'));

    expect(screen.queryByText('Dismissed')).toBeNull();
    expect(screen.queryByTestId('dismiss-error')).toBeNull();
    // one dismissal, then the approval asked again for the plan it saved, with the binding that was shown
    expect(rejections()).toHaveLength(1);
    expect(approvals().map((request) => request.body)).toEqual([{ binding: NEW_BINDING }]);
  });

  test('a 409 to that approval too (the saved plan was changed since) says it was already applied, and nothing more is offered', async () => {
    backend.on('POST', rejectPath(NEW_ID), { status: 409, body: { detail: 'this proposal was already approved: it cannot be rejected' } });
    backend.on('POST', approvePath(NEW_ID), {
      status: 409,
      body: { detail: 'this proposal was already approved, but the workout plan it saved was changed, cancelled or removed since' },
    });
    await newWorkoutOnScreen();

    await fireEvent.press(button('Dismiss'));
    await screen.findByTestId('dismiss-error');

    within(screen.getByTestId('dismiss-error')).getByText('This workout was already applied. Check your plans.');
    expect(screen.queryByText('Dismissed')).toBeNull();
    expect(screen.queryByText('Applied')).toBeNull();
    expect(screen.getByTestId('apply-button')).toBeDisabled();
    expect(rejections()).toHaveLength(1);
    expect(approvals()).toHaveLength(1);
  });

  test('a 409 for another version of the proposal is said as it was, with no approval asked', async () => {
    backend.on('POST', rejectPath(NEW_ID), {
      status: 409,
      body: { detail: 'this rejection is for a different version of the proposal than the one proposed' },
    });
    await newWorkoutOnScreen();

    await fireEvent.press(button('Dismiss'));
    await screen.findByTestId('dismiss-error');

    within(screen.getByTestId('dismiss-error')).getByText('This workout was already applied or changed. Check your plans.');
    expect(screen.queryByText('Dismissed')).toBeNull();
    expect(approvals()).toHaveLength(0);
  });

  test('an expired session is said, with no Dismiss Again', async () => {
    backend.on('POST', rejectPath(NEW_ID), { status: 401, body: { detail: 'could not validate credentials' } });
    await newWorkoutOnScreen();

    await fireEvent.press(button('Dismiss'));
    await screen.findByTestId('dismiss-error');

    expect(screen.getByTestId('dismiss-error')).toHaveTextContent(/Your session has expired\. Log in again\./);
    expect(screen.queryByRole('button', { name: /Dismiss/ })).toBeNull();
  });
});

describe('an approval whose answer was lost', () => {
  test('asking again is a 200 with the same plan, and that is a success: Applied, and sent twice with the same binding', async () => {
    backend.on('POST', '/coach/message', { status: 200, body: newWorkoutReply() });
    backend.on('POST', approvePath(NEW_ID), 'network-error');
    backend.on('POST', approvePath(NEW_ID), { status: 200, body: savedAs() });
    await renderApp();
    await openCoach();
    await fireEvent.press(button('Create a 25-minute upper-body workout'));
    await screen.findByTestId('apply-button');

    await fireEvent.press(button('Apply This Workout'));
    await screen.findByTestId('apply-error');
    status().getByText('New Workout');
    expect(screen.queryByText('Applied')).toBeNull();
    await fireEvent.press(button('Try Again'));
    await screen.findByRole('button', { name: 'Applied' });

    expect(approvals().map((request) => request.body)).toEqual([{ binding: NEW_BINDING }, { binding: NEW_BINDING }]);
    expect(screen.getByTestId('proposal-caption')).toHaveTextContent('Added “Core Stability & Abs” to your plan for today.');
  });

  test('a 409 to the same retry (the saved plan changed since) is not a success', async () => {
    backend.on('POST', '/coach/message', { status: 200, body: newWorkoutReply() });
    backend.on('POST', approvePath(NEW_ID), 'network-error');
    backend.on('POST', approvePath(NEW_ID), { status: 409, body: { detail: 'this proposal was already approved, but the workout it saved was changed or cancelled since' } });
    await renderApp();
    await openCoach();
    await fireEvent.press(button('Create a 25-minute upper-body workout'));
    await screen.findByTestId('apply-button');
    await fireEvent.press(button('Apply This Workout'));
    await screen.findByTestId('apply-error');

    await fireEvent.press(button('Try Again'));
    await waitFor(() => expect(screen.getByTestId('apply-error')).toHaveTextContent(/already applied/));

    expect(screen.queryByText('Applied')).toBeNull();
    expect(screen.getByTestId('apply-button')).toBeDisabled();
  });
});

describe('workouts waiting from before the conversation', () => {
  test('one is found when the coach is opened: a line, its card with when it was proposed, and nothing applied, dismissed or asked', async () => {
    listsWaiting(waitingRevision(12));
    await renderApp();

    await openCoach();
    await screen.findByTestId('apply-button');

    screen.getByText('You have a workout waiting for your approval. It was proposed earlier: look it over before you apply it.');
    status().getByText('Updated Workout');
    expect(screen.getByTestId('proposal-recovered')).toHaveTextContent('Proposed 12 min ago');
    const changes = within(screen.getByTestId('key-changes'));
    changes.getByText('Replaced Bicycle Crunch with Dead Bug');
    changes.getByText('Goblet Squat: 20 kg → no weight');
    changes.getByText('Cat-Cow Stretch: 30 s → 40 s');
    changes.getByText('Duration changed from 17 to 16 min');
    expect(approvals()).toHaveLength(0);
    expect(rejections()).toHaveLength(0);
    expect(messagesToCoach()).toHaveLength(0);
    expect(planReads()).toEqual([]);
  });

  test('is applied with the id and binding it came with, and only the backend makes it Applied', async () => {
    listsWaiting(waitingRevision());
    const approval = held();
    backend.on('POST', approvePath(REVISION_ID), approval.responder);
    await renderApp();
    await openCoach();
    await screen.findByTestId('apply-button');

    await fireEvent.press(button('Apply Updated Workout'));
    button('Applying…');
    expect(approvals().map((request) => [request.path, request.body])).toEqual([[approvePath(REVISION_ID), { binding: REVISION_BINDING }]]);
    expect(screen.queryByText('Applied')).toBeNull();

    approval.release({ status: 201, body: savedAs() });
    await screen.findByRole('button', { name: 'Applied' });
    expect(screen.getByTestId('proposal-caption')).toHaveTextContent('Replaced “Core & Abs Focus” with “Core Stability & Abs” for today.');
  });

  test('a recovered workout that the backend refuses (409 expired) is not left looking as if it could be applied', async () => {
    listsWaiting(waitingRevision());
    backend.on('POST', approvePath(REVISION_ID), { status: 409, body: { detail: 'this proposal has expired: ask the coach for a new one' } });
    await renderApp();
    await openCoach();
    await screen.findByTestId('apply-button');

    await fireEvent.press(button('Apply Updated Workout'));
    await screen.findByTestId('apply-error');

    expect(screen.getByTestId('apply-error')).toHaveTextContent(/has expired/);
    expect(screen.getByTestId('apply-button')).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Dismiss' })).toBeNull();
    expect(screen.queryByText('Applied')).toBeNull();
  });

  test('is dismissed with its own Dismiss', async () => {
    listsWaiting(waitingRevision());
    backend.on('POST', rejectPath(REVISION_ID), { status: 204 });
    await renderApp();
    await openCoach();
    await screen.findByTestId('apply-button');

    await fireEvent.press(button('Dismiss'));
    await screen.findByText('Dismissed');

    expect(rejections().map((request) => [request.path, request.body])).toEqual([[rejectPath(REVISION_ID), { binding: REVISION_BINDING }]]);
  });

  test('several are listed to choose from, newest first, and none is chosen, applied or dismissed for the person', async () => {
    listsWaiting(waitingNew(5), waitingRevision(12));
    await renderApp();

    await openCoach();
    await screen.findByTestId('waiting-proposals');

    screen.getByText('2 workouts are waiting for your approval');
    const [newest, older] = screen.getAllByTestId(/^waiting-c|^waiting-a/);
    within(newest).getByText('Bodyweight Basics');
    within(newest).getByText('New Workout');
    within(older).getByText('Core Stability & Abs');
    within(older).getByText('Replaces “Core & Abs Focus”');
    expect(screen.queryByTestId('proposal-card')).toBeNull();
    expect(approvals()).toHaveLength(0);
    expect(rejections()).toHaveLength(0);
  });

  test('two waiting workouts of one name are told apart, by the day each is for and, on one day, by when it was proposed', async () => {
    // the clock is 9:30 am on 20 Oct: the revision was proposed at 9:18, the new workout at 9:25, a third later still
    const named = (item: object, day: string, id?: string) => ({
      ...(item as Record<string, unknown>),
      name: 'Leg Day',
      scheduled_date: day,
      ...(id ? { proposal_id: id } : {}),
    });
    listsWaiting(
      named(waitingNew(5), '2026-10-21'),
      named(waitingRevision(12), '2026-10-21'),
      named(waitingBody(pendings.two.proposals[0], 2), '2026-10-24', 'e'.repeat(32)),
    );
    await renderApp();

    await openCoach();
    await screen.findByTestId('waiting-proposals');

    const detailOf = (id: string) => screen.getByTestId(`waiting-detail-${id}`).props.children;
    expect(detailOf(NEW_ID)).toBe('For tomorrow • Proposed at 9:25 am');
    expect(detailOf(REVISION_ID)).toBe('For tomorrow • Proposed at 9:18 am');
    expect(detailOf('e'.repeat(32))).toBe('For Sat, 24 Oct');
  });

  test('Review shows that workout as a card; a revision can be changed even when a newer new workout waits: asking binds the conversation to its plan', async () => {
    listsWaiting(waitingNew(5), waitingRevision(12));
    await renderApp();
    await openCoach();
    await screen.findByTestId('waiting-proposals');

    await fireEvent.press(within(screen.getByTestId(`waiting-${REVISION_ID}`)).getByRole('button', { name: 'Review' }));

    status().getByText('Updated Workout');
    expect(screen.getAllByTestId('waiting-proposals')).toHaveLength(1);
    // the coach is then held to this card's plan, so the newer card for no plan at all does not stand in its way
    button('Ask for More Changes');
    expect(screen.queryByTestId('ask-unavailable')).toBeNull();
    button('Apply Updated Workout');
    button('Dismiss');
  });

  test('the one left in the list after the person looked at another says "1 workout is waiting", in the singular', async () => {
    listsWaiting(waitingNew(5), waitingRevision(12));
    await renderApp();
    await openCoach();
    await screen.findByTestId('waiting-proposals');
    screen.getByText('2 workouts are waiting for your approval');

    await fireEvent.press(within(screen.getByTestId(`waiting-${REVISION_ID}`)).getByRole('button', { name: 'Review' }));

    screen.getByText('1 workout is waiting for your approval');
    expect(screen.queryByText(/1 workouts/)).toBeNull();
    expect(screen.queryByText(/Choose one/)).toBeNull();
  });

  test('Review shows a new workout that is not the newest as a card that can only be applied or dismissed, and says why', async () => {
    listsWaiting(waitingBody(pendings.one.proposals[0], 5), waitingBody(pendings.two.proposals[0], 12));
    await renderApp();
    await openCoach();
    await screen.findByTestId('waiting-proposals');

    await fireEvent.press(within(screen.getByTestId(`waiting-${NEW_ID}`)).getByRole('button', { name: 'Review' }));

    status().getByText('New Workout');
    // nothing binds the coach to a new workout: it would change the newest waiting one, which is not this
    expect(screen.queryByRole('button', { name: 'Ask for More Changes' })).toBeNull();
    expect(screen.getByTestId('ask-unavailable')).toHaveTextContent(
      'The coach changes your newest waiting workout, “Core Stability & Abs”. This older one can only be applied or dismissed.',
    );
    button('Apply This Workout');
    button('Dismiss');
  });

  test('is looked for again each time the coach is shown again, and nothing that already has a card is added twice', async () => {
    listsWaiting(waitingRevision());
    await renderApp();
    await openCoach();
    await screen.findByTestId('apply-button');
    expect(listings()).toHaveLength(1);

    await fireEvent.press(tab('Home'));
    await openCoach();
    await waitFor(() => expect(listings()).toHaveLength(2));
    await fireEvent.press(tab('Home'));
    await openCoach();
    await waitFor(() => expect(listings()).toHaveLength(3));

    expect(screen.getAllByTestId('proposal-card')).toHaveLength(1);
  });

  test('looking again finds what has come to wait since, and shows it', async () => {
    await renderApp();
    await openCoach();
    await waitFor(() => expect(listings()).toHaveLength(1));
    expect(screen.queryByTestId('proposal-card')).toBeNull();
    listsWaiting(waitingRevision());

    await fireEvent.press(tab('Home'));
    await openCoach();

    await screen.findByTestId('apply-button');
    status().getByText('Updated Workout');
  });

  test('"Start over" looks again, and a workout dismissed here is not offered again even if the list still has it', async () => {
    listsWaiting(waitingRevision());
    backend.on('POST', rejectPath(REVISION_ID), { status: 204 });
    await renderApp();
    await openCoach();
    await screen.findByTestId('apply-button');
    await fireEvent.press(button('Dismiss'));
    await screen.findByText('Dismissed');

    await fireEvent.press(button('More options'));
    await fireEvent.press(screen.getByRole('menuitem', { name: 'Start over' }));
    await waitFor(() => expect(listings()).toHaveLength(2));

    expect(screen.queryByTestId('proposal-card')).toBeNull();
    screen.getByText(/I'm Formiq Coach/);
  });

  test('"Start over" finds a workout the conversation it cleared had made, since the backend still has it waiting', async () => {
    backend.on('POST', '/coach/message', { status: 200, body: newWorkoutReply() });
    await renderApp();
    await openCoach();
    await fireEvent.press(button('Create a 25-minute upper-body workout'));
    await screen.findByTestId('apply-button');
    listsWaiting(waitingBody(pendings.two.proposals[0], 1));

    await fireEvent.press(button('More options'));
    await fireEvent.press(screen.getByRole('menuitem', { name: 'Start over' }));

    await screen.findByTestId('proposal-recovered');
    expect(screen.getAllByTestId('proposal-card')).toHaveLength(1);
    status().getByText('New Workout');
    expect(screen.getByTestId('proposal-recovered')).toHaveTextContent('Proposed 1 min ago');
  });

  test('a failure to look says so with Try Again, never that there is none, and Try Again shows what is waiting', async () => {
    answerPending({ status: 503, body: { detail: 'unavailable' } });
    await renderApp();

    await openCoach();
    await screen.findByTestId('recovery-failed');

    expect(screen.getByTestId('recovery-failed')).toHaveTextContent(/Formiq isn't available right now\. Couldn't check for workouts waiting for your approval\./);
    expect(screen.queryByTestId('proposal-card')).toBeNull();
    listsWaiting(waitingRevision());
    await fireEvent.press(screen.getByTestId('recovery-retry'));

    await screen.findByTestId('apply-button');
    expect(screen.queryByTestId('recovery-failed')).toBeNull();
  });

  test('an answer the app cannot read in full is a failure to look, and shows no workout from it', async () => {
    const broken = waitingRevision();
    delete (broken as { coverage?: unknown }).coverage;
    listsWaiting(broken);
    await renderApp();

    await openCoach();
    await screen.findByTestId('recovery-failed');

    expect(screen.queryByTestId('proposal-card')).toBeNull();
    expect(screen.queryByTestId('apply-button')).toBeNull();
  });

  test('an expired session is said, with no Try Again', async () => {
    answerPending({ status: 401, body: { detail: 'could not validate credentials' } });
    await renderApp();

    await openCoach();
    await screen.findByTestId('recovery-failed');

    expect(screen.getByTestId('recovery-failed')).toHaveTextContent(/Your session has expired\. Log in again\./);
    expect(screen.queryByTestId('recovery-retry')).toBeNull();
  });

  test('the conversation keeps going while waiting workouts are looked for: a message is sent and answered', async () => {
    const waiting = held();
    answerPending(waiting.responder);
    backend.on('POST', '/coach/message', { status: 200, body: golden.reply_only });
    await renderApp();
    await openCoach();

    await say('hello');
    await screen.findByText('Which workout do you mean?');
    waiting.release({ status: 200, body: { proposals: [waitingRevision()] } });

    await screen.findByTestId('apply-button');
    // the answer to the message did not move: the waiting workout came before the question it was found during
    expect(messagesToCoach()).toHaveLength(1);
  });
});

describe('the workout the conversation is about', () => {
  test('is named in every message, a retry included, and, once a revision of it is applied, is the plan that replaced it', async () => {
    backend.on('POST', '/coach/message', 'network-error');
    backend.on('POST', '/coach/message', { status: 200, body: revisionReply() });
    backend.on('POST', '/coach/message', { status: 200, body: golden.reply_only });
    backend.on('POST', approvePath(REVISION_ID), { status: 201, body: savedAs() });
    await renderApp();
    await editTodaysWorkout();

    await say('Suggest a different ab workout for today.');
    await screen.findByTestId('proposal-generation-failed').catch(() => screen.findByTestId('request-failed'));
    await fireEvent.press(button('Try Again'));
    await screen.findByTestId('apply-button');
    await fireEvent.press(button('Apply Updated Workout'));
    await screen.findByRole('button', { name: 'Applied' });
    await say('now a bit longer');
    await screen.findByText('Which workout do you mean?');

    expect(messagesToCoach().map((request) => (request.body as { workout_plan_id: number }).workout_plan_id)).toEqual([41, 41, 77]);
  });

  test.each([
    [404, 'user 7 has no workout plan 41'],
    [409, 'workout plan 41 is CANCELLED: only a PLANNED plan can be changed with the coach'],
  ])('a %s to a message about it says it can no longer be edited, and there is no Try Again', async (status, detail) => {
    backend.on('POST', '/coach/message', { status, body: { detail } });
    await renderApp();
    await editTodaysWorkout();

    await say('make it shorter');
    await screen.findByTestId('request-failed');

    screen.getByText("This workout can't be edited any more — it was replaced or cancelled. Start over to pick another.");
    expect(screen.queryByRole('button', { name: 'Try Again' })).toBeNull();
    expect(messagesToCoach()).toHaveLength(1);
  });

  test('a 404 to a message about no workout is the account, not a workout', async () => {
    backend.on('POST', '/coach/message', { status: 404, body: { detail: 'user 7 does not exist' } });
    await renderApp();
    await openCoach();

    await say('hello');
    await screen.findByTestId('request-failed');

    screen.getByText("Formiq can't find your account. Log in again.");
  });
});

describe('the new flows, in the light theme', () => {
  test('waiting workouts are chosen from, reviewed, applied and dismissed', async () => {
    listsWaiting(waitingNew(5), waitingRevision(12));
    backend.on('POST', approvePath(NEW_ID), { status: 201, body: savedAs('Bodyweight Basics') });
    backend.on('POST', rejectPath(REVISION_ID), { status: 204 });
    await renderApp('light');
    await openCoach();
    await screen.findByTestId('waiting-proposals');

    await fireEvent.press(within(screen.getByTestId(`waiting-${NEW_ID}`)).getByRole('button', { name: 'Review' }));
    await fireEvent.press(button('Apply This Workout'));
    await screen.findByRole('button', { name: 'Applied' });
    await fireEvent.press(within(screen.getByTestId(`waiting-${REVISION_ID}`)).getByRole('button', { name: 'Review' }));
    await fireEvent.press(button('Dismiss'));
    await screen.findByText('Dismissed');

    expect(approvals()).toHaveLength(1);
    expect(rejections()).toHaveLength(1);
  });
});

// ---- Phase 2.3: after a restart or a new sign-in, which workout the conversation is about

describe('after a restart or a new sign-in', () => {
  // a revision of plan `planId` that was waiting before the app was closed
  function waitingFor(planId: number, name: string, id: string, minutesAgo = 5) {
    const body = waitingBody(pendings.one.proposals[0], minutesAgo) as unknown as {
      proposal_id: string;
      binding: string;
      revision: { replaces_plan_id: number; replaces_plan_name: string };
      changes: { compared_with_plan_id: number; compared_with_plan_name: string };
    };
    body.proposal_id = id;
    body.binding = id.charAt(0).repeat(64);
    body.revision.replaces_plan_id = planId;
    body.revision.replaces_plan_name = name;
    body.changes.compared_with_plan_id = planId;
    body.changes.compared_with_plan_name = name;
    return body;
  }
  const planSent = () => messagesToCoach().map((request) => (request.body as { workout_plan_id?: number }).workout_plan_id);

  beforeEach(() => {
    backend.on('POST', '/coach/message', { status: 200, body: golden.reply_only });
  });

  test('a suggested change to the waiting card is a message about its plan, and so is the next thing typed', async () => {
    listsWaiting(waitingRevision(5));
    await renderApp();
    await openCoach();
    await screen.findByTestId('apply-button');

    await fireEvent.press(button('Keep same duration'));
    await screen.findByText('Which workout do you mean?');
    await say('now a bit longer');
    await waitFor(() => expect(messagesToCoach()).toHaveLength(2));

    // the plan the backend gave in the card, and the same one for the follow-up
    expect(planSent()).toEqual([41, 41]);
  });

  test('"Ask for More Changes" on the waiting card makes what is typed next a message about its plan', async () => {
    listsWaiting(waitingRevision(5));
    await renderApp();
    await openCoach();
    await screen.findByTestId('apply-button');

    await fireEvent.press(screen.getByTestId('ask-button'));
    await say('make it harder');
    await screen.findByText('Which workout do you mean?');

    expect(planSent()).toEqual([41]);
  });

  test('nothing is worked out from the card being there: a message with no change asked of it names no plan', async () => {
    listsWaiting(waitingRevision(5));
    await renderApp();
    await openCoach();
    await screen.findByTestId('apply-button');

    await say('hello');
    await screen.findByText('Which workout do you mean?');

    expect(planSent()).toEqual([undefined]);
    expect(messagesToCoach()[0].body).not.toHaveProperty('workout_plan_id');
  });

  test('of several waiting, only the one the person chose and asked to change binds its plan: never the newest listed', async () => {
    listsWaiting(waitingNew(5), waitingRevision(12));
    await renderApp();
    await openCoach();
    await screen.findByTestId('waiting-proposals');

    await fireEvent.press(within(screen.getByTestId(`waiting-${REVISION_ID}`)).getByRole('button', { name: 'Review' }));
    await fireEvent.press(screen.getByTestId('ask-button'));
    await say('make it easier');
    await screen.findByText('Which workout do you mean?');

    // the plan of the card they looked at (41), not the newest one listed (a new workout, which replaces none)
    expect(planSent()).toEqual([41]);
  });

  test('a new workout waiting is asked about with no plan: it replaces none', async () => {
    listsWaiting(waitingNew(5));
    await renderApp();
    await openCoach();
    await screen.findByTestId('apply-button');

    await fireEvent.press(button('Keep same duration'));
    await screen.findByText('Which workout do you mean?');

    expect(planSent()).toEqual([undefined]);
  });

  test('a workout for another plan than the one being edited can only be applied or dismissed, and the messages still name the plan being edited', async () => {
    listsWaiting(waitingFor(77, 'Leg Day', 'f'.repeat(32)));
    await renderApp();
    await editTodaysWorkout();
    await screen.findByTestId('apply-button');

    status().getByText('Updated Workout');
    expect(screen.queryByRole('button', { name: 'Ask for More Changes' })).toBeNull();
    expect(screen.getByTestId('ask-unavailable')).toHaveTextContent(
      "This isn't a change to “Core & Abs Focus”, which you're editing, so the coach can't change it here. It can only be applied or dismissed.",
    );
    // no suggested changes on a card the coach would not change
    expect(screen.queryByRole('button', { name: 'Keep same duration' })).toBeNull();
    button('Apply Updated Workout');
    button('Dismiss');

    await say('make it shorter');
    await screen.findByText('Which workout do you mean?');

    expect(planSent()).toEqual([41]);
  });

  test('a newer version of the plan being edited is the card the coach is asked to change, whatever else is waiting', async () => {
    listsWaiting(waitingFor(77, 'Leg Day', 'f'.repeat(32), 2), waitingRevision(5));
    await renderApp();
    await editTodaysWorkout();
    await screen.findByTestId('waiting-proposals');

    await fireEvent.press(within(screen.getByTestId(`waiting-${REVISION_ID}`)).getByRole('button', { name: 'Review' }));
    await fireEvent.press(button('Keep same duration'));
    await screen.findByText('Which workout do you mean?');

    expect(planSent()).toEqual([41]);
  });

  test('a new sign-in remembers no plan: the conversation is about none until a change is asked of a card again', async () => {
    listsWaiting(waitingRevision(5));
    const first = await renderApp();
    await openCoach();
    await screen.findByTestId('apply-button');
    await fireEvent.press(button('Keep same duration'));
    await screen.findByText('Which workout do you mean?');
    await first.unmount();

    await renderApp();
    await openCoach();
    await screen.findByTestId('apply-button');
    await say('hello again');
    await waitFor(() => expect(messagesToCoach()).toHaveLength(2));
    expect(planSent()).toEqual([41, undefined]);

    // and asking for a change to the card binds it again
    await screen.findByText('Which workout do you mean?');
    await fireEvent.press(screen.getByTestId('ask-button'));
    await say('make it harder');
    await waitFor(() => expect(messagesToCoach()).toHaveLength(3));
    expect(planSent()).toEqual([41, undefined, 41]);
  });
});
