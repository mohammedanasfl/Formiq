import {
  canAskForChanges,
  chatReducer,
  historyFrom,
  initialChatState,
  isApplicable,
  isApplying,
  isRejecting,
  isWaiting,
  MAX_HISTORY_TEXT_LENGTH,
  MAX_HISTORY_TURNS,
  newestWaiting,
  suggestionsFor,
  type ChatAction,
  type ChatItem,
  type ChatState,
  type ProposalPhase,
} from '../src/coach/chatState';
import { coachOpening } from '../src/coach/opening';
import { REFINEMENT_SUGGESTIONS } from '../src/coach/suggestions';
import { MOCK_INTRO, MOCK_OPENING } from '../src/mock/coachMock';
import { mockPendingProposal, mockProposal } from '../src/mock/coachProposalsMock';

const NOW = new Date(2026, 9, 22, 9, 0, 0);
const RETRYABLE = { message: 'again', retryable: true };

const run = (state: ChatState, ...actions: ChatAction[]) => actions.reduce(chatReducer, state);
const opening = initialChatState(MOCK_OPENING);
const CONFIRMED = (id: number) => ({ id, name: 'Core Stability & Abs', scheduled_date: '2026-10-22' });
const appliedAs = (planId: number): ProposalPhase => ({ kind: 'applied', planId, name: 'Core Stability & Abs', scheduledDate: '2026-10-22' });
const phaseOf = (state: ChatState, id: string): ProposalPhase => {
  const item = state.items.find((entry) => entry.id === id);
  if (item?.kind !== 'proposal') throw new Error(`no proposal ${id}`);
  return item.phase;
};
const proposals = (state: ChatState) => state.items.filter((item): item is Extract<ChatItem, { kind: 'proposal' }> => item.kind === 'proposal');

const edit = (sequence: number) => mockProposal('edit', NOW, sequence);
const asked = (state: ChatState, text = 'hello', expectsWorkout = false) => run(state, { type: 'user-sent', text, expectsWorkout });
const answered = (state: ChatState, sequence: number, kind: 'new' | 'edit' = 'edit') =>
  run(asked(state), { type: 'reply', reply: 'Here is a workout.', proposal: mockProposal(kind, NOW, sequence) });

describe('the conversation starts from what it is given', () => {
  test('with the opening items and ids that carry on from them', () => {
    expect(opening.items).toEqual(MOCK_INTRO);
    expect(asked(opening).items.slice(-2).map((item) => item.id)).toEqual(['m4', 'm5']);
  });
});

describe('sending a message', () => {
  test('adds the user\'s message, then something pending for the coach to answer', () => {
    const state = asked(opening, 'Create a workout', true);

    expect(state.items.slice(-2)).toEqual([
      { kind: 'message', id: 'm4', role: 'user', text: 'Create a workout' },
      { kind: 'pending', id: 'm5', expectsWorkout: true },
    ]);
    expect(isWaiting(state)).toBe(true);
  });
});

describe('the coach answers', () => {
  test('with words only: the pending item becomes the coach\'s message', () => {
    const state = run(asked(opening), { type: 'reply', reply: 'Hi there', proposal: null });

    expect(state.items.slice(-2)).toEqual([
      { kind: 'message', id: 'm4', role: 'user', text: 'hello' },
      { kind: 'message', id: 'm6', role: 'assistant', text: 'Hi there' },
    ]);
    expect(isWaiting(state)).toBe(false);
  });

  test('with a workout: the words, then the workout, ready, and not recovered from before', () => {
    const state = answered(opening, 1);

    expect(state.items.slice(-2).map((item) => item.kind)).toEqual(['message', 'proposal']);
    const [card] = proposals(state);
    expect(card.phase).toEqual({ kind: 'ready' });
    expect(card.recovered).toBeNull();
    expect(card.proposal.proposal_id).toBe(edit(1).proposal_id);
    // what it changes is the backend's, in the proposal itself
    expect(card.proposal.changes?.compared_with_plan_id).toBe(41);
  });

  test('an answer nobody is waiting for (the conversation started over) is dropped', () => {
    const state = run(opening, { type: 'reply', reply: 'late', proposal: edit(1) });

    expect(state).toBe(opening);
  });

  test('a newer workout ends the older one that was still waiting to be applied', () => {
    const state = answered(answered(opening, 1), 2);
    const [older, newer] = proposals(state);

    expect(older.phase).toEqual({ kind: 'superseded', reason: 'newer-version' });
    expect(newer.phase).toEqual({ kind: 'ready' });
  });

  test('words only do not end an older workout: it is still the one to apply', () => {
    const state = run(asked(answered(opening, 1)), { type: 'reply', reply: 'Sure', proposal: null });

    expect(proposals(state)[0].phase).toEqual({ kind: 'ready' });
  });

  test('a workout that was applied stays applied when a newer one arrives', () => {
    const first = answered(opening, 1);
    const [{ id }] = proposals(first);
    const applied = run(first, { type: 'apply-started', id }, { type: 'apply-succeeded', id, plan: CONFIRMED(100) });

    const state = answered(applied, 2, 'new');

    expect(proposals(state)[0].phase).toEqual(appliedAs(100));
  });
});

