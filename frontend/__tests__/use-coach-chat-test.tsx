import { act, renderHook, waitFor } from '@testing-library/react-native';

import { ApiError, type PendingProposal, type WorkoutPlan } from '../src/api';
import type { ChatItem } from '../src/coach/chatState';
import { coachOpening } from '../src/coach/opening';
import { TARGET_UNAVAILABLE } from '../src/coach/coachErrors';
import { useCoachChat } from '../src/coach/useCoachChat';
import { MOCK_OPENING } from '../src/mock/coachMock';
import { mockPendingProposal, mockProposal, mockSavedPlan } from '../src/mock/coachProposalsMock';
import { fakeGateway, type FakeGateway } from '../test-utils/coachGateway';

const NOW = new Date(2026, 9, 22, 9, 0, 0);
const PROPOSALS = {
  new: mockProposal('new', NOW, 1),
  edit: mockProposal('edit', NOW, 2),
  refined: mockProposal('edit-refined', NOW, 3),
};

// the conversation, as the screen has it: `launch` is the workout it was opened from, `active` whether it is on show
async function start({
  launch = null,
  active = true,
  onApplied,
  waiting,
}: {
  launch?: { workoutId: number | string; title: string } | null;
  active?: boolean;
  onApplied?: (plan: WorkoutPlan) => void;
  // what the backend already lists as waiting when the screen opens: the conversation after a restart
  waiting?: PendingProposal[];
} = {}) {
  const fake = fakeGateway();
  if (waiting) fake.waiting.list = waiting;
  const view = await renderHook(
    (props: { active: boolean }) => useCoachChat(fake.gateway, launch ? coachOpening : () => MOCK_OPENING, launch, { active: props.active, onApplied }),
    { initialProps: { active } },
  );
  return { ...view, fake };
}
type Chat = Awaited<ReturnType<typeof start>>;

const cards = (chat: Chat) => chat.result.current.items.filter((item): item is Extract<ChatItem, { kind: 'proposal' }> => item.kind === 'proposal');
const kinds = (chat: Chat) => chat.result.current.items.map((item) => item.kind);

// the coach answers the oldest request still waiting
const answer = (fake: FakeGateway, reply: string, proposal: (typeof PROPOSALS)[keyof typeof PROPOSALS] | null = null) =>
  act(async () => {
    fake.sends.shift()!.resolve({ reply, proposal });
  });

// asks for something and has it answered with a workout
async function askAndGet(chat: Chat, proposal: (typeof PROPOSALS)[keyof typeof PROPOSALS], message = 'a workout') {
  await act(async () => {
    chat.result.current.send(message);
  });
  await answer(chat.fake, 'Here is a workout.', proposal);
}

describe('sending a message', () => {
  test('asks the coach once, with the message without the spaces around it and the conversation so far', async () => {
    const chat = await start();

    let sent = false;
    await act(async () => {
      sent = chat.result.current.send('   Create a workout  \n');
    });

    expect(sent).toBe(true);
    expect(chat.fake.gateway.send).toHaveBeenCalledTimes(1);
    const { request } = chat.fake.sends[0];
    expect(request.message).toBe('Create a workout');
    expect(request.history.map((turn) => turn.role)).toEqual(['coach', 'user', 'coach']);
    expect(chat.result.current.waiting).toBe(true);
  });

  test('about no workout, sends exactly a message and its history: no proposal, no plan, no id', async () => {
    const chat = await start();
    await askAndGet(chat, PROPOSALS.edit);

    await act(async () => {
      chat.result.current.send('make it easier');
    });

    const { request } = chat.fake.sends[0];
    expect(Object.keys(request).sort()).toEqual(['history', 'message']);
    expect(JSON.stringify(request)).not.toMatch(/binding|proposal_id|replaces_plan|exercise_name|workout-plans|workoutPlanId/);
  });

  test('refuses a blank message, and asks nothing', async () => {
    const chat = await start();

    let sent = true;
    await act(async () => {
      sent = chat.result.current.send('  \n ');
    });

    expect(sent).toBe(false);
    expect(chat.fake.gateway.send).not.toHaveBeenCalled();
    expect(kinds(chat)).toEqual(['message', 'message', 'message']);
  });

  test('refuses a second message while the coach is still answering the first', async () => {
    const chat = await start();
    await act(async () => {
      chat.result.current.send('first');
    });

    let sent = true;
    await act(async () => {
      sent = chat.result.current.send('second');
    });

    expect(sent).toBe(false);
    expect(chat.fake.gateway.send).toHaveBeenCalledTimes(1);
    expect(chat.result.current.items.filter((item) => item.kind === 'message' && item.text === 'second')).toHaveLength(0);
  });

  test('two messages sent in the same instant ask once', async () => {
    const chat = await start();

    await act(async () => {
      chat.result.current.send('first');
      chat.result.current.send('second');
    });

    expect(chat.fake.gateway.send).toHaveBeenCalledTimes(1);
  });

  test('can send again once the coach has answered', async () => {
    const chat = await start();
    await act(async () => {
      chat.result.current.send('first');
    });
    await answer(chat.fake, 'ok');

    let sent = false;
    await act(async () => {
      sent = chat.result.current.send('second');
    });

    expect(sent).toBe(true);
  });
});

describe('a workout arrives', () => {
  test('a new workout is shown ready, as the backend sent it, and not as one recovered from before', async () => {
    const chat = await start();

    await askAndGet(chat, PROPOSALS.new);

    expect(cards(chat)).toHaveLength(1);
    expect(cards(chat)[0].phase).toEqual({ kind: 'ready' });
    expect(cards(chat)[0].recovered).toBeNull();
    expect(cards(chat)[0].proposal).toEqual(PROPOSALS.new);
  });

  test('a revision is shown as the backend sent it, with what it changes: nothing else is asked of anyone', async () => {
    const chat = await start();

    await askAndGet(chat, PROPOSALS.edit);

    expect(cards(chat)).toHaveLength(1);
    expect(cards(chat)[0].proposal.changes?.compared_with_plan_id).toBe(41);
    expect(chat.fake.gateway.approve).not.toHaveBeenCalled();
    expect(chat.fake.gateway.reject).not.toHaveBeenCalled();
    // the gateway has no way to read a saved plan: the comparison is the backend's
    expect(chat.fake.gateway).not.toHaveProperty('loadPlan');
  });

  test('the coach\'s words are shown before the workout', async () => {
    const chat = await start();

    await askAndGet(chat, PROPOSALS.edit);

    expect(kinds(chat).slice(-2)).toEqual(['message', 'proposal']);
  });
});

