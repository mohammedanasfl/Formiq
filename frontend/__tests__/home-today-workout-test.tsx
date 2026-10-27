import { act, fireEvent, screen, waitFor, within } from '@testing-library/react-native';

import { TODAY_WORKOUT_FRESH_MS } from '../src/home/useTodayWorkout';
import { AppShell } from '../src/shell/AppShell';
import { themes } from '../src/theme';
import { fixClockAt } from '../test-utils/clock';
import { captureAppState, captureHardwareBack } from '../test-utils/flow';
import { fakeToken, installMockFetch, type MockFetch, type Reply } from '../test-utils/mockFetch';
import { renderWithTheme } from '../test-utils/renderWithTheme';
import {
  backendWorkouts,
  corePlan,
  localTime,
  NOW,
  plan,
  readsMade,
  session,
  type WorkoutAnswers,
} from '../test-utils/workoutFixtures';

const SESSION = { token: fakeToken(7), userId: 7 };
const dark = themes.dark.colors;
const READS_PER_LOAD = 3;

let backend: MockFetch;
let clock: ReturnType<typeof fixClockAt>;
let moveAppTo: ReturnType<typeof captureAppState>;

beforeEach(() => {
  backend = installMockFetch();
  clock = fixClockAt(NOW);
  moveAppTo = captureAppState();
  captureHardwareBack();
});

afterEach(() => {
  jest.restoreAllMocks();
  clock.restore();
});

const tab = (name: string) => screen.getByRole('tab', { name });
const running = (overrides = {}) => session({ id: 5, status: 'IN_PROGRESS', completed_at: null, ...overrides });

async function renderHomeWith(answers: WorkoutAnswers, scheme: 'dark' | 'light' = 'dark') {
  const scripted = backendWorkouts(backend, 7, answers);
  // the AI Coach tab, once opened, looks for the proposals waiting for the person (a read, as Home's are)
  backend.on('GET', '/coach/proposals/pending', { status: 200, body: { proposals: [] } });
  const view = await renderWithTheme(<AppShell session={SESSION} onSignOut={jest.fn()} />, scheme);
  return { ...view, answers: scripted };
}

