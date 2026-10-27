import { act, renderHook, waitFor } from '@testing-library/react-native';

import type { SavedEquipment, Session } from '../src/api';
import { useSaveEquipment } from '../src/profile/useSaveEquipment';
import { fakeToken, installMockFetch, type MockFetch, type Reply } from '../test-utils/mockFetch';

const SESSION: Session = { token: fakeToken(7), userId: 7 };
const PATH = '/users/7/profile';
const CHOICE = { equipment_ids: [1, 2], no_equipment: false };

let backend: MockFetch;

beforeEach(() => {
  backend = installMockFetch();
});

const ok = (equipment: { id: number; name: string }[], noEquipment = false): Reply => ({
  status: 200,
  body: { no_equipment: noEquipment, equipment },
});
const patches = () => backend.requests.filter((request) => request.method === 'PATCH').length;

function renderSave(onSaved: (saved: SavedEquipment) => void = jest.fn()) {
  return renderHook(() => useSaveEquipment(SESSION, onSaved));
}

// holds a reply until the test lets it go
function gated(reply: Reply) {
  let release: () => void = () => undefined;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { release, responder: async (): Promise<Reply> => (await gate, reply) };
}

describe('useSaveEquipment', () => {
  test('is idle and asks nothing until a save is asked for', async () => {
    const { result } = await renderSave();

    expect(result.current.state).toEqual({ kind: 'idle' });
    expect(backend.requests).toHaveLength(0);
  });

  test('shows that it is saving, then what the backend answered, handing the same answer to onSaved', async () => {
    const held = gated(ok([{ id: 1, name: 'Dumbbell' }, { id: 2, name: 'Bench' }]));
    backend.on('PATCH', PATH, held.responder);
    const onSaved = jest.fn();
    const { result } = await renderSave(onSaved);

    await act(async () => result.current.save(CHOICE));

    expect(result.current.state).toEqual({ kind: 'saving' });
    expect(onSaved).not.toHaveBeenCalled();
    held.release();
    await waitFor(() => expect(result.current.state.kind).toBe('saved'));
    const answer = { equipment: [{ id: 1, name: 'Dumbbell' }, { id: 2, name: 'Bench' }], noEquipment: false };
    expect(result.current.state).toEqual({ kind: 'saved', saved: answer });
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(onSaved).toHaveBeenCalledWith(answer);
    expect(backend.requests[0].body).toEqual(CHOICE);
    expect(backend.requests[0].headers.Authorization).toBe(`Bearer ${SESSION.token}`);
  });

  test('hands over what the backend kept, not what it was asked to', async () => {
    backend.on('PATCH', PATH, ok([{ id: 1, name: 'Dumbbell' }]));
    const onSaved = jest.fn();
    const { result } = await renderSave(onSaved);

    await act(async () => result.current.save(CHOICE));

    await waitFor(() => expect(result.current.state.kind).toBe('saved'));
    expect(onSaved).toHaveBeenCalledWith({ equipment: [{ id: 1, name: 'Dumbbell' }], noEquipment: false });
  });

  test('ignores a press while a save is out: one request', async () => {
    const held = gated(ok([{ id: 1, name: 'Dumbbell' }]));
    backend.on('PATCH', PATH, held.responder);
    const onSaved = jest.fn();
    const { result } = await renderSave(onSaved);

    await act(async () => {
      result.current.save(CHOICE);
      result.current.save({ equipment_ids: [3], no_equipment: false });
    });

    expect(patches()).toBe(1);
    held.release();
    await waitFor(() => expect(result.current.state.kind).toBe('saved'));
    expect(onSaved).toHaveBeenCalledTimes(1);
  });

  test('a failure is an error: nothing handed over, nothing saved to show', async () => {
    backend.on('PATCH', PATH, 'network-error');
    const onSaved = jest.fn();
    const { result } = await renderSave(onSaved);

    await act(async () => result.current.save(CHOICE));

    await waitFor(() => expect(result.current.state.kind).toBe('error'));
    expect(result.current.state).toEqual({
      kind: 'error',
      message: "Can't reach Formiq. Check your connection and try again.",
      retryable: true,
    });
    expect(onSaved).not.toHaveBeenCalled();
  });

  test.each([
    ['a server error', { status: 500 } as Reply, "Something went wrong on Formiq's side. Try again."],
    [
      'a refused id',
      { status: 400, body: { detail: 'equipment 9 is retired' } } as Reply,
      "Formiq couldn't accept some of that equipment. Go back, open the list again and choose again.",
    ],
    ['an answer it cannot read', { status: 200, body: { no_equipment: 'yes' } } as Reply, 'Formiq sent an answer the app could not read. Try again.'],
  ])('%s is an error the person can try again', async (_name, reply, message) => {
    backend.on('PATCH', PATH, reply);
    const onSaved = jest.fn();
    const { result } = await renderSave(onSaved);

    await act(async () => result.current.save(CHOICE));

    await waitFor(() => expect(result.current.state.kind).toBe('error'));
    expect(result.current.state).toEqual({ kind: 'error', message, retryable: true });
    expect(onSaved).not.toHaveBeenCalled();
  });

  test('an expired session cannot be retried: only logging in again helps', async () => {
    backend.on('PATCH', PATH, { status: 401 });
    const { result } = await renderSave();

    await act(async () => result.current.save(CHOICE));

    await waitFor(() => expect(result.current.state.kind).toBe('error'));
    expect(result.current.state).toMatchObject({
      kind: 'error',
      message: 'Your session has expired. Log in again.',
      retryable: false,
    });
  });

  test('can be asked again after a failure, and then saves', async () => {
    backend.on('PATCH', PATH, { status: 500 });
    backend.on('PATCH', PATH, ok([{ id: 2, name: 'Bench' }]));
    const onSaved = jest.fn();
    const { result } = await renderSave(onSaved);
    await act(async () => result.current.save(CHOICE));
    await waitFor(() => expect(result.current.state.kind).toBe('error'));

    await act(async () => result.current.save(CHOICE));

    await waitFor(() => expect(result.current.state.kind).toBe('saved'));
    expect(patches()).toBe(2);
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(onSaved).toHaveBeenCalledWith({ equipment: [{ id: 2, name: 'Bench' }], noEquipment: false });
  });

  test('still hands the answer over when the screen that asked has gone', async () => {
    const held = gated(ok([{ id: 1, name: 'Dumbbell' }]));
    backend.on('PATCH', PATH, held.responder);
    const onSaved = jest.fn();
    const { result, unmount } = await renderSave(onSaved);
    await act(async () => result.current.save(CHOICE));

    await unmount();
    held.release();

    await waitFor(() => expect(onSaved).toHaveBeenCalledWith({ equipment: [{ id: 1, name: 'Dumbbell' }], noEquipment: false }));
  });

  test('says nothing more of a failure once the screen has gone', async () => {
    const held = gated({ status: 500 });
    backend.on('PATCH', PATH, held.responder);
    const onSaved = jest.fn();
    const { result, unmount } = await renderSave(onSaved);
    await act(async () => result.current.save(CHOICE));

    await unmount();
    held.release();

    await act(async () => undefined);
    expect(onSaved).not.toHaveBeenCalled();
  });
});
