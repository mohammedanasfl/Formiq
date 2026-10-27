import { ApiError, type PendingProposal, type WorkoutProposal } from '../src/api';
import type { CoachGateway } from '../src/coach/gateway';
import { MOCK_ALREADY_REPLACED, MOCK_LENGTH_QUESTION, MOCK_NO_MORE_REVISIONS, MOCK_TYPED_REPLIES } from '../src/mock/coachMock';
import { MOCK_REPLACED_PLAN_ID } from '../src/mock/coachProposalsMock';
import {
  createMockCoachGateway,
  createMockSwitches,
  MOCK_APPLY_DELAY_MS,
  MOCK_PENDING_DELAY_MS,
  MOCK_PROPOSAL_DELAY_MS,
  MOCK_REJECT_DELAY_MS,
  MOCK_REPLY_DELAY_MS,
  type MockSwitchStore,
} from '../src/mock/mockCoachGateway';

const NOW = new Date(2026, 9, 22, 9, 0, 0);

let switches: MockSwitchStore;
let gateway: CoachGateway;
// whether a test moved the clock with jest.setSystemTime: the mock then reads the clock the test moved
let later = false;

beforeEach(() => {
  jest.useFakeTimers({ now: NOW });
  later = false;
  switches = createMockSwitches();
  gateway = createMockCoachGateway(switches, () => (later ? new Date() : NOW));
});

afterEach(() => {
  jest.useRealTimers();
});

// asks, and lets the pause pass
async function ask(message: string) {
  const answer = gateway.send({ message, history: [] });
  await jest.advanceTimersByTimeAsync(MOCK_PROPOSAL_DELAY_MS);
  return answer;
}

async function approve(proposal: WorkoutProposal) {
  const saved = gateway.approve({ proposalId: proposal.proposal_id, binding: proposal.binding });
  await jest.advanceTimersByTimeAsync(MOCK_APPLY_DELAY_MS);
  return saved;
}

async function reject(proposal: WorkoutProposal) {
  const done = gateway.reject({ proposalId: proposal.proposal_id, binding: proposal.binding });
  await jest.advanceTimersByTimeAsync(MOCK_REJECT_DELAY_MS);
  return done;
}

// what the backend would list as waiting, once the pause has passed
async function waiting(): Promise<PendingProposal[]> {
  const list = gateway.pending();
  await jest.advanceTimersByTimeAsync(MOCK_PENDING_DELAY_MS);
  return list;
}

// the rejection of a promise, once the pause has passed
async function failure(promise: Promise<unknown>): Promise<ApiError> {
  const caught = promise.then(
    () => {
      throw new Error('it did not fail');
    },
    (error: unknown) => error as ApiError,
  );
  await jest.advanceTimersByTimeAsync(MOCK_PROPOSAL_DELAY_MS);
  return caught;
}