describe('the coach cannot answer', () => {
  test('shows why, keeps the message, and the request can be tried again with the same words and history', async () => {
    const chat = await start();
    await act(async () => {
      chat.result.current.send('Create a workout', { expectsWorkout: true });
    });
    const first = chat.fake.sends[0].request;

    await act(async () => {
      chat.fake.sends.shift()!.reject(new ApiError('network', null, null));
    });

    const failed = chat.result.current.items.at(-1);
    expect(failed).toMatchObject({ kind: 'failed', expectsWorkout: true, message: "Can't reach Formiq. Check your connection and try again." });
    expect(chat.result.current.waiting).toBe(false);

    await act(async () => {
      chat.result.current.retry();
    });

    expect(chat.fake.gateway.send).toHaveBeenCalledTimes(2);
    expect(chat.fake.sends[0].request).toEqual(first);
    expect(chat.result.current.items.filter((item) => item.kind === 'message' && item.text === 'Create a workout')).toHaveLength(1);
    expect(chat.result.current.items.at(-1)?.kind).toBe('pending');

    await answer(chat.fake, 'Here you go', PROPOSALS.new);
    expect(cards(chat)).toHaveLength(1);
    expect(kinds(chat)).not.toContain('failed');
  });

  describe('Try Again after more than one failure', () => {
    // "first" fails, then "second" is asked and fails too: two failed bubbles, only the latest can be asked again
    async function twoFailures() {
      const chat = await start();
      await act(async () => {
        chat.result.current.send('first');
      });
      await act(async () => {
        chat.fake.sends.shift()!.reject(new ApiError('http', 502, null));
      });
      await act(async () => {
        chat.result.current.send('second');
      });
      await act(async () => {
        chat.fake.sends.shift()!.reject(new ApiError('http', 502, null));
      });
      return chat;
    }
    const failures = (chat: Chat) => chat.result.current.items.filter((item): item is Extract<ChatItem, { kind: 'failed' }> => item.kind === 'failed');

    test('asks the latest request again, not the older bubble: the older one stays failed and cannot be asked again', async () => {
      const chat = await twoFailures();
      const [older, newer] = failures(chat);
      expect([older.retryable, newer.retryable]).toEqual([false, true]);

      let retried = false;
      await act(async () => {
        retried = chat.result.current.retry();
      });

      expect(retried).toBe(true);
      expect(chat.fake.gateway.send).toHaveBeenCalledTimes(3);
      expect(chat.fake.sends[0].request.message).toBe('second');
      // the older bubble is where it was, still failed; the newer one is the one being asked again
      expect(failures(chat)).toEqual([older]);
      expect(chat.result.current.items.find((item) => item.id === newer.id)).toMatchObject({ kind: 'pending' });
    });

    test('the answer lands under the question that was asked again, and the older failure is the only one left', async () => {
      const chat = await twoFailures();
      await act(async () => {
        chat.result.current.retry();
      });

      await answer(chat.fake, 'the answer to the second');

      const texts = chat.result.current.items.flatMap((item) => (item.kind === 'message' ? [item.text] : []));
      expect(texts.slice(-2)).toEqual(['second', 'the answer to the second']);
      expect(failures(chat)).toHaveLength(1);
      expect(chat.result.current.waiting).toBe(false);
    });

    test('with only a failure that cannot be helped (an expired session), nothing is asked again', async () => {
      const chat = await start();
      await act(async () => {
        chat.result.current.send('only');
      });
      await act(async () => {
        chat.fake.sends.shift()!.reject(new ApiError('http', 401, null));
      });

      let retried = true;
      await act(async () => {
        retried = chat.result.current.retry();
      });

      expect(retried).toBe(false);
      expect(chat.fake.gateway.send).toHaveBeenCalledTimes(1);
    });
  });

  test('retrying with nothing failed asks nothing', async () => {
    const chat = await start();

    let retried = true;
    await act(async () => {
      retried = chat.result.current.retry();
    });

    expect(retried).toBe(false);
    expect(chat.fake.gateway.send).not.toHaveBeenCalled();
  });

  test('a message can be sent after a failure instead of retrying', async () => {
    const chat = await start();
    await act(async () => {
      chat.result.current.send('one');
    });
    await act(async () => {
      chat.fake.sends.shift()!.reject(new ApiError('http', 502, null));
    });

    let sent = false;
    await act(async () => {
      sent = chat.result.current.send('two');
    });

    expect(sent).toBe(true);
  });
});

describe('applying a workout', () => {
  test('sends the workout\'s own id and binding for approval, and is applied only when the backend says so', async () => {
    const chat = await start();
    await askAndGet(chat, PROPOSALS.edit);
    const id = cards(chat)[0].id;

    let pending: Promise<boolean> | undefined;
    await act(async () => {
      pending = chat.result.current.apply(id);
    });

    expect(chat.fake.gateway.approve).toHaveBeenCalledTimes(1);
    expect(chat.fake.gateway.approve).toHaveBeenCalledWith({ proposalId: PROPOSALS.edit.proposal_id, binding: PROPOSALS.edit.binding });
    // asked, not yet answered: it is applying, and not applied
    expect(cards(chat)[0].phase).toEqual({ kind: 'applying' });
    expect(chat.result.current.applying).toBe(true);

    await act(async () => {
      chat.fake.approvals[0].resolve(mockSavedPlan(PROPOSALS.edit, 100));
      await pending;
    });

    expect(cards(chat)[0].phase).toMatchObject({ kind: 'applied', planId: 100 });
    expect(chat.result.current.applying).toBe(false);
  });

  test('a second press while it is applying sends nothing: the workout is approved once', async () => {
    const chat = await start();
    await askAndGet(chat, PROPOSALS.edit);
    const id = cards(chat)[0].id;

    const results: boolean[] = [];
    await act(async () => {
      // two presses in the same instant, as a double tap is
      void chat.result.current.apply(id).then((sent) => results.push(sent));
      void chat.result.current.apply(id).then((sent) => results.push(sent));
    });

    expect(chat.fake.gateway.approve).toHaveBeenCalledTimes(1);
    expect(results).toEqual([false]);
  });

  test('a press after it was applied sends nothing', async () => {
    const chat = await start();
    await askAndGet(chat, PROPOSALS.edit);
    const id = cards(chat)[0].id;
    await act(async () => {
      const pending = chat.result.current.apply(id);
      chat.fake.approvals[0].resolve(mockSavedPlan(PROPOSALS.edit, 100));
      await pending;
    });

    let sent = true;
    await act(async () => {
      sent = await chat.result.current.apply(id);
    });

    expect(sent).toBe(false);
    expect(chat.fake.gateway.approve).toHaveBeenCalledTimes(1);
  });

  test('a failure that trying again can fix leaves the workout as it was, and it can be applied again', async () => {
    const chat = await start();
    await askAndGet(chat, PROPOSALS.edit);
    const [before] = cards(chat);

    await act(async () => {
      const pending = chat.result.current.apply(before.id);
      chat.fake.approvals[0].reject(new ApiError('network', null, null));
      await pending;
    });

    const [after] = cards(chat);
    expect(after.phase).toMatchObject({ kind: 'apply-failed', failure: { retryable: true } });
    // the workout is exactly what it was
    expect(after.proposal).toBe(before.proposal);
    expect(chat.result.current.applying).toBe(false);

    await act(async () => {
      const pending = chat.result.current.apply(before.id);
      chat.fake.approvals[1].resolve(mockSavedPlan(PROPOSALS.edit, 100));
      await pending;
    });

    expect(chat.fake.gateway.approve).toHaveBeenCalledTimes(2);
    expect(cards(chat)[0].phase).toMatchObject({ kind: 'applied', planId: 100 });
  });

  test('a refusal that trying again cannot fix is final: nothing more is sent, and the failure says why', async () => {
    const chat = await start();
    await askAndGet(chat, PROPOSALS.edit);
    const id = cards(chat)[0].id;
    await act(async () => {
      const pending = chat.result.current.apply(id);
      chat.fake.approvals[0].reject(new ApiError('http', 409, 'this proposal has expired: ask the coach for a new one'));
      await pending;
    });

    let sent = true;
    await act(async () => {
      sent = await chat.result.current.apply(id);
    });

    expect(sent).toBe(false);
    expect(chat.fake.gateway.approve).toHaveBeenCalledTimes(1);
    expect(cards(chat)[0].phase).toMatchObject({ kind: 'apply-failed', failure: { retryable: false, message: expect.stringMatching(/expired/) } });
  });

  test('an id that is not a workout on the page sends nothing', async () => {
    const chat = await start();

    let sent = true;
    await act(async () => {
      sent = await chat.result.current.apply('nope');
    });

    expect(sent).toBe(false);
    expect(chat.fake.gateway.approve).not.toHaveBeenCalled();
  });

  test('is refused while the coach is answering', async () => {
    const chat = await start();
    await askAndGet(chat, PROPOSALS.edit);
    const id = cards(chat)[0].id;
    await act(async () => {
      chat.result.current.send('one more thing');
    });

    let sent = true;
    await act(async () => {
      sent = await chat.result.current.apply(id);
    });

    expect(sent).toBe(false);
    expect(chat.fake.gateway.approve).not.toHaveBeenCalled();
  });

  test('a message cannot be sent while a workout is being applied', async () => {
    const chat = await start();
    await askAndGet(chat, PROPOSALS.edit);
    await act(async () => {
      void chat.result.current.apply(cards(chat)[0].id);
    });

    let sent = true;
    await act(async () => {
      sent = chat.result.current.send('wait, change it');
    });

    expect(sent).toBe(false);
    expect(chat.fake.gateway.send).toHaveBeenCalledTimes(1);
  });
});