describe("Home reads today's workout from the backend", () => {
  test('a plan scheduled for today is the card: its name, description and exercise count, no length or category', async () => {
    await renderHomeWith({ plans: [corePlan()] });

    const card = await screen.findByTestId('workout-card-41');
    within(card).getByText('Core & Abs Focus');
    within(card).getByText('Strengthen your core and improve stability.');
    within(card).getByText('6 exercises');
    within(card).getByText('Start Workout');
    expect(within(card).queryByText(/min\b/)).toBeNull();
    expect(screen.queryByText('23 min')).toBeNull();
  });

  test('asks for exactly the plans of the device\'s day and both lists of sessions, and nothing else', async () => {
    await renderHomeWith({ plans: [corePlan()] });
    await screen.findByTestId('workout-card-41');

    expect([...readsMade(backend)].sort()).toEqual([
      'GET /users/7/workout-plans?status=PLANNED&scheduled_date=2026-10-20',
      'GET /users/7/workout-sessions?status=COMPLETED',
      'GET /users/7/workout-sessions?status=IN_PROGRESS',
    ]);
    for (const request of backend.requests) expect(request.headers.Authorization).toBe(`Bearer ${SESSION.token}`);
  });

  test('no plan today: says so, and "Ask Formiq" opens the AI Coach tab', async () => {
    await renderHomeWith({});

    await screen.findByText('No workout planned today');
    await fireEvent.press(screen.getByRole('button', { name: 'Ask Formiq' }));

    expect(tab('AI Coach')).toBeSelected();
  });

  test('a plan for another day is not shown as today\'s', async () => {
    await renderHomeWith({ plans: [plan({ name: 'Tomorrow Only', scheduled_date: '2026-10-21' })] });

    await screen.findByText('No workout planned today');
    expect(screen.queryByText('Tomorrow Only')).toBeNull();
  });

  test('a session in progress: says so, with the plan it was started from, and offers nothing to start', async () => {
    await renderHomeWith({ plans: [corePlan()], inProgress: [running({ workout_plan_id: 41, started_at: localTime(8, 15) })] });

    const card = await screen.findByTestId('workout-card-in-progress');
    within(card).getByText('Core & Abs Focus');
    within(card).getByText('In progress. Started today at 8:15 am.');
    expect(screen.queryByText('Start Workout')).toBeNull();
    expect(screen.queryByRole('button', { name: /^Core & Abs Focus/ })).toBeNull();
  });

  test('a session in progress with no plan today still says so', async () => {
    await renderHomeWith({ inProgress: [running({ workout_plan_id: null })] });

    const card = await screen.findByTestId('workout-card-in-progress');
    within(card).getByText('Workout in progress');
  });

  test('a completed session of today\'s plan: the workout is completed, and it is not offered to start again', async () => {
    await renderHomeWith({ plans: [corePlan()], completed: [session({ workout_plan_id: 41, completed_at: localTime(8, 58) })] });

    const card = await screen.findByTestId('workout-card-completed');
    within(card).getByText('Core & Abs Focus');
    within(card).getByText('Completed today at 8:58 am.');
    expect(screen.queryByText('Start Workout')).toBeNull();
  });

  test('a workout completed today with no plan for today is completed too', async () => {
    await renderHomeWith({ completed: [session({ workout_plan_id: null, completed_at: localTime(7, 30) })] });

    const card = await screen.findByTestId('workout-card-completed');
    within(card).getByText('Workout completed');
    within(card).getByText('Completed today at 7:30 am.');
  });

  test('while it is being read, the card says it is checking; then it is replaced by the answer', async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    backend.on('GET', '/users/7/workout-plans', async (): Promise<Reply> => {
      await gate;
      return { status: 200, body: [corePlan()] };
    });
    backend.on('GET', '/users/7/workout-sessions', { status: 200, body: [] });
    await renderWithTheme(<AppShell session={SESSION} onSignOut={jest.fn()} />);

    screen.getByTestId('workout-card-loading');
    screen.getByText("Checking today's workout");
    expect(screen.queryByText('No workout planned today')).toBeNull();
    // the rest of Home is there meanwhile
    screen.getByRole('header', { name: 'Quick Actions' });

    release();
    await screen.findByTestId('workout-card-41');
    expect(screen.queryByTestId('workout-card-loading')).toBeNull();
  });

  test('a failed read says so, with a reason, and "Try again" asks again and shows the answer', async () => {
    const { answers } = await renderHomeWith({ plans: { status: 500 } });

    const card = await screen.findByTestId('workout-card-error');
    within(card).getByText("Couldn't load today's workout");
    within(card).getByText("Something went wrong on Formiq's side. Try again.");
    expect(screen.queryByText('No workout planned today')).toBeNull();
    expect(screen.queryByText('Start Workout')).toBeNull();

    answers.plans = [corePlan()];
    await fireEvent.press(screen.getByRole('button', { name: 'Try again' }));

    await screen.findByTestId('workout-card-41');
    expect(backend.requests).toHaveLength(2 * READS_PER_LOAD);
  });

  test.each([
    ['plans', { plans: { status: 401 } }],
    ['the in-progress sessions', { inProgress: { status: 401 } }],
    ['the completed sessions', { completed: { status: 401 } }],
  ] as const)('a failure of %s is an error, not a card made from the other two', async (_which, failing) => {
    await renderHomeWith({ plans: [corePlan()], ...failing });

    const card = await screen.findByTestId('workout-card-error');
    within(card).getByText('Your session has expired. Log in again.');
    expect(screen.queryByTestId('workout-card-41')).toBeNull();
  });

  test('an expired session says so and offers no "Try again", which could not work; Home stays usable', async () => {
    await renderHomeWith({ plans: { status: 401 } });

    const card = await screen.findByTestId('workout-card-error');
    within(card).getByText('Your session has expired. Log in again.');
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull();
    expect(within(card).queryByRole('button')).toBeNull();
    // the rest of Home is there and the tabs work
    screen.getByRole('header', { name: 'Quick Actions' });
    await fireEvent.press(tab('Profile'));
    await fireEvent.press(tab('Home'));
    screen.getByRole('header', { name: 'Quick Actions' });
  });

  test.each([
    ['a lost connection', 'network-error'],
    ['a server error', { status: 500 }],
    ['the backend being unavailable', { status: 503 }],
    ['an answer the app cannot read', { status: 200, body: { not: 'a list' } }],
  ] as const)('%s keeps its "Try again"', async (_name, plans) => {
    await renderHomeWith({ plans });

    const card = await screen.findByTestId('workout-card-error');
    within(card).getByRole('button', { name: 'Try again' });
  });

  test('an answer the app cannot read is an error, never an empty day', async () => {
    await renderHomeWith({ plans: [{ id: 41, name: 'No exercises field' }] });

    const card = await screen.findByTestId('workout-card-error');
    within(card).getByText('Formiq sent an answer the app could not read. Try again.');
    expect(screen.queryByText('No workout planned today')).toBeNull();
  });

  test('with no connection, says it cannot reach Formiq', async () => {
    await renderHomeWith({ plans: 'network-error' });

    within(await screen.findByTestId('workout-card-error')).getByText("Can't reach Formiq. Check your connection and try again.");
  });

  test('the rest of Home is unchanged: the other sections are still there', async () => {
    await renderHomeWith({});
    await screen.findByText('No workout planned today');

    screen.getByRole('header', { name: 'Quick Actions' });
    screen.getByRole('header', { name: 'Recent Activity' });
    screen.getByRole('button', { name: /^Nutrition:/ });
    screen.getByRole('header', { name: /^Good morning, / });
  });

  test("the card is the dark card in the light theme too", async () => {
    await renderHomeWith({ plans: [corePlan()] }, 'light');

    expect(await screen.findByTestId('workout-card-41')).toHaveStyle({ backgroundColor: dark.surface, borderColor: dark.border });
    expect(screen.getByText('Core & Abs Focus')).toHaveStyle({ color: dark.textPrimary });
  });
});