describe('the coach fails and the request is tried again', () => {
  test('the pending item becomes a failure that keeps whether it was a request for a workout', () => {
    const state = run(asked(opening, 'x', true), { type: 'request-failed', message: 'nope' });

    expect(state.items.at(-1)).toEqual({ kind: 'failed', id: 'm5', message: 'nope', retryable: true, expectsWorkout: true });
    expect(isWaiting(state)).toBe(false);
  });

  test('trying again puts it back to pending, with the same id, and adds no second message of the user\'s', () => {
    const failed = run(asked(opening, 'x', true), { type: 'request-failed', message: 'nope' });

    const state = run(failed, { type: 'retry' });

    expect(state.items.at(-1)).toEqual({ kind: 'pending', id: 'm5', expectsWorkout: true });
    expect(state.items.filter((item) => item.kind === 'message' && item.role === 'user' && item.text === 'x')).toHaveLength(1);
  });

  test('a failure with nothing waiting, or a retry with nothing failed, changes nothing', () => {
    expect(run(opening, { type: 'request-failed', message: 'x' })).toBe(opening);
    expect(run(opening, { type: 'retry' })).toBe(opening);
  });
});

describe('applying a workout', () => {
  const first = answered(opening, 1);
  const id = proposals(first)[0].id;

  test('starts: the workout is applying, and nothing else about it changes', () => {
    const state = run(first, { type: 'apply-started', id });

    expect(phaseOf(state, id)).toEqual({ kind: 'applying' });
    expect(isApplying(state)).toBe(true);
    expect(proposals(state)[0].proposal).toBe(proposals(first)[0].proposal);
  });

  test('succeeds only on the backend\'s word: applied, with the plan it saved', () => {
    const state = run(first, { type: 'apply-started', id }, { type: 'apply-succeeded', id, plan: CONFIRMED(100) });

    expect(phaseOf(state, id)).toEqual(appliedAs(100));
    expect(isApplying(state)).toBe(false);
  });

  test('fails: the workout is as it was, and says why it could not be applied', () => {
    const state = run(first, { type: 'apply-started', id }, { type: 'apply-failed', id, failure: RETRYABLE });

    expect(phaseOf(state, id)).toEqual({ kind: 'apply-failed', failure: RETRYABLE });
    expect(proposals(state)[0].proposal).toBe(proposals(first)[0].proposal);
  });

  test('applying again after a failure that can be tried again goes through the same start and end', () => {
    const state = run(
      first,
      { type: 'apply-started', id },
      { type: 'apply-failed', id, failure: RETRYABLE },
      { type: 'apply-started', id },
      { type: 'apply-succeeded', id, plan: CONFIRMED(101) },
    );

    expect(phaseOf(state, id)).toEqual(appliedAs(101));
  });

  test('another workout for the same saved plan, still waiting, is ended: the backend cancelled that plan', () => {
    // two workouts for plan 41 on the page, as the conversation has them when a refinement came back and the
    // older one was left (here: put back to ready, to show the rule on its own)
    const second = answered(first, 2);
    const [older, newer] = proposals(second);
    const both = { ...second, items: second.items.map((item) => (item.id === older.id ? { ...older, phase: { kind: 'ready' } as const } : item)) };

    const state = run(both, { type: 'apply-started', id: newer.id }, { type: 'apply-succeeded', id: newer.id, plan: CONFIRMED(100) });

    expect(phaseOf(state, newer.id)).toEqual(appliedAs(100));
    expect(phaseOf(state, older.id)).toEqual({ kind: 'superseded', reason: 'workout-replaced' });
  });

  test('a new workout (it replaces nothing) ends no other', () => {
    const newOne = answered(opening, 3, 'new');
    const other = answered(newOne, 4, 'new');
    const [older, newer] = proposals(other);
    const both = { ...other, items: other.items.map((item) => (item.id === older.id ? { ...older, phase: { kind: 'ready' } as const } : item)) };

    const state = run(both, { type: 'apply-started', id: newer.id }, { type: 'apply-succeeded', id: newer.id, plan: CONFIRMED(100) });

    expect(phaseOf(state, older.id)).toEqual({ kind: 'ready' });
  });

  test('an id that is not a workout of the page changes nothing', () => {
    const state = run(first, { type: 'apply-started', id: 'nope' });

    expect(proposals(state).map((card) => card.phase)).toEqual(proposals(first).map((card) => card.phase));
  });
});