describe('a change to a workout', () => {
  test('asks the coach again with the conversation so far, and the newer workout takes the older one\'s place', async () => {
    const chat = await start();
    await askAndGet(chat, PROPOSALS.edit, 'a different ab workout');

    await act(async () => {
      chat.result.current.send('Keep the same duration, but make it easier on my knees');
    });

    const { request } = chat.fake.sends[0];
    expect(request.message).toBe('Keep the same duration, but make it easier on my knees');
    expect(request.history.at(-1)).toEqual({ role: 'coach', text: 'Here is a workout.' });
    expect(request.history.map((turn) => turn.text)).toContain('a different ab workout');

    await answer(chat.fake, 'A gentler one', PROPOSALS.refined);

    const [older, newer] = cards(chat);
    expect(older.phase).toEqual({ kind: 'superseded', reason: 'newer-version' });
    expect(newer.phase).toEqual({ kind: 'ready' });
    // the newer one comes with the backend's comparison with the original saved workout, not with the first proposal
    expect(newer.proposal.changes?.compared_with_plan_id).toBe(41);
    expect(chat.fake.gateway.send).toHaveBeenCalledTimes(2);
  });

  test('one request makes one workout: a change asks the coach once, and nothing else is created', async () => {
    const chat = await start();
    await askAndGet(chat, PROPOSALS.edit);

    await act(async () => {
      chat.result.current.send('easier on my knees');
    });
    await answer(chat.fake, 'A gentler one', PROPOSALS.refined);

    expect(chat.fake.gateway.send).toHaveBeenCalledTimes(2);
    expect(chat.fake.gateway.approve).not.toHaveBeenCalled();
    expect(cards(chat)).toHaveLength(2);
  });

  test('the older workout can no longer be applied from the page', async () => {
    const chat = await start();
    await askAndGet(chat, PROPOSALS.edit);
    const olderId = cards(chat)[0].id;
    await act(async () => {
      chat.result.current.send('easier');
    });
    await answer(chat.fake, 'Gentler', PROPOSALS.refined);

    let sent = true;
    await act(async () => {
      sent = await chat.result.current.apply(olderId);
    });

    expect(sent).toBe(false);
    expect(chat.fake.gateway.approve).not.toHaveBeenCalled();
  });

  test('when the coach answers with words only, the workout waiting is still the one to apply', async () => {
    const chat = await start();
    await askAndGet(chat, PROPOSALS.edit);
    await act(async () => {
      chat.result.current.send('why that exercise?');
    });
    await answer(chat.fake, 'Because it works the core');

    expect(cards(chat)[0].phase).toEqual({ kind: 'ready' });
  });
});

describe('starting over', () => {
  test('goes back to the opening, tells the gateway, and drops an answer that was still on its way', async () => {
    const chat = await start();
    await act(async () => {
      chat.result.current.send('first');
    });

    let started = false;
    await act(async () => {
      started = chat.result.current.reset();
    });

    expect(started).toBe(true);
    expect(chat.fake.gateway.reset).toHaveBeenCalledTimes(1);
    expect(chat.result.current.items).toEqual(MOCK_OPENING.items);
    expect(chat.result.current.waiting).toBe(false);

    // the old answer arrives late
    await act(async () => {
      chat.fake.sends.shift()!.resolve({ reply: 'late', proposal: PROPOSALS.edit });
    });

    expect(chat.result.current.items).toEqual(MOCK_OPENING.items);
  });

  test('a request that fails after starting over is dropped too', async () => {
    const chat = await start();
    await act(async () => {
      chat.result.current.send('first');
    });
    await act(async () => {
      chat.result.current.reset();
    });

    await act(async () => {
      chat.fake.sends.shift()!.reject(new ApiError('network', null, null));
    });

    expect(chat.result.current.items).toEqual(MOCK_OPENING.items);
  });

  test('an old answer that arrives after a new question was asked does not answer it', async () => {
    const chat = await start();
    await act(async () => {
      chat.result.current.send('first');
    });
    await act(async () => {
      chat.result.current.reset();
    });
    await act(async () => {
      chat.result.current.send('second');
    });
    const [old, current] = chat.fake.sends;

    await act(async () => {
      old.resolve({ reply: 'the answer to the first question', proposal: PROPOSALS.edit });
    });

    // still waiting for the second one's own answer, and nothing of the first is shown
    expect(chat.result.current.waiting).toBe(true);
    expect(chat.result.current.items.some((item) => item.kind === 'message' && item.text === 'the answer to the first question')).toBe(false);
    expect(cards(chat)).toHaveLength(0);

    await act(async () => {
      current.resolve({ reply: 'the answer to the second', proposal: null });
    });
    expect(chat.result.current.items.at(-1)).toMatchObject({ kind: 'message', text: 'the answer to the second' });
  });

  test('a message can be sent again at once', async () => {
    const chat = await start();
    await act(async () => {
      chat.result.current.send('first');
    });
    await act(async () => {
      chat.result.current.reset();
    });

    let sent = false;
    await act(async () => {
      sent = chat.result.current.send('again');
    });

    expect(sent).toBe(true);
    expect(chat.fake.gateway.send).toHaveBeenCalledTimes(2);
  });

  test('is refused while a workout is being applied: the approval cannot be called back', async () => {
    const chat = await start();
    await askAndGet(chat, PROPOSALS.edit);
    await act(async () => {
      void chat.result.current.apply(cards(chat)[0].id);
    });

    let started = true;
    await act(async () => {
      started = chat.result.current.reset();
    });

    expect(started).toBe(false);
    expect(chat.fake.gateway.reset).not.toHaveBeenCalled();
    expect(cards(chat)[0].phase).toEqual({ kind: 'applying' });

    // and it works once the backend has answered
    await act(async () => {
      chat.fake.approvals[0].resolve(mockSavedPlan(PROPOSALS.edit, 100));
    });
    await act(async () => {
      started = chat.result.current.reset();
    });
    expect(started).toBe(true);
  });
});

describe('going away', () => {
  test('an answer that arrives after the screen has closed is dropped without a trace', async () => {
    const chat = await start();
    await act(async () => {
      chat.result.current.send('first');
    });
    const itemsBefore = chat.result.current.items;

    await chat.unmount();
    await act(async () => {
      chat.fake.sends.shift()!.resolve({ reply: 'late', proposal: PROPOSALS.edit });
    });

    expect(chat.result.current.items).toBe(itemsBefore);
  });
});

