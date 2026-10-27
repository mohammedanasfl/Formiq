import { act, renderHook } from '@testing-library/react-native';

import { ApiError, type WorkoutPlan } from '../src/api';
import type { ChatItem } from '../src/coach/chatState';
import { coachOpening } from '../src/coach/opening';
import type { CoachContext } from '../src/shell/routes';
import { useCoachChat } from '../src/coach/useCoachChat';
import { mockPendingProposal, mockProposal, mockSavedPlan, MOCK_REPLACED_PLAN_ID } from '../src/mock/coachProposalsMock';
import { fakeGateway } from '../test-utils/coachGateway';

const NOW = new Date(2026, 9, 22, 9, 0, 0);
const CORE: CoachContext = { workoutId: MOCK_REPLACED_PLAN_ID, title: 'Core & Abs Focus' };
const LEGS: CoachContext = { workoutId: 52, title: 'Leg Day' };
const EDIT = mockProposal('edit', NOW, 2);
const REFINED = mockProposal('edit-refined', NOW, 3);

// `active` is whether the screen is on show: it is, unless a test says otherwise (and a rerender that leaves it out is on show)
async function start(launch: CoachContext | null = null, active?: boolean) {
  const fake = fakeGateway();
  const onApplied = jest.fn();
  const view = await renderHook(
    (props: { launch: CoachContext | null; active?: boolean }) => useCoachChat(fake.gateway, coachOpening, props.launch, { onApplied, active: props.active }),
    { initialProps: { launch, active } },
  );
  return { ...view, fake, onApplied };
}
type Chat = Awaited<ReturnType<typeof start>>;

const texts = (chat: Chat) => chat.result.current.items.map((item) => (item.kind === 'message' ? item.text : item.kind));
const cards = (chat: Chat) => chat.result.current.items.filter((item): item is Extract<ChatItem, { kind: 'proposal' }> => item.kind === 'proposal');
const send = (chat: Chat, text: string) =>
  act(async () => {
    chat.result.current.send(text, { expectsWorkout: true });
  });
const answer = (chat: Chat, reply: string, proposal: typeof EDIT | null = null) =>
  act(async () => {
    chat.fake.sends.shift()!.resolve({ reply, proposal });
  });

describe('a conversation opened from no workout', () => {
  test('opens with a greeting of the app\'s own and the ways to ask for a workout', async () => {
    const chat = await start();

    expect(texts(chat)).toEqual([expect.stringMatching(/Formiq Coach/)]);
    expect(chat.result.current.launch).toBeNull();
    expect(chat.result.current.suggestions.map((reply) => reply.label)).toEqual([
      'Create a 25-minute upper-body workout',
      'Suggest a different workout for today',
    ]);
  });

  test('does not send the greeting to the coach: the conversation it sees starts with what the user said', async () => {
    const chat = await start();

    await send(chat, 'Create a 25-minute upper-body workout.');

    expect(chat.fake.sends[0].request).toEqual({
      message: 'Create a 25-minute upper-body workout.',
      history: [],
    });
  });
});

