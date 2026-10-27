import { act, renderHook, waitFor } from '@testing-library/react-native';

import type { Session } from '../src/api';
import { TODAY_WORKOUT_FRESH_MS, useTodayWorkout } from '../src/home/useTodayWorkout';
import { fixClockAt } from '../test-utils/clock';
import { fakeToken, installMockFetch, type MockFetch, type Reply } from '../test-utils/mockFetch';
import { backendWorkouts, NOW, plan, readsMade, session as sessionFixture, TOMORROW } from '../test-utils/workoutFixtures';

const SESSION: Session = { token: fakeToken(7), userId: 7 };
const READS_PER_LOAD = 3;

let backend: MockFetch;
let clock: ReturnType<typeof fixClockAt>;

beforeEach(() => {
  backend = installMockFetch();
  clock = fixClockAt(NOW);
});

afterEach(() => clock.restore());

type Props = { session?: Session; focused: boolean };

async function renderToday(initial: Props = { focused: true }) {
  const view = await renderHook(({ session, focused }: Props) => useTodayWorkout(session ?? SESSION, focused), {
    initialProps: initial,
  });
  return view;
}

const settled = (kind: string) => (result: { current: { state: { kind: string } } }) =>
  waitFor(() => expect(result.current.state.kind).toBe(kind));

const advance = (ms: number) => clock.set(new Date(Date.now() + ms));

describe('when it asks', () => {
  test('starts out loading, asks once Home is focused, and settles on what the backend says', async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    backend.on('GET', '/users/7/workout-plans', async (): Promise<Reply> => {
      await gate;
      return { status: 200, body: [plan({ id: 41 })] };
    });
    backend.on('GET', '/users/7/workout-sessions', async (): Promise<Reply> => {
      await gate;
      return { status: 200, body: [] };
    });

    const { result } = await renderToday();
    expect(result.current.state).toEqual({ kind: 'loading' });
    release();
    await settled('scheduled')(result);

    expect(result.current.state).toMatchObject({ kind: 'scheduled', plan: { id: 41 } });
    expect(backend.requests).toHaveLength(READS_PER_LOAD);
  });

  test('does not ask while Home is not focused, and asks when it becomes so', async () => {
    backendWorkouts(backend, 7);

    const { result, rerender } = await renderToday({ focused: false });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(backend.requests).toHaveLength(0);
    expect(result.current.state).toEqual({ kind: 'loading' });

    await rerender({ focused: true });
    await settled('none')(result);

    expect(backend.requests).toHaveLength(READS_PER_LOAD);
  });

  test('draws without asking again: repeated renders of the same screen are not new requests', async () => {
    backendWorkouts(backend, 7);
    const { result, rerender } = await renderToday();
    await settled('none')(result);

    for (let draw = 0; draw < 6; draw += 1) await rerender({ focused: true });

    expect(backend.requests).toHaveLength(READS_PER_LOAD);
  });

  test('a focus while a request is out joins it: it never asks twice at once', async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const held = async (body: unknown[]): Promise<Reply> => {
      await gate;
      return { status: 200, body };
    };
    backend.on('GET', '/users/7/workout-plans', () => held([]));
    backend.on('GET', '/users/7/workout-sessions', () => held([]));

    const { result, rerender } = await renderToday();
    await waitFor(() => expect(backend.requests).toHaveLength(READS_PER_LOAD));
    // away and back while it is still being read
    await rerender({ focused: false });
    await rerender({ focused: true });
    await rerender({ focused: false });
    await rerender({ focused: true });
    expect(backend.requests).toHaveLength(READS_PER_LOAD);

    release();
    await settled('none')(result);
    expect(backend.requests).toHaveLength(READS_PER_LOAD);
  });

  test('regaining focus within the fresh window shows the last answer and does not ask again', async () => {
    backendWorkouts(backend, 7, { plans: [plan({ id: 41 })] });
    const { result, rerender } = await renderToday();
    await settled('scheduled')(result);

    await rerender({ focused: false });
    advance(TODAY_WORKOUT_FRESH_MS - 1000);
    await rerender({ focused: true });

    expect(result.current.state.kind).toBe('scheduled');
    expect(backend.requests).toHaveLength(READS_PER_LOAD);
  });

  test('regaining focus after the fresh window asks again, and keeps showing the old answer while it does', async () => {
    const answers = backendWorkouts(backend, 7, { plans: [plan({ id: 41, name: 'Before' })] });
    const { result, rerender } = await renderToday();
    await settled('scheduled')(result);

    answers.plans = [plan({ id: 42, name: 'After' })];
    await rerender({ focused: false });
    advance(TODAY_WORKOUT_FRESH_MS + 1000);
    await rerender({ focused: true });
    // no flash of "loading" over an answer already shown
    expect(result.current.state.kind).not.toBe('loading');

    await waitFor(() => expect(result.current.state).toMatchObject({ plan: { id: 42 } }));
    expect(backend.requests).toHaveLength(2 * READS_PER_LOAD);
  });

  test("a new calendar day is a new answer to ask for, even inside the fresh window: the answer is for one day", async () => {
    const answers = backendWorkouts(backend, 7, { plans: [plan({ id: 41 })] });
    const { result, rerender } = await renderToday();
    await settled('scheduled')(result);

    answers.plans = [];
    await rerender({ focused: false });
    clock.set(new Date(2026, 9, 21, 0, 5));
    await rerender({ focused: true });

    await settled('none')(result);
    expect(readsMade(backend).filter((read) => read.includes('workout-plans')).pop()).toBe(
      `GET /users/7/workout-plans?status=PLANNED&scheduled_date=${TOMORROW}`,
    );
  });

  test('another user is another answer: the previous one is not used for them', async () => {
    backendWorkouts(backend, 7, { plans: [plan({ id: 41 })] });
    backendWorkouts(backend, 8, {});
    const { result, rerender } = await renderToday();
    await settled('scheduled')(result);

    await rerender({ focused: true, session: { token: fakeToken(8), userId: 8 } });

    await settled('none')(result);
    expect(readsMade(backend).some((read) => read.startsWith('GET /users/8/'))).toBe(true);
  });
});