describe('the saved workout the conversation is about', () => {
  const LAUNCH = { workoutId: 41, title: 'Core & Abs Focus' };

  test('every message names it: the first, a try again after a failure, and a change to what came back', async () => {
    const chat = await start({ launch: LAUNCH });

    await act(async () => {
      chat.result.current.send('make it shorter', { expectsWorkout: true });
    });
    expect(chat.fake.sends[0].request).toEqual({ message: 'make it shorter', history: [], workoutPlanId: 41 });

    await act(async () => {
      chat.fake.sends.shift()!.reject(new ApiError('network', null, null));
    });
    await act(async () => {
      chat.result.current.retry();
    });
    expect(chat.fake.sends[0].request).toEqual({ message: 'make it shorter', history: [], workoutPlanId: 41 });
    await answer(chat.fake, 'Here it is', PROPOSALS.edit);

    await act(async () => {
      chat.result.current.send('and easier on my knees');
    });
    expect(chat.fake.sends[0].request.workoutPlanId).toBe(41);
    expect(chat.fake.sends[0].request.history.map((turn) => turn.text)).toEqual(['make it shorter', 'Here it is']);
  });

  test('the question that names the workout is on the screen and is not something said to the coach', async () => {
    const chat = await start({ launch: LAUNCH });

    expect(chat.result.current.items[0]).toMatchObject({ kind: 'message', role: 'assistant', text: 'What would you like to change in “Core & Abs Focus”?' });
    await act(async () => {
      chat.result.current.send('shorter');
    });

    expect(chat.fake.sends[0].request.history).toEqual([]);
  });

  test('a conversation about no workout names none, and neither does one opened from an example workout with no saved id', async () => {
    for (const launch of [null, { workoutId: 'mock-workout-today', title: 'Core & Abs Focus' }]) {
      const chat = await start({ launch });

      await act(async () => {
        chat.result.current.send('shorter');
      });

      expect(chat.fake.sends[0].request).not.toHaveProperty('workoutPlanId');
    }
  });

  test('applying a revision of it moves the conversation to the plan that replaced it: the next change is to that', async () => {
    const chat = await start({ launch: LAUNCH });
    await askAndGet(chat, PROPOSALS.edit);
    expect(chat.result.current.target).toEqual({ planId: 41, title: 'Core & Abs Focus' });

    await act(async () => {
      const pending = chat.result.current.apply(cards(chat)[0].id);
      chat.fake.approvals[0].resolve(mockSavedPlan(PROPOSALS.edit, 100));
      await pending;
    });
    expect(chat.result.current.target).toEqual({ planId: 100, title: 'Core Stability & Abs' });
    // it was opened from the workout, and still says so
    expect(chat.result.current.launch).toEqual(LAUNCH);

    await act(async () => {
      chat.result.current.send('now a bit longer');
    });

    expect(chat.fake.sends[0].request.workoutPlanId).toBe(100);
  });

  test('is not moved by a failed apply, which saved and cancelled nothing', async () => {
    const chat = await start({ launch: LAUNCH });
    await askAndGet(chat, PROPOSALS.edit);
    await act(async () => {
      const pending = chat.result.current.apply(cards(chat)[0].id);
      chat.fake.approvals[0].reject(new ApiError('network', null, null));
      await pending;
    });

    await act(async () => {
      chat.result.current.send('shorter');
    });

    expect(chat.fake.sends[0].request.workoutPlanId).toBe(41);
  });

  test('a try again goes to the workout the conversation is about now, not the one it was about when it failed', async () => {
    const chat = await start({ launch: LAUNCH });
    await askAndGet(chat, PROPOSALS.edit);
    await act(async () => {
      chat.result.current.send('shorter');
    });
    await act(async () => {
      chat.fake.sends.shift()!.reject(new ApiError('network', null, null));
    });
    await act(async () => {
      const pending = chat.result.current.apply(cards(chat)[0].id);
      chat.fake.approvals[0].resolve(mockSavedPlan(PROPOSALS.edit, 100));
      await pending;
    });

    await act(async () => {
      chat.result.current.retry();
    });

    expect(chat.fake.sends[0].request).toMatchObject({ message: 'shorter', workoutPlanId: 100 });
  });

  test.each([404, 409])('a %s to a message about it says it can no longer be edited, and asking again is not offered', async (status) => {
    const chat = await start({ launch: LAUNCH });
    await act(async () => {
      chat.result.current.send('shorter');
    });

    await act(async () => {
      chat.fake.sends.shift()!.reject(new ApiError('http', status, 'whatever the backend says'));
    });

    expect(chat.result.current.items.at(-1)).toMatchObject({ kind: 'failed', message: TARGET_UNAVAILABLE, retryable: false });
    let retried = true;
    await act(async () => {
      retried = chat.result.current.retry();
    });
    expect(retried).toBe(false);
    expect(chat.fake.gateway.send).toHaveBeenCalledTimes(1);
  });

  test('a 404 to a message about no workout is still the account, not a workout', async () => {
    const chat = await start();
    await act(async () => {
      chat.result.current.send('shorter');
    });

    await act(async () => {
      chat.fake.sends.shift()!.reject(new ApiError('http', 404, 'user 7 does not exist'));
    });

    expect(chat.result.current.items.at(-1)).toMatchObject({ kind: 'failed', message: "Formiq can't find your account. Log in again.", retryable: false });
  });

  test('a different workout starts a conversation about that one; the plan an applied revision made counts as the same', async () => {
    const fake = fakeGateway();
    const view = await renderHook(
      (props: { launch: { workoutId: number; title: string } | null }) => useCoachChat(fake.gateway, coachOpening, props.launch, { active: true }),
      { initialProps: { launch: LAUNCH as { workoutId: number; title: string } | null } },
    );
    await act(async () => {
      view.result.current.send('a different ab workout');
    });
    await act(async () => {
      fake.sends.shift()!.resolve({ reply: 'Here', proposal: PROPOSALS.edit });
    });
    await act(async () => {
      const pending = view.result.current.apply(view.result.current.items.find((item) => item.kind === 'proposal')!.id);
      fake.approvals[0].resolve(mockSavedPlan(PROPOSALS.edit, 100));
      await pending;
    });
    const before = view.result.current.items;

    // opened again from the plan that replaced it: the same workout, so the conversation carries on
    await view.rerender({ launch: { workoutId: 100, title: 'Core Stability & Abs' } });
    expect(view.result.current.items).toBe(before);

    // opened from another workout: a new conversation about that one
    await view.rerender({ launch: { workoutId: 7, title: 'Leg Day' } });
    expect(view.result.current.target).toEqual({ planId: 7, title: 'Leg Day' });
    expect(view.result.current.items).not.toBe(before);
  });
});