describe('a conversation opened from a workout', () => {
  test('opens with the coach asking about that workout by name, and offers ways to change it', async () => {
    const chat = await start(CORE);

    expect(texts(chat)).toEqual(['What would you like to change in “Core & Abs Focus”?']);
    expect(chat.result.current.launch).toEqual(CORE);
    expect(chat.result.current.suggestions.map((reply) => reply.label)).toEqual([
      'Make it shorter',
      'Make it easier',
      'Suggest a different workout',
    ]);
  });

  test('tells the coach which workout is meant by its id, with the user\'s message: the question that names it is not sent', async () => {
    const chat = await start(CORE);

    await send(chat, 'Suggest a different ab workout for today.');

    expect(chat.fake.sends[0].request).toEqual({
      message: 'Suggest a different ab workout for today.',
      history: [],
      workoutPlanId: MOCK_REPLACED_PLAN_ID,
    });
  });

  test('is opened as no workout in particular when the workout has no saved id (an example one)', async () => {
    const chat = await start({ workoutId: 'mock-workout-today', title: 'Core & Abs Focus' });

    expect(texts(chat)).toEqual([expect.stringMatching(/Formiq Coach/)]);
    await send(chat, 'a different ab workout');
    expect(chat.fake.sends[0].request).not.toHaveProperty('workoutPlanId');
  });

  test('keeps the saved workout across a refinement: every request names it, and both proposals are compared with it by the backend', async () => {
    const chat = await start(CORE);
    await send(chat, 'a different ab workout');
    expect(chat.fake.sends[0].request.workoutPlanId).toBe(MOCK_REPLACED_PLAN_ID);
    await answer(chat, 'Here is an updated version.', EDIT);
    await send(chat, 'Keep the same duration, but make it easier.');

    // the refinement carries the conversation (what was said, not the question the screen asked) and names the workout again
    expect(chat.fake.sends[0].request.history.map((turn) => turn.role)).toEqual(['user', 'coach']);
    expect(chat.fake.sends[0].request.workoutPlanId).toBe(MOCK_REPLACED_PLAN_ID);
    await answer(chat, 'Here is a gentler version.', REFINED);

    expect(cards(chat).map((card) => [card.proposal.revision?.replaces_plan_id, card.proposal.changes?.compared_with_plan_id, card.phase.kind])).toEqual([
      [MOCK_REPLACED_PLAN_ID, MOCK_REPLACED_PLAN_ID, 'superseded'],
      [MOCK_REPLACED_PLAN_ID, MOCK_REPLACED_PLAN_ID, 'ready'],
    ]);
    // nothing is applied or dismissed by asking
    expect(chat.fake.gateway.approve).not.toHaveBeenCalled();
    expect(chat.fake.gateway.reject).not.toHaveBeenCalled();
  });
});

describe('opening the coach from a workout while the conversation exists', () => {
  test('a different workout starts a new conversation about it, and an answer still on its way to the old one is dropped', async () => {
    const chat = await start(CORE);
    await send(chat, 'a different ab workout');

    await chat.rerender({ launch: LEGS });

    expect(texts(chat)).toEqual(['What would you like to change in “Leg Day”?']);
    expect(chat.result.current.launch).toEqual(LEGS);
    await answer(chat, 'Here is an updated version.', EDIT);
    expect(texts(chat)).toEqual(['What would you like to change in “Leg Day”?']);
    expect(cards(chat)).toHaveLength(0);
    expect(chat.result.current.waiting).toBe(false);
  });

  test('the same workout again carries on with the conversation', async () => {
    const chat = await start(CORE);
    await send(chat, 'a different ab workout');
    await answer(chat, 'Here is an updated version.', EDIT);

    await chat.rerender({ launch: { ...CORE } });

    expect(cards(chat)).toHaveLength(1);
    // the question, the user's message, the answer and the card: nothing was started over
    expect(texts(chat)).toHaveLength(4);
  });

  test('no workout (the tab opened another way) changes nothing, and the conversation keeps its workout', async () => {
    const chat = await start(CORE);
    await send(chat, 'a different ab workout');
    await answer(chat, 'Here is an updated version.', EDIT);

    await chat.rerender({ launch: null });

    expect(cards(chat)).toHaveLength(1);
    expect(chat.result.current.launch).toEqual(CORE);
  });

  test('while a workout is being applied, the new conversation waits for the answer', async () => {
    const chat = await start(CORE);
    await send(chat, 'a different ab workout');
    await answer(chat, 'Here is an updated version.', EDIT);
    await act(async () => {
      void chat.result.current.apply(cards(chat)[0].id);
    });

    await chat.rerender({ launch: LEGS });
    // not yet: the approval cannot be called back
    expect(chat.result.current.launch).toEqual(CORE);
    expect(chat.result.current.applying).toBe(true);

    await act(async () => {
      chat.fake.approvals[0].resolve(mockSavedPlan(EDIT, 77));
    });

    expect(chat.result.current.launch).toEqual(LEGS);
    expect(texts(chat)).toEqual(['What would you like to change in “Leg Day”?']);
  });

  test('"Start over" goes back to a conversation about no workout in particular', async () => {
    const chat = await start(CORE);
    await send(chat, 'a different ab workout');

    await act(async () => {
      chat.result.current.reset();
    });

    expect(chat.result.current.launch).toBeNull();
    expect(texts(chat)).toEqual([expect.stringMatching(/Formiq Coach/)]);
  });
});

