import { act, renderHook, waitFor } from '@testing-library/react-native';

import type { Session } from '../src/api';
import { useSavedEquipment } from '../src/profile/useSavedEquipment';
import { fakeToken, installMockFetch, type MockFetch, type Reply } from '../test-utils/mockFetch';

const SESSION: Session = { token: fakeToken(7), userId: 7 };
const PATH = '/users/7/profile';

let backend: MockFetch;

beforeEach(() => {
  backend = installMockFetch();
});

const body = (equipment: { id: number; name: string }[], noEquipment = false) => ({
  no_equipment: noEquipment,
  equipment,
});
const ok = (equipment: { id: number; name: string }[], noEquipment = false): Reply => ({
  status: 200,
  body: body(equipment, noEquipment),
});

const profileReads = () => backend.requests.filter((request) => request.path === PATH).length;

async function renderSaved(initial = { focused: true }) {
  return renderHook(({ focused }: { focused: boolean }) => useSavedEquipment(SESSION, focused), {
    initialProps: initial,
  });
}

const settled = (kind: string) => (result: { current: { state: { kind: string } } }) =>
  waitFor(() => expect(result.current.state.kind).toBe(kind));

describe('when it asks', () => {
  test('is loading until the Profile tab is looked at, and does not ask before', async () => {
    backend.on('GET', PATH, ok([{ id: 1, name: 'Dumbbell' }]));

    const { result } = await renderSaved({ focused: false });

    expect(result.current.state).toEqual({ kind: 'loading' });
    expect(profileReads()).toBe(0);
  });

  test('asks once the tab is focused and settles on what the backend says', async () => {
    backend.on('GET', PATH, ok([{ id: 1, name: 'Dumbbell' }]));

    const { result } = await renderSaved();
    await settled('ready')(result);

    expect(result.current.state).toEqual({
      kind: 'ready',
      saved: { equipment: [{ id: 1, name: 'Dumbbell' }], noEquipment: false },
    });
    expect(profileReads()).toBe(1);
    expect(backend.requests[0].headers.Authorization).toBe(`Bearer ${SESSION.token}`);
  });

  test('settles on "no equipment" and on "never said" as what they are', async () => {
    backend.on('GET', PATH, ok([], true));
    const first = await renderSaved();
    await settled('ready')(first.result);
    expect(first.result.current.state).toEqual({ kind: 'ready', saved: { equipment: [], noEquipment: true } });
    await first.unmount();

    backend.reset();
    backend.on('GET', PATH, ok([]));
    const second = await renderSaved();
    await settled('ready')(second.result);
    expect(second.result.current.state).toEqual({ kind: 'ready', saved: { equipment: [], noEquipment: false } });
  });

  test('a user with no profile settles on nothing saved', async () => {
    backend.on('GET', PATH, { status: 404, body: { detail: 'no profile found for user 7' } });

    const { result } = await renderSaved();
    await settled('ready')(result);

    expect(result.current.state).toEqual({ kind: 'ready', saved: null });
  });

  test('asks again each time the tab regains focus, and shows the last answer meanwhile', async () => {
    backend.on('GET', PATH, ok([{ id: 1, name: 'Dumbbell' }]));
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    backend.on('GET', PATH, async (): Promise<Reply> => {
      await gate;
      return ok([{ id: 2, name: 'Bench' }]);
    });
    const { result, rerender } = await renderSaved();
    await settled('ready')(result);

    await rerender({ focused: false });
    await rerender({ focused: true });

    // asking again over an answer does not flash "loading"
    expect(result.current.state.kind).toBe('ready');
    expect(profileReads()).toBe(2);
    release();
    await waitFor(() =>
      expect(result.current.state).toEqual({
        kind: 'ready',
        saved: { equipment: [{ id: 2, name: 'Bench' }], noEquipment: false },
      }),
    );
  });

  test('never asks twice at once: a new focus joins the request on its way', async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    backend.on('GET', PATH, async (): Promise<Reply> => {
      await gate;
      return ok([]);
    });
    const { result, rerender } = await renderSaved();

    await rerender({ focused: false });
    await rerender({ focused: true });

    expect(profileReads()).toBe(1);
    release();
    await settled('ready')(result);
  });
});