describe('dismissing a workout', () => {
  test('sends the workout\'s own id and binding, and it is dismissed only when the backend says so', async () => {
    const chat = await start();
    await askAndGet(chat, PROPOSALS.edit);
    const id = cards(chat)[0].id;

    let pending: Promise<boolean> | undefined;
    await act(async () => {
      pending = chat.result.current.reject(id);
    });

    expect(chat.fake.gateway.reject).toHaveBeenCalledTimes(1);
    expect(chat.fake.gateway.reject).toHaveBeenCalledWith({ proposalId: PROPOSALS.edit.proposal_id, binding: PROPOSALS.edit.binding });
    // asked, not yet answered: it is being dismissed, and not dismissed
    expect(cards(chat)[0].phase).toEqual({ kind: 'rejecting' });
    expect(chat.result.current.rejecting).toBe(true);

    await act(async () => {
      chat.fake.rejections[0].resolve();
      await pending;
    });

    expect(cards(chat)[0].phase).toEqual({ kind: 'rejected' });
    expect(chat.result.current.rejecting).toBe(false);
    // nothing was applied, and nothing else was asked
    expect(chat.fake.gateway.approve).not.toHaveBeenCalled();
    expect(chat.fake.gateway.send).toHaveBeenCalledTimes(1);
  });

  test('a second press while it is being dismissed sends nothing: the workout is rejected once', async () => {
    const chat = await start();
    await askAndGet(chat, PROPOSALS.edit);
    const id = cards(chat)[0].id;

    const results: boolean[] = [];
    await act(async () => {
      void chat.result.current.reject(id).then((sent) => results.push(sent));
      void chat.result.current.reject(id).then((sent) => results.push(sent));
    });

    expect(chat.fake.gateway.reject).toHaveBeenCalledTimes(1);
    expect(results).toEqual([false]);
  });

  test('a press after it was dismissed sends nothing, and it can no longer be applied', async () => {
    const chat = await start();
    await askAndGet(chat, PROPOSALS.edit);
    const id = cards(chat)[0].id;
    await act(async () => {
      const pending = chat.result.current.reject(id);
      chat.fake.rejections[0].resolve();
      await pending;
    });

    const sent: boolean[] = [];
    await act(async () => {
      sent.push(await chat.result.current.reject(id));
      sent.push(await chat.result.current.apply(id));
    });

    expect(sent).toEqual([false, false]);
    expect(chat.fake.gateway.reject).toHaveBeenCalledTimes(1);
    expect(chat.fake.gateway.approve).not.toHaveBeenCalled();
  });

  test('a failure that trying again can fix leaves the workout as it was, still waiting: it can be dismissed again, or applied', async () => {
    const chat = await start();
    await askAndGet(chat, PROPOSALS.edit);
    const [before] = cards(chat);

    await act(async () => {
      const pending = chat.result.current.reject(before.id);
      chat.fake.rejections[0].reject(new ApiError('network', null, null));
      await pending;
    });

    const [after] = cards(chat);
    expect(after.phase).toMatchObject({ kind: 'reject-failed', failure: { retryable: true, message: "Can't reach Formiq. Check your connection and try again." } });
    expect(after.proposal).toBe(before.proposal);
    expect(chat.result.current.rejecting).toBe(false);

    await act(async () => {
      const pending = chat.result.current.reject(before.id);
      chat.fake.rejections[1].resolve();
      await pending;
    });

    expect(chat.fake.gateway.reject).toHaveBeenCalledTimes(2);
    expect(cards(chat)[0].phase).toEqual({ kind: 'rejected' });
  });

  test('after a failed dismissal the workout can still be applied', async () => {
    const chat = await start();
    await askAndGet(chat, PROPOSALS.edit);
    const id = cards(chat)[0].id;
    await act(async () => {
      const pending = chat.result.current.reject(id);
      chat.fake.rejections[0].reject(new ApiError('http', 503, null));
      await pending;
    });

    await act(async () => {
      const pending = chat.result.current.apply(id);
      chat.fake.approvals[0].resolve(mockSavedPlan(PROPOSALS.edit, 100));
      await pending;
    });

    expect(cards(chat)[0].phase).toMatchObject({ kind: 'applied', planId: 100 });
  });

  describe('a dismissal the backend refuses because the workout is already applied (the answer to its approval was lost)', () => {
    const ALREADY = () => new ApiError('http', 409, 'this proposal was already approved: it cannot be rejected');

    // the card is on screen, its dismissal has been refused, and the approval is being asked again
    async function refused(onApplied?: (plan: WorkoutPlan) => void) {
      const chat = await start({ onApplied });
      await askAndGet(chat, PROPOSALS.edit);
      const card = cards(chat)[0];
      await act(async () => {
        void chat.result.current.reject(card.id);
      });
      await act(async () => {
        chat.fake.rejections[0].reject(ALREADY());
      });
      return { chat, card };
    }

    test('asks the approval again, with the same id and binding, before saying anything of the dismissal', async () => {
      const { chat, card } = await refused();

      expect(chat.fake.gateway.approve).toHaveBeenCalledTimes(1);
      expect(chat.fake.approvals[0]).toMatchObject({ proposalId: card.proposal.proposal_id, binding: card.proposal.binding });
      // neither dismissed nor failed yet: nothing is known until the backend answers
      expect(cards(chat)[0].phase).toEqual({ kind: 'rejecting' });
      expect(chat.result.current.rejecting).toBe(true);
    });

    test('and shows what the backend answers: the plan the approval saved, as applied, and never as dismissed', async () => {
      const onApplied = jest.fn();
      const { chat, card } = await refused(onApplied);
      const plan = mockSavedPlan(card.proposal, 100);

      await act(async () => {
        chat.fake.approvals[0].resolve(plan);
      });

      expect(cards(chat)[0].phase).toEqual({ kind: 'applied', planId: 100, name: plan.name, scheduledDate: plan.scheduled_date });
      // whatever else shows the user's plans is told, as after any approval
      expect(onApplied).toHaveBeenCalledTimes(1);
      expect(onApplied).toHaveBeenCalledWith(plan);
      expect(chat.result.current.rejecting).toBe(false);
      // it was asked to dismiss once, and it is not offered again
      expect(chat.fake.gateway.reject).toHaveBeenCalledTimes(1);
      await act(async () => {
        expect(await chat.result.current.reject(card.id)).toBe(false);
        expect(await chat.result.current.apply(card.id)).toBe(false);
      });
      expect(chat.fake.gateway.reject).toHaveBeenCalledTimes(1);
      expect(chat.fake.gateway.approve).toHaveBeenCalledTimes(1);
    });

    test('and a screen that closed by then still tells the rest of the app that the workout was saved', async () => {
      const onApplied = jest.fn();
      const { chat, card } = await refused(onApplied);
      await act(async () => {
        chat.unmount();
      });

      await act(async () => {
        chat.fake.approvals[0].resolve(mockSavedPlan(card.proposal, 100));
      });

      expect(onApplied).toHaveBeenCalledTimes(1);
    });

    test('a 409 to that approval (the saved plan was changed since) is said as already applied, and is final', async () => {
      const onApplied = jest.fn();
      const { chat } = await refused(onApplied);

      await act(async () => {
        chat.fake.approvals[0].reject(
          new ApiError('http', 409, 'this proposal was already approved, but the workout plan it saved was changed, cancelled or removed since'),
        );
      });

      expect(cards(chat)[0].phase).toMatchObject({
        kind: 'reject-failed',
        failure: { retryable: false, message: 'This workout was already applied. Check your plans.' },
      });
      expect(onApplied).not.toHaveBeenCalled();
      expect(chat.result.current.rejecting).toBe(false);
    });

    test('a lost connection on that approval can be tried again, and Try Again only asks the approval', async () => {
      const onApplied = jest.fn();
      const { chat, card } = await refused(onApplied);
      await act(async () => {
        chat.fake.approvals[0].reject(new ApiError('network', null, null));
      });

      expect(cards(chat)[0].phase).toMatchObject({ kind: 'reject-failed', failure: { retryable: true } });
      expect(onApplied).not.toHaveBeenCalled();

      await act(async () => {
        void chat.result.current.apply(card.id);
      });
      await act(async () => {
        chat.fake.approvals[1].resolve(mockSavedPlan(card.proposal, 101));
      });

      expect(cards(chat)[0].phase).toMatchObject({ kind: 'applied', planId: 101 });
      expect(onApplied).toHaveBeenCalledTimes(1);
      expect(chat.fake.gateway.reject).toHaveBeenCalledTimes(1);
    });

    test('Dismiss Again after that lost approval reconciles again instead of reporting a failure', async () => {
      const { chat, card } = await refused();
      await act(async () => {
        chat.fake.approvals[0].reject(new ApiError('timeout', null, null));
      });

      await act(async () => {
        void chat.result.current.reject(card.id);
      });
      await act(async () => {
        chat.fake.rejections[1].reject(ALREADY());
      });
      await act(async () => {
        chat.fake.approvals[1].resolve(mockSavedPlan(card.proposal, 100));
      });

      expect(cards(chat)[0].phase).toMatchObject({ kind: 'applied', planId: 100 });
    });

    test('is the same for a card recovered from the backend, and what was applied is not offered again after starting over', async () => {
      const chat = await start();
      chat.fake.waiting.list = [mockPendingProposal('edit', NOW, 7, 5)];
      await act(async () => {
        chat.result.current.reset();
      });
      const card = cards(chat)[0];
      await act(async () => {
        void chat.result.current.reject(card.id);
      });
      await act(async () => {
        chat.fake.rejections[0].reject(ALREADY());
      });
      await act(async () => {
        chat.fake.approvals[0].resolve(mockSavedPlan(card.proposal, 100));
      });

      expect(cards(chat)[0].phase).toMatchObject({ kind: 'applied' });
      await act(async () => {
        chat.result.current.reset();
      });
      // the backend still lists it (a stale list), but this app applied it
      expect(cards(chat)).toHaveLength(0);
    });
  });

  test('a 404 is the backend saying it is not waiting any more: the card ends as expired, not as dismissed', async () => {
    const chat = await start();
    await askAndGet(chat, PROPOSALS.edit);
    await act(async () => {
      const pending = chat.result.current.reject(cards(chat)[0].id);
      chat.fake.rejections[0].reject(new ApiError('http', 404, 'there is no workout plan proposal'));
      await pending;
    });

    expect(cards(chat)[0].phase).toEqual({ kind: 'expired' });
  });

  test('an id that is not a workout on the page sends nothing', async () => {
    const chat = await start();

    let sent = true;
    await act(async () => {
      sent = await chat.result.current.reject('nope');
    });

    expect(sent).toBe(false);
    expect(chat.fake.gateway.reject).not.toHaveBeenCalled();
  });

  test('is refused while the coach is answering, and while another workout is being applied', async () => {
    const chat = await start();
    await askAndGet(chat, PROPOSALS.edit);
    const id = cards(chat)[0].id;
    await act(async () => {
      chat.result.current.send('one more thing');
    });
    let sent = true;
    await act(async () => {
      sent = await chat.result.current.reject(id);
    });
    expect(sent).toBe(false);
    await answer(chat.fake, 'ok');

    await act(async () => {
      void chat.result.current.apply(id);
    });
    await act(async () => {
      sent = await chat.result.current.reject(id);
    });

    expect(sent).toBe(false);
    expect(chat.fake.gateway.reject).not.toHaveBeenCalled();
  });

  test('while it is being dismissed nothing else can be started: not a message, not an apply, not starting over', async () => {
    const chat = await start();
    await askAndGet(chat, PROPOSALS.edit);
    const id = cards(chat)[0].id;
    await act(async () => {
      void chat.result.current.reject(id);
    });

    const outcomes: boolean[] = [];
    await act(async () => {
      outcomes.push(chat.result.current.send('wait, change it'));
      outcomes.push(await chat.result.current.apply(id));
      outcomes.push(chat.result.current.reset());
    });

    expect(outcomes).toEqual([false, false, false]);
    expect(chat.fake.gateway.send).toHaveBeenCalledTimes(1);
    expect(chat.fake.gateway.approve).not.toHaveBeenCalled();
    expect(chat.fake.gateway.reset).not.toHaveBeenCalled();
    expect(cards(chat)[0].phase).toEqual({ kind: 'rejecting' });

    // and starting over works once the backend has answered
    await act(async () => {
      chat.fake.rejections[0].resolve();
    });
    let started = false;
    await act(async () => {
      started = chat.result.current.reset();
    });
    expect(started).toBe(true);
  });
});