// "What is waiting for the person" is asked when the screen is shown and when a new conversation starts. Opening the coach
// from a workout does both in one render (the shell shows the tab and hands it the workout together), and must still be
// one request: the hook is mounted early, hidden, with no workout, and then shown with one.
describe('opening the coach from a workout: the waiting proposals are asked for once', () => {
  const startHidden = (options: { launch?: CoachContext | null; active?: boolean } = {}) => start(options.launch ?? null, options.active ?? false);
  const waitingCard = mockPendingProposal('edit', NOW, 7, 12);

  test('a hidden conversation shown with a workout asks once, not once for being shown and again for the new conversation', async () => {
    const chat = await startHidden();
    expect(chat.fake.gateway.pending).not.toHaveBeenCalled();

    await chat.rerender({ launch: LEGS, active: true });

    expect(chat.fake.gateway.pending).toHaveBeenCalledTimes(1);
    expect(chat.result.current.launch).toEqual(LEGS);
    expect(chat.result.current.items.map((item) => (item.kind === 'message' ? item.text : item.kind))).toEqual(['What would you like to change in “Leg Day”?']);
  });

  test('and the one answer is the one used: what is waiting is shown in the new conversation', async () => {
    const chat = await startHidden();
    chat.fake.waiting.list = [waitingCard];

    await chat.rerender({ launch: LEGS, active: true });

    expect(chat.fake.gateway.pending).toHaveBeenCalledTimes(1);
    expect(chat.result.current.items.at(-1)).toMatchObject({ kind: 'proposal', recovered: { createdAt: waitingCard.created_at } });
    expect(chat.result.current.items.filter((item) => item.kind === 'proposal')).toHaveLength(1);
  });

  test('a conversation that has no answer yet when it is replaced by the new one still asks once for it', async () => {
    const chat = await startHidden();
    chat.fake.waiting.hold = true;

    await chat.rerender({ launch: LEGS, active: true });
    expect(chat.fake.lists).toHaveLength(1);
    await act(async () => {
      chat.fake.lists.shift()!.resolve([waitingCard]);
    });

    expect(chat.fake.gateway.pending).toHaveBeenCalledTimes(1);
    expect(chat.result.current.items.at(-1)).toMatchObject({ kind: 'proposal' });
  });

  test('shown from the workout it is already about, or from no workout, asks once as well', async () => {
    const chat = await startHidden({ launch: CORE });

    await chat.rerender({ launch: { ...CORE }, active: true });
    expect(chat.fake.gateway.pending).toHaveBeenCalledTimes(1);

    await chat.rerender({ launch: null, active: false });
    await chat.rerender({ launch: null, active: true });
    expect(chat.fake.gateway.pending).toHaveBeenCalledTimes(2);
  });

  test('already shown, a different workout starts a new conversation and asks once for it', async () => {
    const chat = await startHidden({ launch: CORE, active: true });
    expect(chat.fake.gateway.pending).toHaveBeenCalledTimes(1);

    await chat.rerender({ launch: LEGS, active: true });

    expect(chat.fake.gateway.pending).toHaveBeenCalledTimes(2);
  });

  test('while a workout is being applied the new conversation waits, and asks once when it starts', async () => {
    const chat = await startHidden({ launch: CORE, active: true });
    await send(chat, 'a different ab workout');
    await answer(chat, 'Here is an updated version.', EDIT);
    await act(async () => {
      void chat.result.current.apply(cards(chat)[0].id);
    });
    await chat.rerender({ launch: CORE, active: false });
    const before = chat.fake.gateway.pending.mock.calls.length;

    await chat.rerender({ launch: LEGS, active: true });
    expect(chat.fake.gateway.pending).toHaveBeenCalledTimes(before);

    await act(async () => {
      chat.fake.approvals[0].resolve(mockSavedPlan(EDIT, 77));
    });
    expect(chat.result.current.launch).toEqual(LEGS);
    expect(chat.fake.gateway.pending).toHaveBeenCalledTimes(before + 1);
  });
});

describe('an answer with nothing in it', () => {
  test('is a failure that can be tried again, never an empty bubble, and trying again asks the same thing once', async () => {
    const chat = await start();
    await send(chat, 'hello');

    await answer(chat, '   ', null);

    expect(chat.result.current.items.at(-1)).toMatchObject({ kind: 'failed', message: 'The coach sent an empty answer. Try again.', retryable: true });
    expect(texts(chat).filter((text) => text.trim() === '')).toEqual([]);

    await act(async () => {
      chat.result.current.retry();
    });
    expect(chat.fake.sends).toHaveLength(1);
    expect(chat.fake.sends[0].request.message).toBe('hello');
    expect(chat.result.current.items.filter((item) => item.kind === 'message' && item.role === 'user')).toHaveLength(1);
  });

  test('a workout with no words is shown as the card alone', async () => {
    const chat = await start();
    await send(chat, 'a workout');

    await answer(chat, '', EDIT);

    expect(cards(chat)).toHaveLength(1);
    expect(texts(chat).filter((text) => text.trim() === '')).toEqual([]);
  });
});

