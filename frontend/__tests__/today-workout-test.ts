import { deriveTodayWorkout, loadTodayWorkout } from '../src/home/todayWorkout';
import { fakeToken, installMockFetch, type MockFetch } from '../test-utils/mockFetch';
import {
  backendWorkouts,
  localTime,
  NOW,
  plan,
  readsMade,
  session,
  TODAY,
  TOMORROW,
  YESTERDAY,
} from '../test-utils/workoutFixtures';

const answers = (parts: Partial<Parameters<typeof deriveTodayWorkout>[0]> = {}) => ({
  plans: [],
  inProgress: [],
  completed: [],
  today: NOW,
  ...parts,
});

const running = (overrides = {}) => session({ id: 5, status: 'IN_PROGRESS', completed_at: null, ...overrides });

describe('which state follows from what the backend says', () => {
  test('a PLANNED plan for today, not done: it is scheduled', () => {
    const today = plan({ id: 41 });

    expect(deriveTodayWorkout(answers({ plans: [today] }))).toEqual({ kind: 'scheduled', plan: today });
  });

  test('nothing planned and nothing done: no workout', () => {
    expect(deriveTodayWorkout(answers())).toEqual({ kind: 'none' });
  });

  test('a session in progress: the workout is in progress, with its plan when it is the plan of today', () => {
    const today = plan({ id: 41 });
    const live = running({ workout_plan_id: 41 });

    expect(deriveTodayWorkout(answers({ plans: [today], inProgress: [live] }))).toEqual({
      kind: 'inProgress',
      session: live,
      plan: today,
    });
  });

  test('a session in progress that is a manual workout, or from another plan, has no plan to name', () => {
    const manual = running({ workout_plan_id: null });
    const other = running({ workout_plan_id: 99 });

    expect(deriveTodayWorkout(answers({ plans: [plan({ id: 41 })], inProgress: [manual] }))).toEqual({
      kind: 'inProgress',
      session: manual,
      plan: null,
    });
    expect(deriveTodayWorkout(answers({ plans: [plan({ id: 41 })], inProgress: [other] }))).toMatchObject({
      kind: 'inProgress',
      plan: null,
    });
  });

  test('a session in progress wins over a plan still to do, and over a completed one: the user is mid-workout', () => {
    const live = running({ workout_plan_id: null });

    expect(
      deriveTodayWorkout(answers({ plans: [plan({ id: 41 })], inProgress: [live], completed: [session({ workout_plan_id: 41 })] })),
    ).toMatchObject({ kind: 'inProgress', session: live });
  });

  test('a session left in progress from an earlier day is still the one in progress', () => {
    const stale = running({ started_at: localTime(9, 0, -3), workout_plan_id: null });

    expect(deriveTodayWorkout(answers({ inProgress: [stale] }))).toMatchObject({ kind: 'inProgress', session: stale });
  });

  test("today's plan done by a COMPLETED session of that plan: the workout is completed, with that session", () => {
    const today = plan({ id: 41 });
    const done = session({ id: 8, workout_plan_id: 41 });

    expect(deriveTodayWorkout(answers({ plans: [today], completed: [done] }))).toEqual({
      kind: 'completed',
      session: done,
      plan: today,
    });
  });

  test("the plan's completion is the session started from it, not any session: a manual workout does not finish it", () => {
    const today = plan({ id: 41 });
    const manual = session({ id: 8, workout_plan_id: null });
    const otherPlan = session({ id: 9, workout_plan_id: 99 });

    expect(deriveTodayWorkout(answers({ plans: [today], completed: [manual, otherPlan] }))).toEqual({
      kind: 'scheduled',
      plan: today,
    });
  });

  test('a plan done on another day is still done: the completion is by plan, not by date', () => {
    const today = plan({ id: 41 });
    const earlier = session({ workout_plan_id: 41, completed_at: localTime(8, 0, -1), started_at: localTime(7, 0, -1) });

    expect(deriveTodayWorkout(answers({ plans: [today], completed: [earlier] }))).toMatchObject({ kind: 'completed', plan: today });
  });

  test('with two plans today, the one not done is shown; with both done, the first is completed', () => {
    const newer = plan({ id: 42, name: 'Newer' });
    const older = plan({ id: 41, name: 'Older' });
    const olderDone = session({ id: 8, workout_plan_id: 41 });
    const newerDone = session({ id: 9, workout_plan_id: 42 });

    expect(deriveTodayWorkout(answers({ plans: [newer, older], completed: [olderDone] }))).toEqual({ kind: 'scheduled', plan: newer });
    expect(deriveTodayWorkout(answers({ plans: [newer, older], completed: [newerDone] }))).toEqual({ kind: 'scheduled', plan: older });
    expect(deriveTodayWorkout(answers({ plans: [newer, older], completed: [olderDone, newerDone] }))).toEqual({
      kind: 'completed',
      plan: newer,
      session: newerDone,
    });
  });

  test('with two plans today and nothing done, the most recently created (the first listed) is shown', () => {
    const [newer, older] = [plan({ id: 42 }), plan({ id: 41 })];

    expect(deriveTodayWorkout(answers({ plans: [newer, older] }))).toEqual({ kind: 'scheduled', plan: newer });
  });

  test('no plan today but a workout completed today: completed, without a plan to name', () => {
    const manual = session({ id: 8, workout_plan_id: null, completed_at: localTime(8, 45) });

    expect(deriveTodayWorkout(answers({ completed: [manual] }))).toEqual({ kind: 'completed', session: manual, plan: null });
  });

  test("a workout completed on another day does not make today's completed", () => {
    const yesterday = session({ completed_at: localTime(21, 0, -1), workout_plan_id: null });

    expect(deriveTodayWorkout(answers({ completed: [yesterday] }))).toEqual({ kind: 'none' });
  });

  test("a completion is of the device's own day: just after midnight local time is the new day", () => {
    const justAfterMidnight = new Date(2026, 9, 21, 0, 10);
    const lateLastNight = session({ completed_at: new Date(2026, 9, 20, 23, 50).toISOString(), workout_plan_id: null });

    // 23:50 on the 20th is last night once the device's clock says the 21st, and today until then
    expect(deriveTodayWorkout(answers({ completed: [lateLastNight], today: justAfterMidnight }))).toEqual({ kind: 'none' });
    expect(deriveTodayWorkout(answers({ completed: [lateLastNight], today: new Date(2026, 9, 20, 23, 55) }))).toMatchObject({
      kind: 'completed',
    });
  });

  test("a plan for another day is not today's, even if the backend listed it", () => {
    expect(deriveTodayWorkout(answers({ plans: [plan({ scheduled_date: YESTERDAY }), plan({ id: 2, scheduled_date: TOMORROW })] }))).toEqual({
      kind: 'none',
    });
  });

  test('an undated plan, a draft and a cancelled plan are not scheduled for today', () => {
    expect(
      deriveTodayWorkout(
        answers({
          plans: [
            plan({ id: 1, scheduled_date: null }),
            plan({ id: 2, status: 'DRAFT' }),
            plan({ id: 3, status: 'CANCELLED' }),
          ],
        }),
      ),
    ).toEqual({ kind: 'none' });
  });

  test('sessions of the wrong status in either list are ignored, as the backend would not have listed them', () => {
    const cancelled = session({ status: 'CANCELLED', workout_plan_id: 41 });
    const notRunning = session({ status: 'COMPLETED' });

    expect(deriveTodayWorkout(answers({ plans: [plan({ id: 41 })], inProgress: [notRunning], completed: [cancelled] }))).toMatchObject({
      kind: 'scheduled',
    });
  });

  test('the plan\'s date is compared with the device\'s own day: "today" moves at local midnight', () => {
    const tonight = plan({ scheduled_date: TODAY });

    expect(deriveTodayWorkout(answers({ plans: [tonight], today: new Date(2026, 9, 20, 23, 59) }))).toMatchObject({ kind: 'scheduled' });
    expect(deriveTodayWorkout(answers({ plans: [tonight], today: new Date(2026, 9, 21, 0, 0) }))).toEqual({ kind: 'none' });
  });

  // The backend stores how many days a week the user trains, never which ones, so a day with no plan is never
  // called a rest day: there is no such state to be in. (The profile is not even read.)
  test('nothing in the answers can make a rest day: the state set has none', () => {
    const states = [
      deriveTodayWorkout(answers()),
      deriveTodayWorkout(answers({ plans: [plan()] })),
      deriveTodayWorkout(answers({ inProgress: [running()] })),
      deriveTodayWorkout(answers({ completed: [session({ workout_plan_id: null })] })),
    ].map((state) => state.kind);

    expect(states).toEqual(['none', 'scheduled', 'inProgress', 'completed']);
  });
});