describe('what it answers', () => {
  test.each(['Keep same duration', 'Suggest a different ab workout for today', 'Can I get a different ab workout?', 'swap my abs routine'])(
    '"%s" is a request to change the ab workout: a proposal that revises the saved plan',
    async (message) => {
      const { reply, proposal } = await ask(message);

      expect(proposal?.revision).toMatchObject({ replaces_plan_id: MOCK_REPLACED_PLAN_ID, replaces_plan_name: 'Core & Abs Focus', kind: 'ALTERNATIVE' });
      expect(proposal?.name).toBe('Core Stability & Abs');
      expect(reply).toMatch(/ab workout/);
    },
  );

  test.each(['Create a 25-minute upper-body workout.', 'build me an upper body workout'])('"%s" is a request for a new workout: a proposal that replaces nothing', async (message) => {
    const { proposal } = await ask(message);

    expect(proposal?.revision).toBeNull();
    expect(proposal?.name).toBe('Upper Body Strength');
    expect(proposal?.coverage.focus).toBe('UPPER_BODY');
  });

  test('"Try different length" is answered with a question, and no workout', async () => {
    expect(await ask('Try different length')).toEqual({ reply: MOCK_LENGTH_QUESTION, proposal: null });
  });

  test('any other message gets the preview\'s fixed lines in turn, then round again, and no workout', async () => {
    const replies: string[] = [];
    for (let turn = 0; turn < MOCK_TYPED_REPLIES.length + 1; turn += 1) {
      const answer = await ask(`hello ${turn}`);
      expect(answer.proposal).toBeNull();
      replies.push(answer.reply);
    }

    expect(replies).toEqual([...MOCK_TYPED_REPLIES, MOCK_TYPED_REPLIES[0]]);
  });

  test('the same conversation always gets the same answers', async () => {
    const run = async () => {
      gateway.reset?.();
      const a = await ask('Keep same duration');
      const b = await ask('easier on my knees');
      return [a.reply, a.proposal?.name, b.reply, b.proposal?.name];
    };

    expect(await run()).toEqual(await run());
  });

  test('a proposal is scheduled for today and open for 30 minutes', async () => {
    const { proposal } = await ask('Keep same duration');

    expect(proposal?.scheduled_date).toBe('2026-10-22');
    expect(new Date(proposal!.expires_at).getTime() - NOW.getTime()).toBe(30 * 60_000);
  });

  test('each proposal has its own id and binding, in the backend\'s forms', async () => {
    const first = (await ask('Keep same duration')).proposal!;
    const second = (await ask('easier on my knees')).proposal!;

    for (const proposal of [first, second]) {
      expect(proposal.proposal_id).toMatch(/^[0-9a-f]{32}$/);
      expect(proposal.binding).toMatch(/^[0-9a-f]{64}$/);
    }
    expect(second.proposal_id).not.toBe(first.proposal_id);
    expect(second.binding).not.toBe(first.binding);
  });
});

describe('a change to the workout waiting', () => {
  test('whatever is said while one waits is a change to it: the saved plan\'s revision becomes the knee-friendly one', async () => {
    await ask('Keep same duration');

    const { proposal, reply } = await ask('Keep the same duration, but make it easier on my knees.');

    expect(proposal?.name).toBe('Gentle Core & Abs');
    expect(proposal?.revision?.replaces_plan_id).toBe(MOCK_REPLACED_PLAN_ID);
    expect(reply).toMatch(/knees/);
  });

  test('a new workout changed is another new workout, with no equipment', async () => {
    await ask('Create a 25-minute upper-body workout.');

    const { proposal } = await ask('Use no equipment');

    expect(proposal?.name).toBe('Upper Body, No Equipment');
    expect(proposal?.revision).toBeNull();
    expect(proposal?.exercises.every((exercise) => exercise.equipment.length === 0)).toBe(true);
  });

  test('has one change of each: after that it says so, with words only', async () => {
    await ask('Keep same duration');
    await ask('easier');

    expect(await ask('and again')).toEqual({ reply: MOCK_NO_MORE_REVISIONS, proposal: null });
  });
});

describe('the saved plan', () => {
  test('is left exactly as it was by every proposal and every change: only an approval touches it', async () => {
    await ask('Keep same duration');
    await ask('easier on my knees');

    // still PLANNED: another edit of it is still proposed, and the proposals still replace it
    expect((await waiting()).map((item) => item.revision?.replaces_plan_id)).toEqual([MOCK_REPLACED_PLAN_ID, MOCK_REPLACED_PLAN_ID]);
  });
});