describe('workouts waiting from before the conversation', () => {
  const waiting = (sequence: number, minutesAgo = 12, scenario: 'new' | 'edit' = 'edit') => mockPendingProposal(scenario, NOW, sequence, minutesAgo);
  const recoverNow = (chat: Chat) =>
    act(async () => {
      await chat.result.current.recover();
    });

  test('is asked once when the screen is first shown, and none leaves the conversation as it opened', async () => {
    const chat = await start();

    expect(chat.fake.gateway.pending).toHaveBeenCalledTimes(1);
    expect(chat.result.current.items).toEqual(MOCK_OPENING.items);
    expect(chat.result.current.recoveryFailure).toBeNull();
  });

  test('one is shown as its card, ready, with a line saying it was proposed earlier: nothing is applied, dismissed or asked', async () => {
    const fake = fakeGateway();
    fake.waiting.list = [waiting(1)];
    const chat = await renderHook(() => useCoachChat(fake.gateway, () => MOCK_OPENING, null, { active: true }));
    await act(async () => {});

    const items = chat.result.current.items;
    expect(items.slice(-2).map((item) => item.kind)).toEqual(['message', 'proposal']);
    expect(items.at(-1)).toMatchObject({ phase: { kind: 'ready' }, recovered: { createdAt: waiting(1).created_at } });
    expect(fake.gateway.approve).not.toHaveBeenCalled();
    expect(fake.gateway.reject).not.toHaveBeenCalled();
    expect(fake.gateway.send).not.toHaveBeenCalled();
  });

  test('several are listed to choose from: none is shown as a card, and choosing one shows its card only', async () => {
    const fake = fakeGateway();
    fake.waiting.list = [waiting(2, 5, 'new'), waiting(1, 12)];
    const chat = await renderHook(() => useCoachChat(fake.gateway, () => MOCK_OPENING, null, { active: true }));
    await act(async () => {});

    expect(chat.result.current.items.filter((item) => item.kind === 'proposal')).toHaveLength(0);
    const listed = chat.result.current.items.find((item) => item.kind === 'choice');
    expect(listed).toMatchObject({ kind: 'choice', entries: [{ proposal_id: waiting(2).proposal_id }, { proposal_id: waiting(1).proposal_id }] });

    await act(async () => {
      chat.result.current.review(waiting(1).proposal_id);
    });

    const shown = chat.result.current.items.filter((item): item is Extract<ChatItem, { kind: 'proposal' }> => item.kind === 'proposal');
    expect(shown.map((card) => card.proposal.proposal_id)).toEqual([waiting(1).proposal_id]);
    expect(shown[0].phase).toEqual({ kind: 'ready' });
    expect(fake.gateway.approve).not.toHaveBeenCalled();
    expect(fake.gateway.reject).not.toHaveBeenCalled();
  });

  test('is not asked while the screen is hidden, and is asked each time it is shown again, and not when it stays shown', async () => {
    const chat = await start({ active: false });
    expect(chat.fake.gateway.pending).not.toHaveBeenCalled();

    await chat.rerender({ active: true });
    expect(chat.fake.gateway.pending).toHaveBeenCalledTimes(1);
    await chat.rerender({ active: true });
    expect(chat.fake.gateway.pending).toHaveBeenCalledTimes(1);

    await chat.rerender({ active: false });
    expect(chat.fake.gateway.pending).toHaveBeenCalledTimes(1);
    await chat.rerender({ active: true });
    expect(chat.fake.gateway.pending).toHaveBeenCalledTimes(2);
  });

  test('coming back asks again, and shows what is waiting now that was not before', async () => {
    const chat = await start();
    chat.fake.waiting.list = [waiting(1)];

    await chat.rerender({ active: false });
    await chat.rerender({ active: true });

    expect(chat.result.current.items.at(-1)).toMatchObject({ kind: 'proposal', recovered: { createdAt: waiting(1).created_at } });
  });

  test('a proposal that already has a card is never added again, however often it is asked', async () => {
    const chat = await start();
    chat.fake.waiting.list = [waiting(1)];
    await recoverNow(chat);
    await recoverNow(chat);
    await chat.rerender({ active: false });
    await chat.rerender({ active: true });

    expect(cards(chat)).toHaveLength(1);
    expect(chat.result.current.items.filter((item) => item.kind === 'message' && item.inHistory === false && /waiting for your approval/.test(item.text))).toHaveLength(1);
  });

  test('a proposal the coach made in this conversation is not added again when the backend lists it', async () => {
    const chat = await start();
    await askAndGet(chat, PROPOSALS.edit);
    chat.fake.waiting.list = [{ ...PROPOSALS.edit, created_at: NOW.toISOString() }];

    await recoverNow(chat);

    expect(cards(chat)).toHaveLength(1);
    expect(cards(chat)[0].recovered).toBeNull();
  });

  test('at most one request at a time: asking while one is on its way asks nothing more', async () => {
    const chat = await start();
    chat.fake.waiting.hold = true;
    const answers: boolean[] = [];

    await act(async () => {
      void chat.result.current.recover().then((asked) => answers.push(asked));
      void chat.result.current.recover().then((asked) => answers.push(asked));
    });

    expect(chat.fake.gateway.pending).toHaveBeenCalledTimes(2); // the one on mount, and the one that was held
    expect(answers).toEqual([false]);
    expect(chat.fake.lists).toHaveLength(1);

    // once it has answered, it can ask again
    await act(async () => {
      chat.fake.lists.shift()!.resolve([]);
    });
    chat.fake.waiting.hold = false;
    await recoverNow(chat);
    expect(chat.fake.gateway.pending).toHaveBeenCalledTimes(3);
  });

  test('is not asked while a message, an apply or a dismissal is under way', async () => {
    const chat = await start();
    const asked: boolean[] = [];

    await act(async () => {
      chat.result.current.send('hello');
    });
    await act(async () => {
      asked.push(await chat.result.current.recover());
    });
    await answer(chat.fake, 'Here is one', PROPOSALS.edit);
    const id = cards(chat)[0].id;
    await act(async () => {
      void chat.result.current.apply(id);
    });
    await act(async () => {
      asked.push(await chat.result.current.recover());
    });
    await act(async () => {
      chat.fake.approvals[0].reject(new ApiError('network', null, null));
    });
    await act(async () => {
      void chat.result.current.reject(id);
    });
    await act(async () => {
      asked.push(await chat.result.current.recover());
    });

    expect(asked).toEqual([false, false, false]);
    // only the one on mount
    expect(chat.fake.gateway.pending).toHaveBeenCalledTimes(1);
  });

  test('an answer that arrives after the conversation started over is dropped, and starting over asks again', async () => {
    const chat = await start();
    chat.fake.waiting.hold = true;
    await act(async () => {
      void chat.result.current.recover();
    });
    expect(chat.fake.lists).toHaveLength(1);

    await act(async () => {
      chat.result.current.reset();
    });
    // asked again for the conversation that began, while the old answer is still out
    expect(chat.fake.lists).toHaveLength(2);

    await act(async () => {
      chat.fake.lists[0].resolve([waiting(1)]);
    });
    expect(chat.result.current.items).toEqual(MOCK_OPENING.items);

    await act(async () => {
      chat.fake.lists[1].resolve([waiting(2, 5, 'new')]);
    });
    expect(cards(chat).map((card) => card.proposal.proposal_id)).toEqual([waiting(2).proposal_id]);
  });

  test('a conversation that began over finds what is waiting, which starting over does not change on the backend', async () => {
    const chat = await start();
    await askAndGet(chat, PROPOSALS.edit);
    chat.fake.waiting.list = [{ ...PROPOSALS.edit, created_at: NOW.toISOString() }];

    await act(async () => {
      chat.result.current.reset();
    });

    expect(chat.result.current.items.at(-1)).toMatchObject({ kind: 'proposal', phase: { kind: 'ready' }, recovered: { createdAt: NOW.toISOString() } });
  });

  test('is not asked after starting over is refused (a workout is being applied)', async () => {
    const chat = await start();
    await askAndGet(chat, PROPOSALS.edit);
    await act(async () => {
      void chat.result.current.apply(cards(chat)[0].id);
    });
    const asks = chat.fake.gateway.pending.mock.calls.length;

    await act(async () => {
      chat.result.current.reset();
    });

    expect(chat.fake.gateway.pending).toHaveBeenCalledTimes(asks);
  });

  test('an answer that arrives after the screen has closed is dropped without a trace', async () => {
    const chat = await start();
    chat.fake.waiting.hold = true;
    await act(async () => {
      void chat.result.current.recover();
    });
    const itemsBefore = chat.result.current.items;

    await chat.unmount();
    await act(async () => {
      chat.fake.lists.shift()!.resolve([waiting(1)]);
    });

    expect(chat.result.current.items).toBe(itemsBefore);
  });

  describe('when it cannot be asked', () => {
    test('says so, shows no workout and never says there is none; asking again once it works shows what is waiting and clears it', async () => {
      const fake = fakeGateway();
      fake.waiting.list = new ApiError('network', null, null);
      const chat = await renderHook(() => useCoachChat(fake.gateway, () => MOCK_OPENING, null, { active: true }));
      await act(async () => {});

      expect(chat.result.current.recoveryFailure).toEqual({
        message: "Can't reach Formiq. Couldn't check for workouts waiting for your approval.",
        retryable: true,
      });
      expect(chat.result.current.items).toEqual(MOCK_OPENING.items);

      fake.waiting.list = [waiting(1)];
      await act(async () => {
        await chat.result.current.recover();
      });

      expect(chat.result.current.recoveryFailure).toBeNull();
      expect(chat.result.current.items.at(-1)).toMatchObject({ kind: 'proposal' });
    });

    test('an expired session cannot be helped by asking again', async () => {
      const fake = fakeGateway();
      fake.waiting.list = new ApiError('http', 401, 'could not validate credentials');
      const chat = await renderHook(() => useCoachChat(fake.gateway, () => MOCK_OPENING, null, { active: true }));
      await act(async () => {});

      expect(chat.result.current.recoveryFailure).toEqual({ message: 'Your session has expired. Log in again.', retryable: false });
    });

    test('an answer that cannot be read is a failure to look, never "none"', async () => {
      const fake = fakeGateway();
      fake.waiting.list = new ApiError('invalid-response', null, null);
      const chat = await renderHook(() => useCoachChat(fake.gateway, () => MOCK_OPENING, null, { active: true }));
      await act(async () => {});

      expect(chat.result.current.recoveryFailure?.retryable).toBe(true);
      expect(chat.result.current.items).toEqual(MOCK_OPENING.items);
    });
  });

  describe('what this screen applied or dismissed', () => {
    test('an applied workout is not offered again to a conversation that started over, whatever the list still says', async () => {
      const chat = await start();
      chat.fake.waiting.list = [waiting(1)];
      await recoverNow(chat);
      await act(async () => {
        const pending = chat.result.current.apply(cards(chat)[0].id);
        chat.fake.approvals[0].resolve(mockSavedPlan(waiting(1), 100));
        await pending;
      });

      await act(async () => {
        chat.result.current.reset();
      });

      expect(chat.result.current.items).toEqual(MOCK_OPENING.items);
    });

    test('nor a dismissed one', async () => {
      const chat = await start();
      chat.fake.waiting.list = [waiting(1)];
      await recoverNow(chat);
      await act(async () => {
        const pending = chat.result.current.reject(cards(chat)[0].id);
        chat.fake.rejections[0].resolve();
        await pending;
      });

      await act(async () => {
        chat.result.current.reset();
      });

      expect(chat.result.current.items).toEqual(MOCK_OPENING.items);
    });

    test('a dismissal that failed is not settled: a conversation that started over is offered it again', async () => {
      const chat = await start();
      chat.fake.waiting.list = [waiting(1)];
      await recoverNow(chat);
      await act(async () => {
        const pending = chat.result.current.reject(cards(chat)[0].id);
        chat.fake.rejections[0].reject(new ApiError('network', null, null));
        await pending;
      });

      await act(async () => {
        chat.result.current.reset();
      });

      expect(cards(chat).map((card) => card.proposal.proposal_id)).toEqual([waiting(1).proposal_id]);
    });

    test('a recovered workout is applied with its own id and binding, and only the backend makes it applied', async () => {
      const chat = await start();
      chat.fake.waiting.list = [waiting(1)];
      await recoverNow(chat);
      const [card] = cards(chat);

      await act(async () => {
        void chat.result.current.apply(card.id);
      });

      expect(chat.fake.gateway.approve).toHaveBeenCalledWith({ proposalId: waiting(1).proposal_id, binding: waiting(1).binding });
      expect(cards(chat)[0].phase).toEqual({ kind: 'applying' });
      await act(async () => {
        chat.fake.approvals[0].resolve(mockSavedPlan(waiting(1), 100));
      });
      expect(cards(chat)[0].phase).toMatchObject({ kind: 'applied', planId: 100 });
    });
  });
});