describe('isApplicable: when a workout can be sent for approval', () => {
  test.each<[ProposalPhase, boolean]>([
    [{ kind: 'ready' }, true],
    [{ kind: 'apply-failed', failure: RETRYABLE }, true],
    [{ kind: 'apply-failed', failure: { message: 'expired', retryable: false } }, false],
    [{ kind: 'applying' }, false],
    [appliedAs(1), false],
    [{ kind: 'rejecting' }, false],
    [{ kind: 'rejected' }, false],
    [{ kind: 'reject-failed', failure: RETRYABLE }, true],
    [{ kind: 'reject-failed', failure: { message: 'already applied', retryable: false } }, false],
    [{ kind: 'expired' }, false],
    [{ kind: 'superseded', reason: 'newer-version' }, false],
  ])('%j: %s', (phase, applicable) => {
    expect(isApplicable(phase)).toBe(applicable);
  });
});

describe('starting over', () => {
  test('puts the conversation back to the state it is given', () => {
    const state = run(answered(opening, 1), { type: 'reset', to: opening });

    expect(state).toBe(opening);
  });
});

describe('historyFrom: the turns the coach API takes', () => {
  test('has the words of both sides, the coach\'s as "coach", and nothing that is not words', () => {
    const state = answered(opening, 1);

    expect(historyFrom(state.items)).toEqual([
      { role: 'coach', text: MOCK_INTRO[0].kind === 'message' ? MOCK_INTRO[0].text : '' },
      { role: 'user', text: 'Can I get a different ab workout?' },
      { role: 'coach', text: 'Sure. Do you want to keep the same duration, or try a different length?' },
      { role: 'user', text: 'hello' },
      { role: 'coach', text: 'Here is a workout.' },
    ]);
  });

  test('carries no proposal, no plan and no binding: the coach reads the workout waiting for approval itself', () => {
    const json = JSON.stringify(historyFrom(answered(opening, 1).items));

    expect(json).not.toMatch(/binding|proposal_id|exercise_name|replaces_plan|workout-plans/);
  });

  test('keeps the most recent turns, as many as the API takes', () => {
    const items: ChatItem[] = Array.from({ length: MAX_HISTORY_TURNS + 7 }, (_, index) => ({
      kind: 'message',
      id: `m${index}`,
      role: index % 2 ? 'user' : 'assistant',
      text: `turn ${index}`,
    }));

    const history = historyFrom(items);

    expect(history).toHaveLength(MAX_HISTORY_TURNS);
    expect(history[0].text).toBe('turn 7');
    expect(history.at(-1)?.text).toBe(`turn ${MAX_HISTORY_TURNS + 6}`);
  });

  test('cuts a turn to the longest the API takes', () => {
    const long: ChatItem = { kind: 'message', id: 'm1', role: 'user', text: 'x'.repeat(MAX_HISTORY_TEXT_LENGTH + 50) };

    expect(historyFrom([long])[0].text).toHaveLength(MAX_HISTORY_TEXT_LENGTH);
  });

  test('the API\'s limits are the backend\'s: 50 turns of 8,000 characters', () => {
    expect([MAX_HISTORY_TURNS, MAX_HISTORY_TEXT_LENGTH]).toEqual([50, 8000]);
  });
});