describe('approving', () => {
  test('saves the workout as a new PLANNED plan with the proposal\'s own exercises, and cancels the one it replaces', async () => {
    const { proposal } = await ask('Keep same duration');

    const saved = await approve(proposal!);

    expect(saved).toMatchObject({ name: 'Core Stability & Abs', status: 'PLANNED', scheduled_date: '2026-10-22' });
    expect(saved.id).not.toBe(MOCK_REPLACED_PLAN_ID);
    expect(saved.exercises.map((exercise) => exercise.exercise.name)).toEqual(proposal!.exercises.map((exercise) => exercise.exercise_name));
    // the one it replaces is cancelled: another edit of it is refused, and nothing waiting still replaces it
    expect(await ask('a different ab workout')).toEqual({ reply: MOCK_ALREADY_REPLACED, proposal: null });
    expect(await waiting()).toEqual([]);
  });

  test('a new workout saves a plan and cancels nothing', async () => {
    const { proposal } = await ask('Create a 25-minute upper-body workout.');

    await approve(proposal!);

    // the ab workout is still there to be changed
    expect((await ask('Keep same duration')).proposal?.revision?.replaces_plan_id).toBe(MOCK_REPLACED_PLAN_ID);
  });

  test('takes as long as the backend would: nothing is saved before the pause is over', async () => {
    const { proposal } = await ask('Keep same duration');

    const saved = gateway.approve({ proposalId: proposal!.proposal_id, binding: proposal!.binding });
    await jest.advanceTimersByTimeAsync(MOCK_APPLY_DELAY_MS - 1);
    // asked now, the list is as it is now: the proposal still waits
    const before = gateway.pending();
    await jest.advanceTimersByTimeAsync(1);
    await saved;
    const after = gateway.pending();
    await jest.advanceTimersByTimeAsync(MOCK_PENDING_DELAY_MS);

    expect((await before).map((item) => item.proposal_id)).toEqual([proposal!.proposal_id]);
    expect(await after).toEqual([]);
  });

  test('refuses a proposal it does not know, as the backend does: 404', async () => {
    const error = await failure(gateway.approve({ proposalId: 'f'.repeat(32), binding: 'f'.repeat(64) }).then(() => null));
    // (the pause of an approval)
    expect(error).toMatchObject({ kind: 'http', status: 404 });
  });

  test('refuses a binding that is not the one of the proposal shown: 409, and saves nothing', async () => {
    const { proposal } = await ask('Keep same duration');

    const error = await failure(gateway.approve({ proposalId: proposal!.proposal_id, binding: '0'.repeat(64) }));

    expect(error).toMatchObject({ kind: 'http', status: 409, detail: expect.stringMatching(/different version/) });
    expect((await waiting()).map((item) => item.proposal_id)).toEqual([proposal!.proposal_id]);
  });

  test('approves a proposal once, and asking again returns the plan the first approval saved, not a second plan', async () => {
    const { proposal } = await ask('Create a 25-minute upper-body workout.');
    const first = await approve(proposal!);

    const again = await approve(proposal!);

    expect(again).toEqual(first);
    // and nothing was saved twice: the next plan has the next id
    const another = (await ask('Create a 25-minute upper-body workout.')).proposal!;
    expect((await approve(another)).id).toBe(first.id + 1);
  });

  test('refuses a rejected proposal, with the backend\'s words: 409 "rejected"', async () => {
    const { proposal } = await ask('Keep same duration');
    await reject(proposal!);

    const error = await failure(gateway.approve({ proposalId: proposal!.proposal_id, binding: proposal!.binding }));

    expect(error).toMatchObject({ status: 409, detail: expect.stringMatching(/rejected/) });
  });

  test('refuses a proposal after its 30 minutes: 409 "expired"', async () => {
    const { proposal } = await ask('Keep same duration');
    jest.setSystemTime(NOW.getTime() + 31 * 60_000);
    later = true;

    const error = await failure(gateway.approve({ proposalId: proposal!.proposal_id, binding: proposal!.binding }));

    expect(error).toMatchObject({ status: 409, detail: expect.stringMatching(/expired/) });
  });

  test('refuses a proposal whose saved plan has since been replaced: 409, the backend\'s own words', async () => {
    const older = (await ask('Keep same duration')).proposal!;
    const newer = (await ask('easier on my knees')).proposal!;
    await approve(newer);

    const error = await failure(gateway.approve({ proposalId: older.proposal_id, binding: older.binding }));

    expect(error).toMatchObject({ status: 409, detail: expect.stringMatching(/changed or cancelled since it was proposed/) });
  });

  test('and the proposal that replaces it is no longer listed as waiting: the backend would not offer it', async () => {
    const older = (await ask('Keep same duration')).proposal!;
    const newer = (await ask('easier on my knees')).proposal!;
    expect((await waiting()).map((item) => item.proposal_id)).toEqual([newer.proposal_id, older.proposal_id]);

    await approve(newer);

    expect(await waiting()).toEqual([]);
  });

  test('once the ab workout was replaced, asking for another change to it says so, and proposes nothing', async () => {
    const { proposal } = await ask('Keep same duration');
    await approve(proposal!);

    expect(await ask('a different ab workout')).toEqual({ reply: MOCK_ALREADY_REPLACED, proposal: null });
  });

  test('a workout approved is no longer the one waiting: the next message is not a change to it', async () => {
    const { proposal } = await ask('Create a 25-minute upper-body workout.');
    await approve(proposal!);

    const answer = await ask('hello');

    expect(answer).toEqual({ reply: MOCK_TYPED_REPLIES[0], proposal: null });
  });
});