describe('what Home never does', () => {
  test('only reads: every request is a GET with no body, whatever the state, even after pressing every control of the card', async () => {
    await renderHomeWith({ plans: [corePlan()] });
    await fireEvent.press(await screen.findByRole('button', { name: /^Core & Abs Focus/ }));
    await fireEvent.press(screen.getByRole('button', { name: 'Start Workout' }));
    within(screen.getByTestId('toast')).getByText("Starting a workout isn't available yet. Nothing was started.");

    expect(backend.requests.map((request) => request.method)).toEqual(['GET', 'GET', 'GET']);
    expect(backend.requests.every((request) => request.body === undefined)).toBe(true);
  });

  test('never calls the coach, a proposal, an approval or a session write: opening the coach tab only reads which proposals wait', async () => {
    await renderHomeWith({});
    await screen.findByText('No workout planned today');
    await fireEvent.press(screen.getByRole('button', { name: 'Ask Formiq' }));
    await fireEvent.press(tab('Home'));

    // Home asks the coach nothing; the coach tab, once opened, reads the list of proposals waiting (nothing is proposed,
    // approved or rejected by reading it)
    expect(backend.requests.filter((request) => /coach|proposal|approve|reject/.test(request.path)).map((request) => `${request.method} ${request.path}`)).toEqual([
      'GET /coach/proposals/pending',
    ]);
    expect(backend.requests.filter((request) => request.method !== 'GET')).toEqual([]);
  });

  // The profile stores how many days a week the user trains (training_frequency_per_week), never which days.
  test('does not read the profile or work out a rest day from a weekly count: a day with no plan is "no workout planned"', async () => {
    backend.on('GET', '/users/7/profile', { status: 200, body: { training_frequency_per_week: 3 } });
    await renderHomeWith({});

    await screen.findByText('No workout planned today');
    expect(screen.queryByText(/rest/i)).toBeNull();
    expect(backend.requests.some((request) => request.path.endsWith('/profile'))).toBe(false);
  });

  // The backend can now list the proposals waiting (GET /coach/proposals/pending), but showing one is the AI Coach's job:
  // Home's card is today's workout, and Home never asks the coach, or the list, anything.
  test('shows no pending proposal, and does not ask the coach or the list of waiting proposals: that is the AI Coach tab\'s', async () => {
    await renderHomeWith({});

    await screen.findByText('No workout planned today');
    expect(screen.queryByText(/proposal|pending|review/i)).toBeNull();
    expect(backend.requests.some((request) => request.path.startsWith('/coach'))).toBe(false);
  });
});