describe('suggestionsFor: which replies to offer', () => {
  const offered = (state: ChatState) => suggestionsFor(state, REFINEMENT_SUGGESTIONS);

  test('the ones the screen opened with, until the user says something', () => {
    expect(offered(opening)).toBe(MOCK_OPENING.suggestions);
  });

  test('none once they have, unless the coach has just shown a workout', () => {
    const talked = run(asked(opening), { type: 'reply', reply: 'ok', proposal: null });

    expect(offered(talked)).toEqual([]);
  });

  test('none while the coach is working or a workout is being applied', () => {
    const waiting = asked(opening);
    const shown = answered(opening, 1);
    const id = proposals(shown)[0].id;

    expect(offered(waiting)).toEqual([]);
    expect(offered(run(shown, { type: 'apply-started', id }))).toEqual([]);
  });

  test('ways to change the workout, while the last thing on the page is one that can still be applied', () => {
    const shown = answered(opening, 1);
    const id = proposals(shown)[0].id;

    expect(offered(shown)).toBe(REFINEMENT_SUGGESTIONS);
    expect(offered(run(shown, { type: 'apply-started', id }, { type: 'apply-failed', id, failure: RETRYABLE }))).toBe(REFINEMENT_SUGGESTIONS);
  });

  test('none for a workout that was applied, one that cannot be applied, or one that was replaced', () => {
    const shown = answered(opening, 1);
    const id = proposals(shown)[0].id;

    expect(offered(run(shown, { type: 'apply-started', id }, { type: 'apply-succeeded', id, plan: CONFIRMED(1) }))).toEqual([]);
    expect(offered(run(shown, { type: 'apply-started', id }, { type: 'apply-failed', id, failure: { message: 'x', retryable: false } }))).toEqual([]);
  });

  test('every way to change a workout is a request for one', () => {
    expect(REFINEMENT_SUGGESTIONS.map((reply) => reply.label)).toEqual([
      'Keep same duration',
      'Try different length',
      'Make it more intense',
      'Use no equipment',
    ]);
    expect(REFINEMENT_SUGGESTIONS.every((reply) => reply.expectsWorkout === true)).toBe(true);
  });
});

describe('a line the app wrote itself', () => {
  const greeting: ChatItem = { kind: 'message', id: 'm1', role: 'assistant', text: 'Hi, I am the greeting.', inHistory: false };

  test('is shown but is not sent to the coach as something said in the conversation', () => {
    const state = asked(initialChatState({ items: [greeting], suggestions: [] }), 'a workout please');

    expect(state.items.filter((item) => item.kind === 'message')).toHaveLength(2);
    expect(historyFrom(state.items)).toEqual([{ role: 'user', text: 'a workout please' }]);
  });

  // the workout the conversation is about travels in its own field (workout_plan_id), so the question that names it
  // is shown and nothing more: sending it as something the coach said would be a second, weaker way of saying so
  test('is not sent either when it is the question that names the workout the conversation is about', () => {
    const launch = { workoutId: 41, title: 'Core & Abs Focus' };
    const state = asked(initialChatState(coachOpening(launch), launch), 'make it shorter');

    expect(state.items.filter((item) => item.kind === 'message')).toHaveLength(2);
    expect(historyFrom(state.items)).toEqual([{ role: 'user', text: 'make it shorter' }]);
  });
});

describe('an answer with a workout and no words', () => {
  test('shows the card alone: an empty bubble would say nothing', () => {
    const state = run(asked(opening), { type: 'reply', reply: '  ', proposal: mockProposal('new', NOW, 1) });

    expect(state.items.filter((item) => item.kind === 'message')).toHaveLength(opening.items.length + 1);
    expect(proposals(state)).toHaveLength(1);
  });
});

describe('a failure followed by a new question', () => {
  test('stays in the conversation but can no longer be tried again: only the latest request can be repeated', () => {
    const failed = run(asked(opening, 'first'), { type: 'request-failed', message: 'nope', retryable: true });

    const state = asked(failed, 'second');

    const [older] = state.items.filter((item) => item.kind === 'failed');
    expect(older).toMatchObject({ kind: 'failed', message: 'nope', retryable: false });
    expect(state.items.at(-1)).toMatchObject({ kind: 'pending' });
  });
});

describe('a failure that asking again cannot help', () => {
  test('is kept as one, and a retry puts the pending item back', () => {
    const state = run(asked(opening, 'x', true), { type: 'request-failed', message: 'Log in again.', retryable: false });

    expect(state.items.at(-1)).toMatchObject({ kind: 'failed', retryable: false });
  });
});

describe('the opening a conversation carries', () => {
  const launch = { workoutId: 41, title: 'Core & Abs Focus' };

  test('keeps the workout it was opened from, and none when it was opened from none', () => {
    expect(initialChatState({ items: [], suggestions: [] }, launch).launch).toEqual(launch);
    expect(initialChatState({ items: [], suggestions: [] }).launch).toBeNull();
  });

  test('is about that saved workout, when it has a plan id: the one every message names', () => {
    expect(initialChatState({ items: [], suggestions: [] }, launch).target).toEqual({ planId: 41, title: 'Core & Abs Focus' });
    expect(initialChatState({ items: [], suggestions: [] }).target).toBeNull();
    // only a saved plan has an id the backend can be pointed at
    expect(initialChatState({ items: [], suggestions: [] }, { workoutId: 'mock-1', title: 'Core' }).target).toBeNull();
  });

  test("offers its own replies until the user says something, and not the screen's others", () => {
    const own = [{ id: 'own', label: 'Make it shorter', expectsWorkout: true }];
    const state = initialChatState({ items: [{ kind: 'message', id: 'm1', role: 'assistant', text: 'Hi' }], suggestions: own }, launch);

    expect(suggestionsFor(state, REFINEMENT_SUGGESTIONS)).toEqual(own);
    expect(suggestionsFor(asked(state), REFINEMENT_SUGGESTIONS)).toEqual([]);
  });

  test('starting over replaces it as a whole: its items, its replies and its workout', () => {
    const state = run(asked(initialChatState(MOCK_OPENING, launch)), { type: 'reset', to: initialChatState({ items: [], suggestions: [] }) });

    expect(state.launch).toBeNull();
    expect(state.target).toBeNull();
    expect(state.items).toEqual([]);
  });
});