describe('the switches that force a failure', () => {
  test('"next request fails" makes the next send fail once, like a lost connection, and the one after work', async () => {
    switches.set({ failNextRequest: true });

    const error = await failure(gateway.send({ message: 'hello', history: [] }));

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ kind: 'network' });
    expect(switches.get().failNextRequest).toBe(false);
    expect((await ask('hello')).reply).toBe(MOCK_TYPED_REPLIES[0]);
  });

  test('a request that failed leaves no workout waiting: asking again gets the same workout, not a change to it', async () => {
    switches.set({ failNextRequest: true });
    await failure(gateway.send({ message: 'Keep same duration', history: [] }));

    const { proposal } = await ask('Keep same duration');

    expect(proposal?.name).toBe('Core Stability & Abs');
  });

  test('"next apply fails" makes the next approval fail once, saving nothing, and the next one works', async () => {
    const { proposal } = await ask('Keep same duration');
    switches.set({ failNextApply: true });

    const error = await failure(gateway.approve({ proposalId: proposal!.proposal_id, binding: proposal!.binding }));

    expect(error).toMatchObject({ kind: 'network' });
    expect(switches.get().failNextApply).toBe(false);
    expect((await waiting()).map((item) => item.proposal_id)).toEqual([proposal!.proposal_id]);

    const saved = await approve(proposal!);
    expect(saved.status).toBe('PLANNED');
  });

  test('"next dismiss fails" makes the next rejection fail once, dismissing nothing, and the next one works', async () => {
    const { proposal } = await ask('Keep same duration');
    switches.set({ failNextReject: true });

    const error = await failure(gateway.reject({ proposalId: proposal!.proposal_id, binding: proposal!.binding }));

    expect(error).toMatchObject({ kind: 'network' });
    expect(switches.get().failNextReject).toBe(false);
    expect((await waiting()).map((item) => item.proposal_id)).toEqual([proposal!.proposal_id]);
    await expect(reject(proposal!)).resolves.toBeUndefined();
    expect(await waiting()).toEqual([]);
  });

  test('each is off to begin with, and subscribers hear when one changes', () => {
    expect(switches.get()).toEqual({ failNextRequest: false, failNextApply: false, failNextReject: false, waiting: 0 });
    const heard = jest.fn();
    const unsubscribe = switches.subscribe(heard);

    switches.set({ failNextApply: true });
    unsubscribe();
    switches.set({ failNextApply: false });

    expect(heard).toHaveBeenCalledTimes(1);
  });
});

