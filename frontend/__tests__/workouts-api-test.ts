import { ApiError, listPlannedWorkouts, listWorkoutSessions } from '../src/api';
import { fakeToken, installMockFetch, type MockFetch } from '../test-utils/mockFetch';
import { plan, planExercise, readsMade, session as sessionFixture, TODAY } from '../test-utils/workoutFixtures';

const SESSION = { token: fakeToken(7), userId: 7 };
const PLANS = '/users/7/workout-plans';
const SESSIONS = '/users/7/workout-sessions';

let backend: MockFetch;

beforeEach(() => {
  backend = installMockFetch();
});

async function failure(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(ApiError);
    return error as ApiError;
  }
  throw new Error('expected the request to fail');
}

describe('GET /users/{id}/workout-plans, for one day', () => {
  test("asks for the user's PLANNED plans of that day, with their token, and sends nothing else", async () => {
    backend.on('GET', PLANS, { status: 200, body: [] });

    await listPlannedWorkouts(SESSION, TODAY);

    expect(readsMade(backend)).toEqual([`GET ${PLANS}?status=PLANNED&scheduled_date=${TODAY}`]);
    expect(backend.requests[0].headers.Authorization).toBe(`Bearer ${SESSION.token}`);
    expect(backend.requests[0].body).toBeUndefined();
  });

  test('returns the plans with the fields the app uses, in the backend order', async () => {
    const first = plan({ id: 2, name: 'Newer', description: 'Pushes.', exercises: [planExercise({ id: 5, notes: 'Slow.', weight_kg: 12.5 })] });
    const second = plan({ id: 1, name: 'Older' });
    backend.on('GET', PLANS, {
      status: 200,
      // the backend sends more than the app reads: the rest is left behind
      body: [
        { ...first, user_id: 7, created_at: '2026-10-19T08:00:00Z', updated_at: '2026-10-19T08:00:00Z' },
        second,
      ],
    });

    const plans = await listPlannedWorkouts(SESSION, TODAY);

    expect(plans).toEqual([first, second]);
    expect(plans[0]).not.toHaveProperty('user_id');
  });

  test('a day with no plan is an empty list, not an error', async () => {
    backend.on('GET', PLANS, { status: 200, body: [] });

    expect(await listPlannedWorkouts(SESSION, TODAY)).toEqual([]);
  });

  test('keeps a plan without a description, without a date, and an exercise with a timed target', async () => {
    const timed = planExercise({ reps: null, duration_seconds: 30, rest_seconds: null });
    backend.on('GET', PLANS, { status: 200, body: [plan({ description: null, scheduled_date: null, exercises: [timed] })] });

    const [read] = await listPlannedWorkouts(SESSION, TODAY);

    expect(read.description).toBeNull();
    expect(read.scheduled_date).toBeNull();
    expect(read.exercises[0]).toMatchObject({ reps: null, duration_seconds: 30, rest_seconds: null });
  });

  const damaged: [string, (valid: Record<string, unknown>) => unknown][] = [
    ['has no name', ({ name, ...rest }) => rest],
    ['has a blank name', (valid) => ({ ...valid, name: '  ' })],
    ['has an id that is not a whole number', (valid) => ({ ...valid, id: '41' })],
    ['has a status the backend does not have', (valid) => ({ ...valid, status: 'DONE' })],
    ['has a day that is not YYYY-MM-DD', (valid) => ({ ...valid, scheduled_date: 'tomorrow' })],
    ['has no list of exercises', ({ exercises, ...rest }) => rest],
    ['has exercises that are not a list', (valid) => ({ ...valid, exercises: {} })],
    ['has a description that is not text', (valid) => ({ ...valid, description: 5 })],
    ['has an exercise without its catalog details', (valid) => ({ ...valid, exercises: [{ ...planExercise(), exercise: undefined }] })],
    ['has an exercise with a blank catalog name', (valid) => ({ ...valid, exercises: [planExercise({ exercise: { name: '', description: null, instructions: [] } })] })],
    ['has an exercise in a section the backend does not have', (valid) => ({ ...valid, exercises: [{ ...planExercise(), section: 'FINISHER' }] })],
    ['has an exercise without sets', (valid) => ({ ...valid, exercises: [{ ...planExercise(), sets: undefined }] })],
    ['has an exercise whose steps are not text', (valid) => ({ ...valid, exercises: [{ ...planExercise(), exercise: { name: 'Squat', description: null, instructions: [1] } }] })],
    ['is not an object', () => 'a plan'],
  ];

  test.each(damaged)('refuses the whole answer when a plan %s, rather than showing the others', async (_what, damage) => {
    backend.on('GET', PLANS, { status: 200, body: [plan({ id: 1 }), damage(plan({ id: 2 }) as unknown as Record<string, unknown>)] });

    const error = await failure(listPlannedWorkouts(SESSION, TODAY));

    expect(error.kind).toBe('invalid-response');
  });

  test.each([
    ['an object', {}],
    ['null', null],
    ['text', 'no plans'],
  ])('refuses an answer that is %s instead of a list', async (_what, body) => {
    backend.on('GET', PLANS, { status: 200, body });

    expect((await failure(listPlannedWorkouts(SESSION, TODAY))).kind).toBe('invalid-response');
  });

  test('refuses an answer that is not JSON', async () => {
    backend.on('GET', PLANS, { status: 200 });

    expect((await failure(listPlannedWorkouts(SESSION, TODAY))).kind).toBe('invalid-response');
  });

  test.each([401, 404, 422, 500, 503])('a %i answer is an http error with its status', async (status) => {
    backend.on('GET', PLANS, { status, body: { detail: 'nope' } });

    const error = await failure(listPlannedWorkouts(SESSION, TODAY));

    expect([error.kind, error.status]).toEqual(['http', status]);
  });

  test('a dropped connection is a network error', async () => {
    backend.on('GET', PLANS, 'network-error');

    expect((await failure(listPlannedWorkouts(SESSION, TODAY))).kind).toBe('network');
  });
});