describe('when it fails', () => {
  test('a failed read is an error state with a sentence for the person, never half an answer', async () => {
    backendWorkouts(backend, 7, { plans: [plan({ id: 41 })], completed: { status: 500 } });

    const { result } = await renderToday();
    await settled('error')(result);

    expect(result.current.state).toEqual({ kind: 'error', message: "Something went wrong on Formiq's side. Try again.", retryable: true });
  });

  // asking again helps unless the token itself is refused (a 401): then only signing in again does
  test.each([
    [{ status: 401 }, 'Your session has expired. Log in again.', false],
    ['network-error', "Can't reach Formiq. Check your connection and try again.", true],
    [{ status: 200, body: { not: 'a list' } }, 'Formiq sent an answer the app could not read. Try again.', true],
    [{ status: 503 }, "Formiq isn't available right now. Try again in a moment.", true],
    [{ status: 502 }, "Something went wrong on Formiq's side. Try again.", true],
    [{ status: 404 }, 'Something went wrong. Try again.', true],
  ] as const)('%j reads as "%s" (retryable: %s)', async (reply, sentence, retryable) => {
    backendWorkouts(backend, 7, { plans: reply });

    const { result } = await renderToday();
    await settled('error')(result);

    expect(result.current.state).toEqual({ kind: 'error', message: sentence, retryable });
  });

  test.each([
    ['the plans', { plans: { status: 401 } }],
    ['the in-progress sessions', { inProgress: { status: 401 } }],
    ['the completed sessions', { completed: { status: 401 } }],
  ] as const)('a 401 on any one of the reads, %s, is not retryable', async (_which, failing) => {
    backendWorkouts(backend, 7, { plans: [plan({ id: 41 })], ...failing });

    const { result } = await renderToday();
    await settled('error')(result);

    expect(result.current.state).toMatchObject({ kind: 'error', retryable: false });
  });

  test('a failure is not kept as fresh: the next focus asks again at once', async () => {
    const answers = backendWorkouts(backend, 7, { plans: { status: 500 } });
    const { result, rerender } = await renderToday();
    await settled('error')(result);

    answers.plans = [plan({ id: 41 })];
    await rerender({ focused: false });
    await rerender({ focused: true });

    await settled('scheduled')(result);
    expect(backend.requests).toHaveLength(2 * READS_PER_LOAD);
  });

  test('"retry" asks again, shows loading while it does, and settles on the new answer', async () => {
    let failing = true;
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    backend.on('GET', '/users/7/workout-plans', async (): Promise<Reply> => {
      if (failing) return { status: 500 };
      await gate;
      return { status: 200, body: [plan({ id: 41 })] };
    });
    backend.on('GET', '/users/7/workout-sessions', { status: 200, body: [] });
    const { result } = await renderToday();
    await settled('error')(result);

    failing = false;
    await act(async () => result.current.retry());
    expect(result.current.state).toEqual({ kind: 'loading' });
    release();
    await settled('scheduled')(result);

    expect(backend.requests).toHaveLength(2 * READS_PER_LOAD);
  });

  test('"retry" while a request is out does not start a second', async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    backend.on('GET', '/users/7/workout-plans', async () => {
      await gate;
      return { status: 200, body: [] };
    });
    backend.on('GET', '/users/7/workout-sessions', async () => {
      await gate;
      return { status: 200, body: [] };
    });
    const { result } = await renderToday();
    await waitFor(() => expect(backend.requests).toHaveLength(READS_PER_LOAD));

    await act(async () => {
      result.current.retry();
      result.current.retry();
    });
    release();
    await settled('none')(result);

    expect(backend.requests).toHaveLength(READS_PER_LOAD);
  });

  test('a refresh that fails replaces the old answer with the error: an answer not confirmed is not shown as current', async () => {
    const answers = backendWorkouts(backend, 7, { plans: [plan({ id: 41 })] });
    const { result, rerender } = await renderToday();
    await settled('scheduled')(result);

    answers.inProgress = { status: 500 };
    await rerender({ focused: false });
    advance(TODAY_WORKOUT_FRESH_MS + 1000);
    await rerender({ focused: true });

    await settled('error')(result);
  });

  test('"retry" keeps its identity from one draw to the next', async () => {
    backendWorkouts(backend, 7);
    const { result, rerender } = await renderToday();
    await settled('none')(result);
    const first = result.current.retry;

    await rerender({ focused: true });

    expect(result.current.retry).toBe(first);
  });

  test('an answer that arrives after the screen has gone changes nothing and raises nothing', async () => {
    const errors = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    backend.on('GET', '/users/7/workout-plans', async () => {
      await gate;
      return { status: 200, body: [] };
    });
    backend.on('GET', '/users/7/workout-sessions', async () => {
      await gate;
      return { status: 200, body: [sessionFixture({ status: 'IN_PROGRESS', completed_at: null })] };
    });
    const { unmount } = await renderToday();
    await waitFor(() => expect(backend.requests).toHaveLength(READS_PER_LOAD));

    await unmount();
    release();
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(errors).not.toHaveBeenCalled();
    errors.mockRestore();
  });
});