describe('rejecting', () => {
  test('dismisses the proposal: resolves with nothing once the pause has passed, and it is no longer waiting', async () => {
    const { proposal } = await ask('Keep same duration');

    const done = gateway.reject({ proposalId: proposal!.proposal_id, binding: proposal!.binding });
    const settled = jest.fn();
    void done.then(settled);
    await jest.advanceTimersByTimeAsync(MOCK_REJECT_DELAY_MS - 1);
    expect(settled).not.toHaveBeenCalled();
    await jest.advanceTimersByTimeAsync(1);

    await expect(done).resolves.toBeUndefined();
    expect(await waiting()).toEqual([]);
  });

  test('is the same answer when repeated', async () => {
    const { proposal } = await ask('Keep same duration');
    await reject(proposal!);

    await expect(reject(proposal!)).resolves.toBeUndefined();
  });

  test('saves nothing and leaves the saved plan as it was: the ab workout can still be changed', async () => {
    const { proposal } = await ask('Keep same duration');
    await reject(proposal!);

    expect((await ask('Keep same duration')).proposal?.revision?.replaces_plan_id).toBe(MOCK_REPLACED_PLAN_ID);
  });

  test('is refused for a proposal that was approved, as the backend does: 409', async () => {
    const { proposal } = await ask('Create a 25-minute upper-body workout.');
    await approve(proposal!);

    const error = await failure(gateway.reject({ proposalId: proposal!.proposal_id, binding: proposal!.binding }));

    expect(error).toMatchObject({ kind: 'http', status: 409, detail: expect.stringMatching(/already approved/) });
  });

  test('is refused for a binding that is not the one of the proposal shown: 409', async () => {
    const { proposal } = await ask('Keep same duration');

    const error = await failure(gateway.reject({ proposalId: proposal!.proposal_id, binding: '0'.repeat(64) }));

    expect(error).toMatchObject({ status: 409, detail: expect.stringMatching(/different version/) });
    expect((await waiting()).map((item) => item.proposal_id)).toEqual([proposal!.proposal_id]);
  });

  test('a proposal it does not know is 404', async () => {
    const error = await failure(gateway.reject({ proposalId: 'f'.repeat(32), binding: 'f'.repeat(64) }));

    expect(error).toMatchObject({ kind: 'http', status: 404 });
  });

  test('a workout dismissed is no longer the one waiting: the next message is not a change to it', async () => {
    const { proposal } = await ask('Create a 25-minute upper-body workout.');
    await reject(proposal!);

    expect(await ask('hello')).toEqual({ reply: MOCK_TYPED_REPLIES[0], proposal: null });
  });
});