describe('GET /users/{id}/workout-sessions, by status', () => {
  test.each(['IN_PROGRESS', 'COMPLETED'] as const)('asks for the %s sessions, with the token, and sends nothing else', async (status) => {
    backend.on('GET', SESSIONS, { status: 200, body: [] });

    await listWorkoutSessions(SESSION, status);

    expect(readsMade(backend)).toEqual([`GET ${SESSIONS}?status=${status}`]);
    expect(backend.requests[0].headers.Authorization).toBe(`Bearer ${SESSION.token}`);
    expect(backend.requests[0].body).toBeUndefined();
  });

  test('returns the sessions with the fields the app uses, in the backend order', async () => {
    const running = sessionFixture({ id: 3, status: 'IN_PROGRESS', completed_at: null, workout_plan_id: null });
    const done = sessionFixture({ id: 2 });
    backend.on('GET', SESSIONS, {
      status: 200,
      // a session carries its exercises and sets too: the app does not read them
      body: [
        { ...running, user_id: 7, notes: null, exercises: [{ id: 1, sets: [] }] },
        done,
      ],
    });

    const sessions = await listWorkoutSessions(SESSION, 'COMPLETED');

    expect(sessions).toEqual([running, done]);
    expect(sessions[0]).not.toHaveProperty('exercises');
  });

  const damaged: [string, (valid: Record<string, unknown>) => unknown][] = [
    ['has no id', ({ id, ...rest }) => rest],
    ['has a status the backend does not have', (valid) => ({ ...valid, status: 'PLANNED' })],
    ['has no start time', ({ started_at, ...rest }) => rest],
    ['has a start time that is not a time', (valid) => ({ ...valid, started_at: 'earlier' })],
    ['has a completion time that is not a time', (valid) => ({ ...valid, completed_at: 'later' })],
    ['has no completion time field', ({ completed_at, ...rest }) => rest],
    ['has a plan id that is not a whole number', (valid) => ({ ...valid, workout_plan_id: 'x' })],
    ['has no plan id field', ({ workout_plan_id, ...rest }) => rest],
  ];

  test.each(damaged)('refuses the whole answer when a session %s: a dropped session would read as none', async (_what, damage) => {
    backend.on('GET', SESSIONS, { status: 200, body: [damage(sessionFixture() as unknown as Record<string, unknown>)] });

    expect((await failure(listWorkoutSessions(SESSION, 'COMPLETED'))).kind).toBe('invalid-response');
  });

  test('refuses an answer that is not a list', async () => {
    backend.on('GET', SESSIONS, { status: 200, body: { sessions: [] } });

    expect((await failure(listWorkoutSessions(SESSION, 'IN_PROGRESS'))).kind).toBe('invalid-response');
  });

  test.each([401, 404, 500])('a %i answer is an http error with its status', async (status) => {
    backend.on('GET', SESSIONS, { status, body: { detail: 'nope' } });

    const error = await failure(listWorkoutSessions(SESSION, 'IN_PROGRESS'));

    expect([error.kind, error.status]).toEqual(['http', status]);
  });

  test('a dropped connection is a network error', async () => {
    backend.on('GET', SESSIONS, 'network-error');

    expect((await failure(listWorkoutSessions(SESSION, 'IN_PROGRESS'))).kind).toBe('network');
  });
});