describe('failures of a message', () => {
  const fail = (chat: Chat, error: unknown) =>
    act(async () => {
      chat.fake.sends.shift()!.reject(error);
    });

  test.each([
    ['a lost connection', new ApiError('network', null, null), true],
    ['an answer that took too long', new ApiError('timeout', null, null), true],
    ['an answer the app could not read', new ApiError('invalid-response', 200, null), true],
    ['the coach being unavailable', new ApiError('http', 502, 'the AI coach could not answer; try again later'), true],
    ['an expired session', new ApiError('http', 401, 'could not validate credentials'), false],
  ])('%s: the message stays, and trying again is offered only where it can help (%s)', async (_name, error, retryable) => {
    const chat = await start();
    await send(chat, 'a workout');

    await fail(chat, error);

    expect(chat.result.current.items.at(-1)).toMatchObject({ kind: 'failed', retryable });
    expect(chat.result.current.items.filter((item) => item.kind === 'message' && item.role === 'user')).toHaveLength(1);
    let retried = false;
    await act(async () => {
      retried = chat.result.current.retry();
    });
    expect(retried).toBe(retryable);
    expect(chat.fake.sends).toHaveLength(retryable ? 1 : 0);
  });

  test('after a new message, an older failure can no longer be tried again, and trying again repeats the newest request only', async () => {
    const chat = await start();
    await send(chat, 'first');
    await fail(chat, new ApiError('http', 502, 'x'));
    await send(chat, 'second');
    await fail(chat, new ApiError('http', 502, 'x'));

    const failures = chat.result.current.items.filter((item) => item.kind === 'failed');
    expect(failures.map((item) => item.kind === 'failed' && item.retryable)).toEqual([false, true]);

    await act(async () => {
      chat.result.current.retry();
    });
    expect(chat.fake.sends.map((entry) => entry.request.message)).toEqual(['second']);
  });

  test('a second request is never started while the first is waiting, however often the button is pressed', async () => {
    const chat = await start();

    await act(async () => {
      chat.result.current.send('a workout');
      chat.result.current.send('a workout');
      chat.result.current.send('a workout again');
    });

    expect(chat.fake.gateway.send).toHaveBeenCalledTimes(1);
  });
});

describe('after the backend confirmed a workout', () => {
  async function applyEdit(chat: Chat) {
    await send(chat, 'a different ab workout');
    await answer(chat, 'Here is an updated version.', EDIT);
    await act(async () => {
      void chat.result.current.apply(cards(chat)[0].id);
    });
  }

  test("the card holds the plan the backend answered with, and the screen is told once", async () => {
    const chat = await start(CORE);
    await applyEdit(chat);
    const saved: WorkoutPlan = mockSavedPlan(EDIT, 77);

    await act(async () => {
      chat.fake.approvals[0].resolve(saved);
    });

    expect(cards(chat)[0].phase).toEqual({ kind: 'applied', planId: 77, name: saved.name, scheduledDate: saved.scheduled_date });
    expect(chat.onApplied).toHaveBeenCalledTimes(1);
    expect(chat.onApplied).toHaveBeenCalledWith(saved);
  });

  test('nothing is reported while the approval is out, or when it failed: the workout is not saved', async () => {
    const chat = await start(CORE);
    await applyEdit(chat);
    expect(chat.onApplied).not.toHaveBeenCalled();

    await act(async () => {
      chat.fake.approvals[0].reject(new ApiError('http', 409, 'this proposal has expired: ask the coach for a new one'));
    });

    expect(cards(chat)[0].phase).toMatchObject({ kind: 'apply-failed' });
    expect(chat.onApplied).not.toHaveBeenCalled();
  });

  test('is reported even when the screen is gone by then: the backend saved it all the same', async () => {
    const chat = await start(CORE);
    await applyEdit(chat);

    await chat.unmount();
    await act(async () => {
      chat.fake.approvals[0].resolve(mockSavedPlan(EDIT, 77));
    });

    expect(chat.onApplied).toHaveBeenCalledTimes(1);
  });
});