describe('after something changed the plans (invalidate)', () => {
  test('Home asks again the next time it is in focus, though the answer is still fresh', async () => {
    backendWorkouts(backend, 7, { plans: [plan({ id: 41 })] });
    const { result, rerender } = await renderToday({ focused: true });
    await settled('scheduled')(result);
    expect(backend.requests).toHaveLength(READS_PER_LOAD);

    // a workout was applied from the coach while Home was out of focus, a moment after Home loaded
    await rerender({ focused: false });
    await act(async () => {
      result.current.invalidate();
    });
    await rerender({ focused: true });

    await waitFor(() => expect(backend.requests).toHaveLength(2 * READS_PER_LOAD));
  });

  test('while Home is the screen in focus, it asks again at once and shows the new answer: a workout applied while Home was showing', async () => {
    const answers = backendWorkouts(backend, 7, { plans: [plan({ id: 41 })] });
    const { result } = await renderToday({ focused: true });
    await settled('scheduled')(result);
    expect(result.current.state).toMatchObject({ plan: { id: 41 } });

    // the coach saved a revision while Home (not the coach tab) was what the person looked at
    answers.plans = [plan({ id: 42 })];
    await act(async () => {
      result.current.invalidate();
    });

    await waitFor(() => expect(backend.requests).toHaveLength(2 * READS_PER_LOAD));
    await waitFor(() => expect(result.current.state).toMatchObject({ kind: 'scheduled', plan: { id: 42 } }));
  });

  test('a read that was already on its way when the plans changed is not the answer: it asks again, and the later answer stands', async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    // the first read of the plans is held, and answers with the plan as it was before the change
    backend.on('GET', '/users/7/workout-plans', async (): Promise<Reply> => {
      await gate;
      return { status: 200, body: [plan({ id: 41 })] };
    });
    backend.on('GET', '/users/7/workout-plans', { status: 200, body: [plan({ id: 42 })] });
    backend.on('GET', '/users/7/workout-sessions', { status: 200, body: [] });
    const { result } = await renderToday({ focused: true });
    await waitFor(() => expect(backend.requests.length).toBeGreaterThan(0));

    await act(async () => {
      result.current.invalidate();
    });
    await waitFor(() => expect(result.current.state).toMatchObject({ kind: 'scheduled', plan: { id: 42 } }));
    // the old read arrives late: it must not put the old plan back
    await act(async () => {
      release();
      await new Promise((resolve) => setTimeout(resolve, 20));
    });

    expect(result.current.state).toMatchObject({ kind: 'scheduled', plan: { id: 42 } });
  });

  test('a read in flight when the plans changed, with Home out of focus, is shown but not taken as current: the next focus asks again', async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    backend.on('GET', '/users/7/workout-plans', async (): Promise<Reply> => {
      await gate;
      return { status: 200, body: [plan({ id: 41 })] };
    });
    backend.on('GET', '/users/7/workout-plans', { status: 200, body: [plan({ id: 42 })] });
    backend.on('GET', '/users/7/workout-sessions', { status: 200, body: [] });
    const { result, rerender } = await renderToday({ focused: true });
    await waitFor(() => expect(backend.requests.length).toBeGreaterThan(0));
    await rerender({ focused: false });

    await act(async () => {
      result.current.invalidate();
    });
    // nothing is asked while Home is not on show
    expect(backend.requests).toHaveLength(READS_PER_LOAD);
    await act(async () => {
      release();
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    await rerender({ focused: true });

    await waitFor(() => expect(result.current.state).toMatchObject({ kind: 'scheduled', plan: { id: 42 } }));
    expect(backend.requests).toHaveLength(2 * READS_PER_LOAD);
  });

  test('with Home out of focus, nothing is asked until it is back in focus', async () => {
    backendWorkouts(backend, 7, { plans: [plan({ id: 41 })] });
    const { result, rerender } = await renderToday({ focused: true });
    await settled('scheduled')(result);
    await rerender({ focused: false });

    await act(async () => {
      result.current.invalidate();
    });
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(backend.requests).toHaveLength(READS_PER_LOAD);
  });

  test('without it, coming back within the fresh window asks nothing', async () => {
    backendWorkouts(backend, 7, { plans: [plan({ id: 41 })] });
    const { result, rerender } = await renderToday({ focused: true });
    await settled('scheduled')(result);

    await rerender({ focused: false });
    await rerender({ focused: true });
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(backend.requests).toHaveLength(READS_PER_LOAD);
  });
});