describe('the saved workout the conversation is about', () => {
  const launch = { workoutId: 41, title: 'Core & Abs Focus' };
  const about = () => initialChatState({ items: [], suggestions: [] }, launch);
  const applied = (state: ChatState, plan: { id: number; name: string; scheduled_date: string | null }) => {
    const shown = run(asked(state), { type: 'reply', reply: 'Here.', proposal: edit(1) });
    const [{ id }] = proposals(shown);
    return run(shown, { type: 'apply-started', id }, { type: 'apply-succeeded', id, plan });
  };

  test('moves to the saved plan when a revision of it is applied: the plan it replaced is cancelled', () => {
    const state = applied(about(), { id: 55, name: 'Core Stability & Abs', scheduled_date: '2026-10-22' });

    expect(state.target).toEqual({ planId: 55, title: 'Core Stability & Abs' });
    // the screen was opened from the workout, and still says so
    expect(state.launch).toEqual(launch);
  });

  test('does not move when the revision was of another workout', () => {
    const state = applied(initialChatState({ items: [], suggestions: [] }, { workoutId: 99, title: 'Leg Day' }), { id: 55, name: 'X', scheduled_date: null });

    expect(state.target).toEqual({ planId: 99, title: 'Leg Day' });
  });

  test('does not move when a new workout is applied, which replaces nothing', () => {
    const shown = run(asked(about()), { type: 'reply', reply: 'Here.', proposal: mockProposal('new', NOW, 1) });
    const [{ id }] = proposals(shown);

    const state = run(shown, { type: 'apply-started', id }, { type: 'apply-succeeded', id, plan: CONFIRMED(60) });

    expect(state.target).toEqual({ planId: 41, title: 'Core & Abs Focus' });
  });

  test('is none to begin with when the conversation is about no workout, and an apply does not make one', () => {
    const state = applied(initialChatState({ items: [], suggestions: [] }), { id: 55, name: 'X', scheduled_date: null });

    expect(state.target).toBeNull();
  });
});

describe('dismissing a workout', () => {
  const first = answered(opening, 1);
  const id = proposals(first)[0].id;

  test('starts: the workout is being dismissed, and nothing else about it changes', () => {
    const state = run(first, { type: 'reject-started', id });

    expect(phaseOf(state, id)).toEqual({ kind: 'rejecting' });
    expect(isRejecting(state)).toBe(true);
    expect(isApplying(state)).toBe(false);
    expect(proposals(state)[0].proposal).toBe(proposals(first)[0].proposal);
  });

  test('succeeds only on the backend\'s word: dismissed', () => {
    const state = run(first, { type: 'reject-started', id }, { type: 'reject-succeeded', id });

    expect(phaseOf(state, id)).toEqual({ kind: 'rejected' });
    expect(isRejecting(state)).toBe(false);
  });

  test('fails: the workout is as it was, and says why it could not be dismissed', () => {
    const state = run(first, { type: 'reject-started', id }, { type: 'reject-failed', id, failure: RETRYABLE });

    expect(phaseOf(state, id)).toEqual({ kind: 'reject-failed', failure: RETRYABLE });
    expect(proposals(state)[0].proposal).toBe(proposals(first)[0].proposal);
  });

  test('the backend not having it any more ends the card without calling it dismissed', () => {
    const state = run(first, { type: 'reject-started', id }, { type: 'proposal-gone', id });

    expect(phaseOf(state, id)).toEqual({ kind: 'expired' });
  });

  test('after a failure that can be tried again, dismissing goes through the same start and end', () => {
    const state = run(
      first,
      { type: 'reject-started', id },
      { type: 'reject-failed', id, failure: RETRYABLE },
      { type: 'reject-started', id },
      { type: 'reject-succeeded', id },
    );

    expect(phaseOf(state, id)).toEqual({ kind: 'rejected' });
  });

  test('a dismissed workout stays dismissed when a newer one arrives, and is not ended again', () => {
    const dismissed = run(first, { type: 'reject-started', id }, { type: 'reject-succeeded', id });

    const state = answered(dismissed, 2);

    expect(proposals(state)[0].phase).toEqual({ kind: 'rejected' });
  });

  test('a workout whose dismissal failed, and can be tried again, is still waiting: a newer one ends it', () => {
    const failed = run(first, { type: 'reject-started', id }, { type: 'reject-failed', id, failure: RETRYABLE });

    const state = answered(failed, 2);

    expect(proposals(state)[0].phase).toEqual({ kind: 'superseded', reason: 'newer-version' });
  });

  test('no suggestions while it is being dismissed, and none for a card that cannot be changed any more', () => {
    const offered = (state: ChatState) => suggestionsFor(state, REFINEMENT_SUGGESTIONS);

    expect(offered(run(first, { type: 'reject-started', id }))).toEqual([]);
    expect(offered(run(first, { type: 'reject-started', id }, { type: 'reject-succeeded', id }))).toEqual([]);
    expect(offered(run(first, { type: 'reject-started', id }, { type: 'reject-failed', id, failure: RETRYABLE }))).toBe(REFINEMENT_SUGGESTIONS);
  });
});