describe('when Home asks again', () => {
  test('a quick trip to another tab and back shows the card at once and does not ask again', async () => {
    await renderHomeWith({ plans: [corePlan()] });
    await screen.findByTestId('workout-card-41');

    await fireEvent.press(tab('Discover'));
    await fireEvent.press(tab('Home'));

    expect(screen.getByTestId('workout-card-41')).toBeOnTheScreen();
    expect(screen.queryByTestId('workout-card-loading')).toBeNull();
    expect(backend.requests).toHaveLength(READS_PER_LOAD);
  });

  test('opening the workout and coming back does not ask again either', async () => {
    await renderHomeWith({ plans: [corePlan()] });
    await fireEvent.press(await screen.findByRole('button', { name: /^Core & Abs Focus/ }));
    expect(screen.getByTestId('workout-details')).toBeOnTheScreen();

    await fireEvent.press(screen.getByRole('button', { name: 'Back' }));

    expect(screen.getByTestId('workout-card-41')).toBeOnTheScreen();
    expect(backend.requests).toHaveLength(READS_PER_LOAD);
  });

  test('returning to Home after the answer has gone stale asks again and shows what changed, with no flash of loading', async () => {
    const { answers } = await renderHomeWith({ plans: [corePlan()] });
    await screen.findByTestId('workout-card-41');

    await fireEvent.press(tab('Discover'));
    answers.inProgress = [running({ workout_plan_id: 41 })];
    clock.set(new Date(Date.now() + TODAY_WORKOUT_FRESH_MS + 1000));
    await fireEvent.press(tab('Home'));
    expect(screen.queryByTestId('workout-card-loading')).toBeNull();

    await screen.findByTestId('workout-card-in-progress');
    expect(backend.requests).toHaveLength(2 * READS_PER_LOAD);
  });

  test("while the tab is not Home, nothing is asked: Home's reads are for Home", async () => {
    await renderHomeWith({ plans: [corePlan()] });
    await screen.findByTestId('workout-card-41');
    clock.set(new Date(Date.now() + TODAY_WORKOUT_FRESH_MS * 10));
    backend.on('GET', '/users/7/profile', { status: 200, body: { no_equipment: false, equipment: [] } });

    await fireEvent.press(tab('Discover'));
    await fireEvent.press(tab('Profile'));
    await fireEvent.press(tab('AI Coach'));

    // Home's reads are not asked again; the Profile tab reads the equipment saved with the profile, and the AI Coach
    // tab, opened for the first time, reads the proposals waiting
    const paths = backend.requests.map((request) => request.path);
    expect(paths.filter((path) => !path.startsWith('/coach') && path !== '/users/7/profile')).toHaveLength(READS_PER_LOAD);
    expect(paths.filter((path) => path === '/users/7/profile')).toHaveLength(1);
    expect(paths.filter((path) => path.startsWith('/coach'))).toEqual(['/coach/proposals/pending']);
  });

  test('the app coming back from the background is a focus: it asks again if the answer is stale, and not if it is fresh', async () => {
    await renderHomeWith({ plans: [corePlan()] });
    await screen.findByTestId('workout-card-41');

    await moveAppTo('background');
    await moveAppTo('active');
    expect(backend.requests).toHaveLength(READS_PER_LOAD);

    await moveAppTo('background');
    clock.set(new Date(Date.now() + TODAY_WORKOUT_FRESH_MS + 1000));
    await moveAppTo('active');
    await waitFor(() => expect(backend.requests).toHaveLength(2 * READS_PER_LOAD));
  });

  test('a stale answer is not asked for while the app is in the background', async () => {
    await renderHomeWith({ plans: [corePlan()] });
    await screen.findByTestId('workout-card-41');

    await moveAppTo('background');
    clock.set(new Date(Date.now() + TODAY_WORKOUT_FRESH_MS * 10));
    await act(async () => undefined);

    expect(backend.requests).toHaveLength(READS_PER_LOAD);
  });

  test('coming back the next day asks for the new day\'s plan, even inside the fresh window', async () => {
    const { answers } = await renderHomeWith({ plans: [corePlan()] });
    await screen.findByTestId('workout-card-41');

    await moveAppTo('background');
    // five minutes after midnight, with the plan of the new day
    clock.set(new Date(2026, 9, 21, 0, 5));
    answers.plans = [{ ...corePlan('2026-10-21'), id: 77, name: "Tomorrow's workout" }];
    await moveAppTo('active');

    await screen.findByText("Tomorrow's workout");
    expect(readsMade(backend)).toContain('GET /users/7/workout-plans?status=PLANNED&scheduled_date=2026-10-21');
  });
});