// Phase 2.3: after a restart or a new sign-in the conversation is new and the backend's list of waiting workouts is all
// there is to go on. What the conversation is about comes only from the card the person asks to change.
describe('a conversation after a restart or a new sign-in', () => {
  const waitingFor = (sequence: number, planId: number, name: string, minutesAgo = 5) => {
    const base = mockPendingProposal('edit', NOW, sequence, minutesAgo);
    return { ...base, revision: { ...base.revision!, replaces_plan_id: planId, replaces_plan_name: name } };
  };
  // the screen opens, and the backend lists what was waiting before the app was closed
  async function restarted(list = [waitingFor(1, 41, 'Core')], launch: { workoutId: number; title: string } | null = null) {
    const chat = await start({ launch, waiting: list });
    // what the backend listed has arrived: a card, or the list to choose from
    await waitFor(() => expect(chat.result.current.items.some((item) => item.kind === 'proposal' || item.kind === 'choice')).toBe(true));
    return chat;
  }
  const plansSent = (chat: Chat) => chat.fake.gateway.send.mock.calls.map(([request]) => request.workoutPlanId);

  test('is about no workout until a change is asked of a card: a card being there names no plan', async () => {
    const chat = await restarted();

    expect(chat.result.current.target).toBeNull();
    await act(async () => {
      chat.result.current.send('hello');
    });

    expect(plansSent(chat)).toEqual([undefined]);
    expect(chat.fake.sends[0].request).not.toHaveProperty('workoutPlanId');
  });

  test('a suggested change to the waiting card is a message about its plan, and the next one carries the same plan', async () => {
    const chat = await restarted();
    const card = cards(chat)[0];
    expect(chat.result.current.refined).toBe(card.id);

    await act(async () => {
      chat.result.current.send('Keep same duration', { expectsWorkout: true, about: chat.result.current.refined ?? undefined });
    });
    await answer(chat.fake, 'ok');
    expect(chat.result.current.target).toEqual({ planId: 41, title: 'Core' });
    await act(async () => {
      chat.result.current.send('and shorter');
    });

    expect(plansSent(chat)).toEqual([41, 41]);
  });

  test('"Ask for More Changes" on the card makes what is typed next a message about its plan', async () => {
    const chat = await restarted();

    await act(async () => {
      chat.result.current.refine(cards(chat)[0].id);
    });
    expect(chat.result.current.target).toEqual({ planId: 41, title: 'Core' });
    await act(async () => {
      chat.result.current.send('make it harder');
    });

    expect(plansSent(chat)).toEqual([41]);
  });

  test('the request asked again after a failure keeps the plan that message was about', async () => {
    const chat = await restarted();
    await act(async () => {
      chat.result.current.send('Keep same duration', { about: chat.result.current.refined ?? undefined });
    });
    await act(async () => {
      chat.fake.sends.shift()!.reject(new ApiError('network', null, null));
    });

    await act(async () => {
      chat.result.current.retry();
    });

    expect(plansSent(chat)).toEqual([41, 41]);
    expect(chat.fake.gateway.send.mock.calls[1][0].message).toBe('Keep same duration');
  });

  test('of several, only the card chosen and asked about binds its plan; not the newest in the list', async () => {
    const chat = await restarted([waitingFor(2, 77, 'Legs', 2), waitingFor(1, 41, 'Core', 9)]);
    expect(cards(chat)).toHaveLength(0);

    await act(async () => {
      chat.result.current.review(waitingFor(1, 41, 'Core', 9).proposal_id);
    });
    await act(async () => {
      chat.result.current.refine(cards(chat)[0].id);
    });
    await act(async () => {
      chat.result.current.send('make it easier');
    });

    expect(plansSent(chat)).toEqual([41]);
  });

  test('a card for another plan than the one being edited is no one to change: no refinement, and the plan stays', async () => {
    const chat = await restarted([waitingFor(1, 77, 'Legs')], { workoutId: 41, title: 'Core' });

    expect(chat.result.current.target).toEqual({ planId: 41, title: 'Core' });
    expect(chat.result.current.refined).toBeNull();
    expect(chat.result.current.suggestions).toEqual([]);
    await act(async () => {
      chat.result.current.refine(cards(chat)[0].id);
    });
    await act(async () => {
      chat.result.current.send('make it shorter');
    });

    expect(plansSent(chat)).toEqual([41]);
    expect(chat.result.current.target).toEqual({ planId: 41, title: 'Core' });
  });

  test('nothing is remembered by the app: a new conversation starts about no workout again, and can be bound again', async () => {
    const first = await restarted();
    await act(async () => {
      first.result.current.refine(cards(first)[0].id);
    });
    expect(first.result.current.target).not.toBeNull();
    await first.unmount();

    const second = await restarted();

    expect(second.result.current.target).toBeNull();
    await act(async () => {
      second.result.current.refine(cards(second)[0].id);
    });
    expect(second.result.current.target).toEqual({ planId: 41, title: 'Core' });
  });

  test('starting over forgets the plan too, and finds the waiting card again', async () => {
    const chat = await restarted();
    await act(async () => {
      chat.result.current.refine(cards(chat)[0].id);
    });
    expect(chat.result.current.target).not.toBeNull();

    await act(async () => {
      chat.result.current.reset();
    });

    expect(chat.result.current.target).toBeNull();
    expect(cards(chat)).toHaveLength(1);
  });
});