describe('workouts waiting from before the conversation', () => {
  const waiting = (sequence: number, minutesAgo = 12, scenario: 'new' | 'edit' = 'edit') => mockPendingProposal(scenario, NOW, sequence, minutesAgo);
  const recovered = (state: ChatState, proposals: ReturnType<typeof waiting>[], settled: string[] = []) =>
    run(state, { type: 'recovered', proposals, settled });
  const choices = (state: ChatState) => state.items.filter((item): item is Extract<ChatItem, { kind: 'choice' }> => item.kind === 'choice');

  test('none leaves the conversation exactly as it was', () => {
    expect(recovered(opening, [])).toBe(opening);
  });

  test('one is shown as its card, ready, after a line that says it was proposed earlier, which is not sent to the coach', () => {
    const state = recovered(opening, [waiting(1)]);

    const [line, card] = state.items.slice(-2);
    expect(line).toMatchObject({ kind: 'message', role: 'assistant', inHistory: false });
    expect(line.kind === 'message' && line.text).toMatch(/waiting for your approval.*proposed earlier/);
    expect(card).toMatchObject({ kind: 'proposal', phase: { kind: 'ready' }, recovered: { createdAt: waiting(1).created_at } });
    expect(historyFrom(state.items)).toEqual(historyFrom(opening.items));
    // the card is the proposal, without the time it was made
    expect(card.kind === 'proposal' && card.proposal).toMatchObject({ proposal_id: waiting(1).proposal_id, binding: waiting(1).binding });
    expect(card.kind === 'proposal' && card.proposal).not.toHaveProperty('created_at');
  });

  test('several are listed to choose from, newest first as the backend gave them, and none is chosen', () => {
    const state = recovered(opening, [waiting(2, 5, 'new'), waiting(1, 12)]);

    expect(proposals(state)).toEqual([]);
    expect(choices(state)).toHaveLength(1);
    expect(choices(state)[0].entries.map((entry) => entry.proposal_id)).toEqual([waiting(2).proposal_id, waiting(1).proposal_id]);
  });

  test('choosing one puts its card in the conversation, leaves the rest listed, and removes the list when it is empty', () => {
    const listed = recovered(opening, [waiting(2, 5, 'new'), waiting(1, 12)]);

    const one = run(listed, { type: 'review', proposalId: waiting(1).proposal_id });
    expect(proposals(one).map((card) => card.proposal.proposal_id)).toEqual([waiting(1).proposal_id]);
    expect(proposals(one)[0]).toMatchObject({ phase: { kind: 'ready' }, recovered: { createdAt: waiting(1).created_at } });
    expect(choices(one)[0].entries.map((entry) => entry.proposal_id)).toEqual([waiting(2).proposal_id]);

    const both = run(one, { type: 'review', proposalId: waiting(2).proposal_id });
    expect(proposals(both)).toHaveLength(2);
    expect(choices(both)).toEqual([]);
  });

  test('choosing one that is not listed changes nothing', () => {
    const listed = recovered(opening, [waiting(2, 5, 'new'), waiting(1, 12)]);

    expect(run(listed, { type: 'review', proposalId: 'f'.repeat(32) })).toBe(listed);
  });

  test('applies, dismisses or chooses nothing by itself: every card it adds is ready, and the list holds proposals only', () => {
    const state = recovered(opening, [waiting(2, 5, 'new'), waiting(1, 12)]);

    expect(isApplying(state) || isRejecting(state)).toBe(false);
    expect(state.items.every((item) => item.kind !== 'proposal')).toBe(true);
  });

  test('a proposal the conversation already has a card for, in any state, is never added again', () => {
    const mine = answered(opening, 1);
    const [{ id }] = proposals(mine);
    const states = [
      mine,
      run(mine, { type: 'apply-started', id }, { type: 'apply-succeeded', id, plan: CONFIRMED(100) }),
      run(mine, { type: 'reject-started', id }, { type: 'reject-succeeded', id }),
      run(mine, { type: 'reject-started', id }, { type: 'proposal-gone', id }),
      answered(mine, 2),
    ];

    for (const state of states) {
      expect(recovered(state, [{ ...edit(1), created_at: NOW.toISOString() }])).toEqual(state);
    }
  });

  test('a proposal this app applied or dismissed is not offered again, even to a conversation that started over', () => {
    const state = recovered(opening, [waiting(1)], [waiting(1).proposal_id]);

    expect(state).toEqual(opening);
  });

  test('the other waiting ones are still offered when one is settled', () => {
    const state = recovered(opening, [waiting(2, 5, 'new'), waiting(1, 12)], [waiting(1).proposal_id]);

    expect(proposals(state).map((card) => card.proposal.proposal_id)).toEqual([waiting(2).proposal_id]);
  });

  test('the list is refreshed from the backend: what it no longer lists is no longer offered, and nothing is listed twice', () => {
    const listed = recovered(opening, [waiting(3, 2, 'new'), waiting(2, 5, 'new'), waiting(1, 12)]);

    const again = recovered(listed, [waiting(3, 2, 'new'), waiting(1, 12)]);

    expect(choices(again)).toHaveLength(1);
    expect(choices(again)[0].entries.map((entry) => entry.proposal_id)).toEqual([waiting(3).proposal_id, waiting(1).proposal_id]);
    expect(recovered(again, [waiting(3, 2, 'new'), waiting(1, 12)])).toEqual(again);
  });

  test('a refresh that finds none removes the list', () => {
    const listed = recovered(opening, [waiting(2, 5, 'new'), waiting(1, 12)]);

    expect(choices(recovered(listed, []))).toEqual([]);
  });

  test('a refresh does not list what already has a card, and a card already shown is not shown twice', () => {
    const shown = recovered(opening, [waiting(1)]);

    expect(recovered(shown, [waiting(1)])).toEqual(shown);
    expect(proposals(recovered(shown, [waiting(1)]))).toHaveLength(1);
  });

  test('what arrives while the coach is still answering goes before the question it is answering, so the answer lands under it', () => {
    const asking = asked(opening, 'hello');

    const state = recovered(asking, [waiting(1)]);

    expect(state.items.slice(-4).map((item) => item.kind)).toEqual(['message', 'proposal', 'message', 'pending']);
    expect(state.items.at(-2)).toMatchObject({ kind: 'message', role: 'user', text: 'hello' });
    // and the coach's answer still replaces what was pending
    const answeredAfter = run(state, { type: 'reply', reply: 'Hi', proposal: null });
    expect(answeredAfter.items.at(-1)).toMatchObject({ kind: 'message', role: 'assistant', text: 'Hi' });
    expect(isWaiting(answeredAfter)).toBe(false);
  });

  test('a failure to look is kept until a look succeeds, and is never taken for none', () => {
    const failed = run(opening, { type: 'recovery-failed', failure: RETRYABLE });

    expect(failed.recoveryFailure).toEqual(RETRYABLE);
    expect(failed.items).toEqual(opening.items);
    expect(recovered(failed, []).recoveryFailure).toBeNull();
    expect(recovered(failed, [waiting(1)]).recoveryFailure).toBeNull();
  });

  test('starting over forgets a failure to look', () => {
    const failed = run(opening, { type: 'recovery-failed', failure: RETRYABLE });

    expect(run(failed, { type: 'reset', to: opening }).recoveryFailure).toBeNull();
  });

  test('applying a revision of a workout removes the listed ones that revise the same workout: the backend cancelled it', () => {
    const mine = answered(opening, 1);
    const [{ id }] = proposals(mine);
    const listed = recovered(mine, [waiting(3, 2, 'new'), { ...waiting(2, 5), proposal_id: 'e'.repeat(32) }, { ...waiting(4, 7), proposal_id: 'f'.repeat(32) }]);
    expect(choices(listed)[0].entries).toHaveLength(3);

    const state = run(listed, { type: 'apply-started', id }, { type: 'apply-succeeded', id, plan: CONFIRMED(100) });

    // only the new workout, which replaces nothing, is still offered
    expect(choices(state)[0].entries.map((entry) => entry.proposal_id)).toEqual([waiting(3).proposal_id]);
  });

  test('and the whole list when all of them revised it', () => {
    const mine = answered(opening, 1);
    const [{ id }] = proposals(mine);
    const listed = recovered(mine, [
      { ...waiting(2, 5), proposal_id: 'e'.repeat(32) },
      { ...waiting(4, 7), proposal_id: 'f'.repeat(32) },
    ]);

    const state = run(listed, { type: 'apply-started', id }, { type: 'apply-succeeded', id, plan: CONFIRMED(100) });

    expect(choices(state)).toEqual([]);
  });
});