describe("opening today's workout", () => {
  test("its card opens the workout screen with the plan's own name, sections and exercises", async () => {
    await renderHomeWith({ plans: [corePlan()] });

    await fireEvent.press(await screen.findByRole('button', { name: /^Core & Abs Focus/ }));

    expect(screen.getByTestId('workout-details')).toBeOnTheScreen();
    screen.getByRole('header', { name: 'Core & Abs Focus' });
    const headings = screen.getAllByRole('header').map((node) => node.props.children);
    expect(headings).toEqual(expect.arrayContaining(['Core & Abs Focus', 'Warm-up', 'Main Workout', 'Cool-down']));
    for (const name of ['Mountain Climbers', 'Lunges', 'Plank', 'Dead Bug', 'Bicycle Crunch', 'Hamstring Stretch']) {
      expect(screen.getByRole('button', { name: new RegExp(`^${name}\\.`) })).toBeOnTheScreen();
    }
  });

  test("the workout screen shows no length, category or muscles: the plan has none, so none is invented", async () => {
    await renderHomeWith({ plans: [corePlan()] });

    await fireEvent.press(await screen.findByRole('button', { name: /^Core & Abs Focus/ }));

    expect(screen.queryByText(/\b23 min|23 minutes/)).toBeNull();
    expect(screen.queryByText(/^Covers /)).toBeNull();
  });

  test('a plan with a section missing shows only the sections it has', async () => {
    const onlyMain = { ...corePlan(), exercises: corePlan().exercises.filter((entry) => entry.section === 'MAIN_WORKOUT') };
    await renderHomeWith({ plans: [onlyMain] });

    await fireEvent.press(await screen.findByRole('button', { name: /^Core & Abs Focus/ }));

    screen.getByRole('header', { name: 'Main Workout' });
    expect(screen.queryByRole('header', { name: 'Warm-up' })).toBeNull();
    expect(screen.queryByRole('header', { name: 'Cool-down' })).toBeNull();
  });

  test("the other cards on Home still lead to the Workouts screen: only today's plan has a screen", async () => {
    await renderHomeWith({ plans: [corePlan()] });
    await screen.findByTestId('workout-card-41');

    await fireEvent.press(screen.getByRole('button', { name: /^Lower Body Strength, Strength\./ }));

    expect(screen.getByTestId('workouts-placeholder')).toBeOnTheScreen();
  });
});