describe('loadTodayWorkout: the three reads', () => {
  const USER = { token: fakeToken(7), userId: 7 };
  let backend: MockFetch;

  beforeEach(() => {
    backend = installMockFetch();
  });

  test("reads the plans of today's date and both session lists, each once, and nothing else", async () => {
    backendWorkouts(backend, 7, { plans: [plan({ id: 41 })] });

    const state = await loadTodayWorkout(USER, NOW);

    expect(state).toMatchObject({ kind: 'scheduled' });
    expect([...readsMade(backend)].sort()).toEqual([
      `GET /users/7/workout-plans?status=PLANNED&scheduled_date=${TODAY}`,
      'GET /users/7/workout-sessions?status=COMPLETED',
      'GET /users/7/workout-sessions?status=IN_PROGRESS',
    ]);
  });

  test("uses the device's day for the plans, not the UTC one", async () => {
    backendWorkouts(backend, 7);
    // 00:30 local on the 21st: the UTC date may still be the 20th (in zones ahead of UTC), and the local one rules
    await loadTodayWorkout(USER, new Date(2026, 9, 21, 0, 30));

    expect(readsMade(backend)).toContain('GET /users/7/workout-plans?status=PLANNED&scheduled_date=2026-10-21');
  });

  test.each([
    ['the plans read', { plans: { status: 500 } }],
    ['the in-progress read', { inProgress: { status: 500 } }],
    ['the completed read', { completed: { status: 500 } }],
  ] as const)('fails as a whole when %s fails: a state from two reads could say "start" during a session', async (_which, failing) => {
    backendWorkouts(backend, 7, { plans: [plan({ id: 41 })], ...failing });

    await expect(loadTodayWorkout(USER, NOW)).rejects.toMatchObject({ kind: 'http', status: 500 });
  });

  test('fails as a whole when one answer cannot be read', async () => {
    backendWorkouts(backend, 7, { plans: [{ id: 'x' }] });

    await expect(loadTodayWorkout(USER, NOW)).rejects.toMatchObject({ kind: 'invalid-response' });
  });

  test('never writes: every request is a GET, and none goes to the coach, a session or a proposal', async () => {
    backendWorkouts(backend, 7, { plans: [plan({ id: 41 })], completed: [session({ workout_plan_id: 41 })] });

    await loadTodayWorkout(USER, NOW);

    expect(backend.requests.map((request) => request.method)).toEqual(['GET', 'GET', 'GET']);
    expect(backend.requests.some((request) => /coach|proposal|profile/.test(request.path))).toBe(false);
    expect(backend.requests.every((request) => request.body === undefined)).toBe(true);
  });
});