describe('when it cannot be had', () => {
  test('says so, and says nothing is saved that the backend did not say', async () => {
    backend.on('GET', PATH, 'network-error');

    const { result } = await renderSaved();
    await settled('error')(result);

    expect(result.current.state).toEqual({
      kind: 'error',
      message: "Can't reach Formiq. Check your connection and try again.",
      retryable: true,
    });
  });

  test('a failed refresh replaces the last answer: an old one that could not be confirmed is not shown as current', async () => {
    backend.on('GET', PATH, ok([{ id: 1, name: 'Dumbbell' }]));
    backend.on('GET', PATH, { status: 500 });
    const { result, rerender } = await renderSaved();
    await settled('ready')(result);

    await rerender({ focused: false });
    await rerender({ focused: true });

    await settled('error')(result);
  });

  test('"Try again" asks again, showing that it is asking, and recovers', async () => {
    backend.on('GET', PATH, { status: 500 });
    backend.on('GET', PATH, ok([{ id: 4, name: 'Treadmill' }]));
    const { result } = await renderSaved();
    await settled('error')(result);

    await act(async () => result.current.retry());

    await settled('ready')(result);
    expect(profileReads()).toBe(2);
  });

  test('an expired session cannot be retried: only logging in again helps', async () => {
    backend.on('GET', PATH, { status: 401 });

    const { result } = await renderSaved();
    await settled('error')(result);

    expect(result.current.state).toMatchObject({
      kind: 'error',
      message: 'Your session has expired. Log in again.',
      retryable: false,
    });
  });

  test('an answer the app cannot read is an error, not a smaller list', async () => {
    backend.on('GET', PATH, {
      status: 200,
      body: { no_equipment: false, equipment: [{ id: 1, name: 'Dumbbell' }, { id: 'x' }] },
    });

    const { result } = await renderSaved();
    await settled('error')(result);

    expect(result.current.state).toMatchObject({ kind: 'error', retryable: true });
  });
});

describe('replace', () => {
  test('shows an answer the backend gave to a change, at once', async () => {
    backend.on('GET', PATH, ok([{ id: 1, name: 'Dumbbell' }]));
    const { result } = await renderSaved();
    await settled('ready')(result);

    await act(async () => result.current.replace({ equipment: [{ id: 2, name: 'Bench' }], noEquipment: false }));

    expect(result.current.state).toEqual({
      kind: 'ready',
      saved: { equipment: [{ id: 2, name: 'Bench' }], noEquipment: false },
    });
    // it asked for nothing more
    expect(profileReads()).toBe(1);
  });

  test('a read already on its way is not shown: it may predate the change', async () => {
    backend.on('GET', PATH, ok([{ id: 1, name: 'Dumbbell' }]));
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    backend.on('GET', PATH, async (): Promise<Reply> => {
      await gate;
      // what the backend said before the change
      return ok([{ id: 1, name: 'Dumbbell' }]);
    });
    const { result, rerender } = await renderSaved();
    await settled('ready')(result);
    await rerender({ focused: false });
    await rerender({ focused: true });
    expect(profileReads()).toBe(2);

    await act(async () => result.current.replace({ equipment: [{ id: 2, name: 'Bench' }], noEquipment: false }));
    release();
    await act(async () => undefined);

    expect(result.current.state).toEqual({
      kind: 'ready',
      saved: { equipment: [{ id: 2, name: 'Bench' }], noEquipment: false },
    });
  });

  test('a failed read already on its way does not replace it either', async () => {
    backend.on('GET', PATH, ok([{ id: 1, name: 'Dumbbell' }]));
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    backend.on('GET', PATH, async (): Promise<Reply> => {
      await gate;
      return { status: 500 };
    });
    const { result, rerender } = await renderSaved();
    await settled('ready')(result);
    await rerender({ focused: false });
    await rerender({ focused: true });

    await act(async () => result.current.replace({ equipment: [], noEquipment: true }));
    release();
    await act(async () => undefined);

    expect(result.current.state).toEqual({ kind: 'ready', saved: { equipment: [], noEquipment: true } });
  });

  test('a read asked for after the change is shown as usual', async () => {
    backend.on('GET', PATH, ok([{ id: 1, name: 'Dumbbell' }]));
    backend.on('GET', PATH, ok([{ id: 2, name: 'Bench' }]));
    const { result, rerender } = await renderSaved();
    await settled('ready')(result);
    await act(async () => result.current.replace({ equipment: [{ id: 2, name: 'Bench' }], noEquipment: false }));

    await rerender({ focused: false });
    await rerender({ focused: true });

    await waitFor(() => expect(profileReads()).toBe(2));
    await waitFor(() =>
      expect(result.current.state).toEqual({
        kind: 'ready',
        saved: { equipment: [{ id: 2, name: 'Bench' }], noEquipment: false },
      }),
    );
  });

  test('is harmless once the tab has gone', async () => {
    backend.on('GET', PATH, ok([]));
    const { result, unmount } = await renderSaved();
    await settled('ready')(result);

    await unmount();

    expect(() => result.current.replace({ equipment: [], noEquipment: true })).not.toThrow();
  });
});