describe('asking for more changes: only the newest waiting workout can be changed', () => {
  // made 5 minutes ago unless said: the ones that matter here are told apart by when they were made
  const waiting = (sequence: number, minutesAgo = 5, scenario: 'new' | 'edit' = 'new') => mockPendingProposal(scenario, NOW, sequence, minutesAgo);
  const recovered = (state: ChatState, list: ReturnType<typeof waiting>[]) => run(state, { type: 'recovered', proposals: list, settled: [] });
  const cardOf = (state: ChatState, proposalId: string) => proposals(state).find((card) => card.proposal.proposal_id === proposalId)!;

  test('a proposal the coach just made is the newest', () => {
    const state = answered(opening, 1);

    expect(canAskForChanges(state.items, proposals(state)[0])).toBe(true);
    expect(newestWaiting(state.items)).toEqual({ proposalId: edit(1).proposal_id, name: 'Core Stability & Abs' });
  });

  test('the newest of several recovered can be changed, an older one cannot', () => {
    const listed = recovered(opening, [waiting(2, 5), waiting(1, 12)]);
    const both = run(listed, { type: 'review', proposalId: waiting(1).proposal_id }, { type: 'review', proposalId: waiting(2).proposal_id });

    expect(canAskForChanges(both.items, cardOf(both, waiting(2).proposal_id))).toBe(true);
    expect(canAskForChanges(both.items, cardOf(both, waiting(1).proposal_id))).toBe(false);
  });

  test('an older one cannot be changed while a newer one is still only listed, which has not been looked at', () => {
    const listed = recovered(opening, [waiting(2, 5), waiting(1, 12)]);
    const older = run(listed, { type: 'review', proposalId: waiting(1).proposal_id });

    expect(canAskForChanges(older.items, cardOf(older, waiting(1).proposal_id))).toBe(false);
    expect(newestWaiting(older.items)).toEqual({ proposalId: waiting(2).proposal_id, name: waiting(2).name });
  });

  test('a newer one that is dismissed no longer stands in the way: the older one is then the newest waiting', () => {
    const listed = recovered(opening, [waiting(2, 5), waiting(1, 12)]);
    const both = run(listed, { type: 'review', proposalId: waiting(1).proposal_id }, { type: 'review', proposalId: waiting(2).proposal_id });
    const newer = cardOf(both, waiting(2).proposal_id);

    const state = run(both, { type: 'reject-started', id: newer.id }, { type: 'reject-succeeded', id: newer.id });

    expect(canAskForChanges(state.items, cardOf(state, waiting(1).proposal_id))).toBe(true);
  });

  test('a card that cannot be applied cannot be changed either', () => {
    const state = answered(opening, 1);
    const [{ id }] = proposals(state);
    const applied = run(state, { type: 'apply-started', id }, { type: 'apply-succeeded', id, plan: CONFIRMED(100) });

    expect(canAskForChanges(applied.items, proposals(applied)[0])).toBe(false);
    expect(newestWaiting(applied.items)).toBeNull();
  });

  test('refinements are offered only on the last card when it can be changed: not on a recovered older one', () => {
    const listed = recovered(opening, [waiting(2, 5), waiting(1, 12)]);
    const older = run(listed, { type: 'review', proposalId: waiting(1).proposal_id });
    const newest = run(older, { type: 'review', proposalId: waiting(2).proposal_id });

    expect(suggestionsFor(older, REFINEMENT_SUGGESTIONS)).toEqual([]);
    expect(suggestionsFor(newest, REFINEMENT_SUGGESTIONS)).toBe(REFINEMENT_SUGGESTIONS);
  });

  test('the opening replies stay while only a list of waiting workouts has been added: the person has said nothing yet', () => {
    const listed = recovered(opening, [waiting(2, 5), waiting(1, 12)]);

    expect(suggestionsFor(listed, REFINEMENT_SUGGESTIONS)).toBe(MOCK_OPENING.suggestions);
  });
});