describe('the proposals waiting for the person', () => {
  test('are the ones made and not yet approved or dismissed, the most recently made first, each with when it was made', async () => {
    const first = (await ask('Create a 25-minute upper-body workout.')).proposal!;
    jest.setSystemTime(NOW.getTime() + 60_000);
    later = true;
    const second = (await ask('Use no equipment')).proposal!;

    const list = await waiting();

    expect(list.map((item) => item.proposal_id)).toEqual([second.proposal_id, first.proposal_id]);
    expect(list[0].created_at).toBe(new Date(NOW.getTime() + 60_000).toISOString());
    expect(list[1]).toMatchObject({ ...first, created_at: NOW.toISOString() });
  });

  test('are none to begin with, and a copy that cannot be changed from outside', async () => {
    expect(await waiting()).toEqual([]);
    const { proposal } = await ask('Keep same duration');

    (await waiting())[0].name = 'Changed from outside';

    expect((await waiting())[0].name).toBe(proposal!.name);
  });

  test('do not include one that is approved, dismissed, expired or whose saved plan was replaced', async () => {
    const approved = (await ask('Create a 25-minute upper-body workout.')).proposal!;
    await approve(approved);
    const dismissed = (await ask('Keep same duration')).proposal!;
    await reject(dismissed);
    const kept = (await ask('Keep same duration')).proposal!;
    expect((await waiting()).map((item) => item.proposal_id)).toEqual([kept.proposal_id]);

    jest.setSystemTime(NOW.getTime() + 31 * 60_000);
    later = true;
    expect(await waiting()).toEqual([]);
  });

  test('take as long as the backend would, and only read: nothing is proposed, approved or dismissed by asking', async () => {
    const { proposal } = await ask('Keep same duration');
    const list = gateway.pending();
    const settled = jest.fn();
    void list.then(settled);
    await jest.advanceTimersByTimeAsync(MOCK_PENDING_DELAY_MS - 1);
    expect(settled).not.toHaveBeenCalled();
    await jest.advanceTimersByTimeAsync(1);

    expect((await list).map((item) => item.proposal_id)).toEqual([proposal!.proposal_id]);
    expect((await waiting()).map((item) => item.proposal_id)).toEqual([proposal!.proposal_id]);
  });

  test.each([
    [1, 1],
    [2, 2],
  ])('the "%s waiting" switch leaves %s proposals made earlier for the next time the screen asks, and then is off', async (count, listed) => {
    switches.set({ waiting: count as 1 | 2 });

    const list = await waiting();

    expect(list).toHaveLength(listed);
    expect(switches.get().waiting).toBe(0);
    // made 12 minutes ago, and (with two) another 5 minutes ago: they are the newest first and each can still be approved
    const ages = list.map((item) => Math.round((NOW.getTime() - new Date(item.created_at).getTime()) / 60_000));
    expect(ages).toEqual(count === 1 ? [12] : [5, 12]);
    expect((await waiting()).map((item) => item.proposal_id)).toEqual(list.map((item) => item.proposal_id));
    const saved = await approve(list[0]);
    expect(saved.status).toBe('PLANNED');
  });

  test('the newest of them is the one the coach changes, as the backend\'s coach changes the newest waiting one', async () => {
    switches.set({ waiting: 2 });
    const [newest] = await waiting();

    const { proposal } = await ask('easier on my knees');

    // the newest seeded is an edit of the saved plan: its refinement is the knee-friendly edit
    expect(newest.name).toBe('Core Stability & Abs');
    expect(proposal?.name).toBe('Gentle Core & Abs');
    expect(proposal?.revision?.replaces_plan_id).toBe(MOCK_REPLACED_PLAN_ID);
  });

  test('starting over forgets them, which a real backend would not: a preview starts a fresh conversation', async () => {
    await ask('Keep same duration');

    gateway.reset?.();

    expect(await waiting()).toEqual([]);
  });
});

describe('the pauses', () => {
  test('words take a moment, a workout a little longer', async () => {
    const words = gateway.send({ message: 'hello', history: [] });
    const settled = jest.fn();
    void words.then(settled);

    await jest.advanceTimersByTimeAsync(MOCK_REPLY_DELAY_MS - 1);
    expect(settled).not.toHaveBeenCalled();
    await jest.advanceTimersByTimeAsync(1);
    expect(settled).toHaveBeenCalledTimes(1);

    const workout = gateway.send({ message: 'Keep same duration', history: [] });
    const workoutSettled = jest.fn();
    void workout.then(workoutSettled);
    await jest.advanceTimersByTimeAsync(MOCK_REPLY_DELAY_MS);
    expect(workoutSettled).not.toHaveBeenCalled();
    await jest.advanceTimersByTimeAsync(MOCK_PROPOSAL_DELAY_MS - MOCK_REPLY_DELAY_MS);
    expect(workoutSettled).toHaveBeenCalledTimes(1);
  });
});

describe('starting over', () => {
  test('brings back the saved plan, forgets the workout waiting and starts the fixed lines again', async () => {
    const { proposal } = await ask('Keep same duration');
    await approve(proposal!);
    await ask('hello');

    gateway.reset?.();

    // the saved plan is back: it can be changed again, and it is the first thing proposed
    expect((await ask('hello')).reply).toBe(MOCK_TYPED_REPLIES[0]);
    expect((await ask('Keep same duration')).proposal?.name).toBe('Core Stability & Abs');
  });
});

describe('it is a mock, and it stays one', () => {
  test('makes no network request', async () => {
    const fetchSpy = jest.fn();
    (globalThis as { fetch: unknown }).fetch = fetchSpy;

    const { proposal } = await ask('Keep same duration');
    await approve(proposal!);
    await waiting();
    await reject((await ask('Create a 25-minute upper-body workout.')).proposal!);

    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
