import {
  bindTarget,
  canAskForChanges,
  chatReducer,
  initialChatState,
  newestWaiting,
  refinedCard,
  suggestionsFor,
  type ChatAction,
  type ChatItem,
  type ChatState,
} from '../src/coach/chatState';
import { coachOpening } from '../src/coach/opening';
import { REFINEMENT_SUGGESTIONS } from '../src/coach/suggestions';
import { MOCK_OPENING } from '../src/mock/coachMock';
import { mockPendingProposal } from '../src/mock/coachProposalsMock';
import type { PendingProposal, WorkoutProposal } from '../src/api';

// Phase 2.3. What the conversation is about, which workouts a newer proposal replaces, and which card the coach can be
// asked to change: all of it decided from what the backend says (a proposal's `revision`), never from which card
// happens to be the last one on the screen.

const NOW = new Date(2026, 9, 22, 9, 0, 0);
const run = (state: ChatState, ...actions: ChatAction[]) => actions.reduce(chatReducer, state);
const opening = initialChatState(MOCK_OPENING);
const cards = (state: ChatState) => state.items.filter((item): item is Extract<ChatItem, { kind: 'proposal' }> => item.kind === 'proposal');
const phases = (state: ChatState) => cards(state).map((card) => card.phase.kind);
const CONFIRMED = (id: number) => ({ id, name: 'Saved', scheduled_date: '2026-10-22' });

// a proposal that revises saved plan `planId`, and one that revises none
const revising = (sequence: number, planId: number, name: string, minutesAgo = 5): PendingProposal => {
  const base = mockPendingProposal('edit', NOW, sequence, minutesAgo);
  return { ...base, revision: { ...base.revision!, replaces_plan_id: planId, replaces_plan_name: name } };
};
const fresh = (sequence: number, minutesAgo = 5): PendingProposal => mockPendingProposal('new', NOW, sequence, minutesAgo);

const recovered = (state: ChatState, list: PendingProposal[]) => run(state, { type: 'recovered', proposals: list, settled: [] });
const cardFor = (state: ChatState, proposal: WorkoutProposal) => cards(state).find((card) => card.proposal.proposal_id === proposal.proposal_id)!;
const asked = (state: ChatState, text = 'hello', about?: string) => run(state, { type: 'user-sent', text, expectsWorkout: false, about });
const coachMade = (state: ChatState, proposal: WorkoutProposal) =>
  run(asked(state, 'a change'), { type: 'reply', reply: 'Here is a workout.', proposal });

describe('Try Again repeats the latest failed request, never an older bubble', () => {
  const twoFailures = () => {
    const first = run(asked(opening, 'first'), { type: 'request-failed', message: 'nope', retryable: true });
    return run(asked(first, 'second'), { type: 'request-failed', message: 'nope again', retryable: true });
  };

  test('with an older failure that can no longer be tried and a newer one that can, the newer one goes back to pending', () => {
    const failed = twoFailures();
    const [older, newer] = failed.items.filter((item): item is Extract<ChatItem, { kind: 'failed' }> => item.kind === 'failed');
    expect(older.retryable).toBe(false);
    expect(newer.retryable).toBe(true);

    const state = run(failed, { type: 'retry' });

    // the older bubble is left as it was; the newer one is the one asked again
    expect(state.items.find((item) => item.id === older.id)).toEqual(older);
    expect(state.items.find((item) => item.id === newer.id)).toMatchObject({ kind: 'pending' });
    expect(state.items.filter((item) => item.kind === 'pending')).toHaveLength(1);
  });

  test("the answer lands under the question that was asked again, not under the older one's", () => {
    const retried = run(twoFailures(), { type: 'retry' });

    const state = run(retried, { type: 'reply', reply: 'the answer to the second', proposal: null });

    const texts = state.items.flatMap((item) => (item.kind === 'message' ? [item.text] : []));
    expect(texts.slice(-2)).toEqual(['second', 'the answer to the second']);
    // and the older failure is still the only failure left
    expect(state.items.filter((item) => item.kind === 'failed')).toHaveLength(1);
  });

  test('with nothing that can be tried again, nothing changes', () => {
    const failed = run(asked(opening, 'x'), { type: 'request-failed', message: 'Log in again.', retryable: false });

    expect(run(failed, { type: 'retry' })).toBe(failed);
  });
});

describe('a newer proposal ends only the older versions of the same workout', () => {
  test('one for the same saved plan ends the older one', () => {
    const state = coachMade(recovered(opening, [revising(1, 41, 'Core')]), revising(2, 41, 'Core'));

    expect(phases(state)).toEqual(['superseded', 'ready']);
  });

  test("one for another saved plan does not: it is not a version of that workout, and the user may still apply it", () => {
    const state = coachMade(recovered(opening, [revising(1, 77, 'Legs')]), revising(2, 41, 'Core'));

    expect(phases(state)).toEqual(['ready', 'ready']);
  });

  test('a revision does not end a waiting new workout, nor a new workout a waiting revision', () => {
    const newWaiting = coachMade(recovered(opening, [fresh(1)]), revising(2, 41, 'Core'));
    const revisionWaiting = coachMade(recovered(opening, [revising(1, 41, 'Core')]), fresh(2));

    expect(phases(newWaiting)).toEqual(['ready', 'ready']);
    expect(phases(revisionWaiting)).toEqual(['ready', 'ready']);
  });

  test('a new workout refined into another new workout is a newer version, as it was', () => {
    const state = coachMade(recovered(opening, [fresh(1)]), fresh(2));

    expect(phases(state)).toEqual(['superseded', 'ready']);
  });

  test('a conversation about plan 41 keeps an unrelated waiting proposal for plan 77 when the coach makes one for 41', () => {
    const about = initialChatState(coachOpening({ workoutId: 41, title: 'Core' }), { workoutId: 41, title: 'Core' });
    const listed = recovered(about, [revising(1, 77, 'Legs'), revising(2, 41, 'Core', 12)]);
    const both = run(
      listed,
      { type: 'review', proposalId: revising(1, 77, 'Legs').proposal_id },
      { type: 'review', proposalId: revising(2, 41, 'Core').proposal_id },
    );
    const state = coachMade(both, revising(3, 41, 'Core', 0));

    // the older version for 41 is ended; the one for 77 is not
    expect(phases(state)).toEqual(['ready', 'superseded', 'ready']);
  });
});

describe('the plan a conversation is about is bound by asking for changes on a card, never by one being visible', () => {
  test('a recovered card, however it came, sets no plan by itself', () => {
    const one = recovered(opening, [revising(1, 41, 'Core')]);
    const several = recovered(opening, [revising(2, 41, 'Core', 5), revising(1, 77, 'Legs', 12)]);
    const reviewed = run(several, { type: 'review', proposalId: revising(2, 41, 'Core').proposal_id });

    expect(one.target).toBeNull();
    expect(several.target).toBeNull();
    expect(reviewed.target).toBeNull();
  });

  test('asking for changes on a recovered revision binds the conversation to the plan it replaces', () => {
    const one = recovered(opening, [revising(1, 41, 'Core')]);

    const state = run(one, { type: 'refine', id: cards(one)[0].id });

    expect(state.target).toEqual({ planId: 41, title: 'Core' });
    expect(bindTarget(one, cards(one)[0].id)).toEqual({ planId: 41, title: 'Core' });
  });

  test('a message sent about a card binds the same way, and one sent about none binds nothing', () => {
    const one = recovered(opening, [revising(1, 41, 'Core')]);

    const about = asked(one, 'Make it more intense', cards(one)[0].id);
    const typed = asked(one, 'Make it more intense');

    expect(about.target).toEqual({ planId: 41, title: 'Core' });
    expect(typed.target).toBeNull();
  });

  test('only the card the person chose from several is bound: not the newest listed', () => {
    const several = recovered(opening, [revising(2, 41, 'Core', 5), revising(1, 77, 'Legs', 12)]);
    const older = run(several, { type: 'review', proposalId: revising(1, 77, 'Legs').proposal_id });

    const state = run(older, { type: 'refine', id: cards(older)[0].id });

    // the plan of the card they looked at, which the backend then reads the proposals of
    expect(state.target).toEqual({ planId: 77, title: 'Legs' });
  });

  test('a card that is not the newest for its plan binds nothing: the coach would change the newer one', () => {
    const two = recovered(opening, [revising(2, 41, 'Core', 5), revising(1, 41, 'Core', 12)]);
    const both = run(
      two,
      { type: 'review', proposalId: revising(1, 41, 'Core').proposal_id },
      { type: 'review', proposalId: revising(2, 41, 'Core').proposal_id },
    );
    const older = cardFor(both, revising(1, 41, 'Core'));

    expect(run(both, { type: 'refine', id: older.id }).target).toBeNull();
    expect(run(both, { type: 'refine', id: cardFor(both, revising(2, 41, 'Core')).id }).target).toEqual({ planId: 41, title: 'Core' });
  });

  test('a new workout binds no plan: it replaces none', () => {
    const one = recovered(opening, [fresh(1)]);

    expect(run(one, { type: 'refine', id: cards(one)[0].id }).target).toBeNull();
  });

  test('a card that cannot be applied any more binds nothing', () => {
    const one = recovered(opening, [revising(1, 41, 'Core')]);
    const { id } = cards(one)[0];
    const dismissed = run(one, { type: 'reject-started', id }, { type: 'reject-succeeded', id });

    expect(run(dismissed, { type: 'refine', id }).target).toBeNull();
  });

  test("a conversation already about a plan is not moved to another by looking at a different plan's card", () => {
    const about = initialChatState(coachOpening({ workoutId: 41, title: 'Core' }), { workoutId: 41, title: 'Core' });
    const other = recovered(about, [revising(1, 77, 'Legs')]);

    const state = run(other, { type: 'refine', id: cards(other)[0].id });

    expect(state.target).toEqual({ planId: 41, title: 'Core' });
    expect(bindTarget(other, cards(other)[0].id)).toEqual({ planId: 41, title: 'Core' });
  });

  test('an id that is not a card binds nothing and changes nothing', () => {
    const one = recovered(opening, [revising(1, 41, 'Core')]);

    expect(run(one, { type: 'refine', id: 'nope' })).toBe(one);
    expect(bindTarget(one, 'nope')).toBeNull();
  });
});

describe('which card the coach can be asked to change', () => {
  test("about plan 41, only a revision of 41: another plan's card, and a new workout, can only be applied or dismissed", () => {
    const about = initialChatState(coachOpening({ workoutId: 41, title: 'Core' }), { workoutId: 41, title: 'Core' });
    const listed = recovered(about, [fresh(3), revising(2, 77, 'Legs'), revising(1, 41, 'Core', 12)]);
    // everything is listed for choosing, so each is looked at
    const all = run(
      listed,
      { type: 'review', proposalId: fresh(3).proposal_id },
      { type: 'review', proposalId: revising(2, 77, 'Legs').proposal_id },
      { type: 'review', proposalId: revising(1, 41, 'Core').proposal_id },
    );

    expect(canAskForChanges(all.items, cardFor(all, fresh(3)), all.target)).toBe(false);
    expect(canAskForChanges(all.items, cardFor(all, revising(2, 77, 'Legs')), all.target)).toBe(false);
    // plan 41's is the newest for 41, whatever is newer for another plan
    expect(canAskForChanges(all.items, cardFor(all, revising(1, 41, 'Core')), all.target)).toBe(true);
  });

  test('with no plan yet, a revision can be changed when no newer proposal waits for the same plan, whatever waits for another', () => {
    const state = recovered(opening, [revising(2, 77, 'Legs', 5), revising(1, 41, 'Core', 12)]);
    const all = run(
      state,
      { type: 'review', proposalId: revising(1, 41, 'Core').proposal_id },
      { type: 'review', proposalId: revising(2, 77, 'Legs').proposal_id },
    );

    // the bound plan makes the coach read this one, so it is not shadowed by the newer card for another plan
    expect(canAskForChanges(all.items, cardFor(all, revising(1, 41, 'Core')), null)).toBe(true);
    expect(canAskForChanges(all.items, cardFor(all, revising(2, 77, 'Legs')), null)).toBe(true);
  });

  test('a new workout can be changed only when nothing newer waits at all: nothing binds the coach to it', () => {
    const state = recovered(opening, [revising(2, 41, 'Core', 5), fresh(1, 12)]);
    const all = run(
      state,
      { type: 'review', proposalId: fresh(1).proposal_id },
      { type: 'review', proposalId: revising(2, 41, 'Core').proposal_id },
    );

    expect(canAskForChanges(all.items, cardFor(all, fresh(1)), null)).toBe(false);
    expect(canAskForChanges(all.items, cardFor(all, revising(2, 41, 'Core')), null)).toBe(true);
  });

  test('the newest waiting workout is named for the card it is asked about: its own plan, or any for a new workout', () => {
    const state = recovered(opening, [revising(3, 77, 'Legs', 2), revising(2, 41, 'Core', 5), revising(1, 41, 'Core', 12)]);

    const olderCore = revising(1, 41, 'Core');
    expect(newestWaiting(state.items, olderCore)).toEqual({ proposalId: revising(2, 41, 'Core').proposal_id, name: revising(2, 41, 'Core').name });
    expect(newestWaiting(state.items, fresh(9))).toEqual({ proposalId: revising(3, 77, 'Legs').proposal_id, name: revising(3, 77, 'Legs').name });
    // no card in mind: the newest of all, as before
    expect(newestWaiting(state.items)).toEqual({ proposalId: revising(3, 77, 'Legs').proposal_id, name: revising(3, 77, 'Legs').name });
  });

  test('the refinements are offered on the last card only when the coach can be asked to change it', () => {
    const about = initialChatState(coachOpening({ workoutId: 41, title: 'Core' }), { workoutId: 41, title: 'Core' });
    const unrelated = recovered(about, [revising(1, 77, 'Legs')]);
    const related = recovered(about, [revising(1, 41, 'Core')]);
    const unbound = recovered(opening, [revising(1, 77, 'Legs')]);

    expect(suggestionsFor(unrelated, REFINEMENT_SUGGESTIONS)).toEqual([]);
    expect(suggestionsFor(related, REFINEMENT_SUGGESTIONS)).toBe(REFINEMENT_SUGGESTIONS);
    expect(suggestionsFor(unbound, REFINEMENT_SUGGESTIONS)).toBe(REFINEMENT_SUGGESTIONS);
  });

  test('refinedCard is the card the refinements are about: the last one, when they are on offer', () => {
    const one = recovered(opening, [revising(1, 41, 'Core')]);
    const about = initialChatState(coachOpening({ workoutId: 41, title: 'Core' }), { workoutId: 41, title: 'Core' });
    const unrelated = recovered(about, [revising(1, 77, 'Legs')]);

    expect(refinedCard(one)).toBe(cards(one)[0].id);
    // not while the coach is answering, nor for a card it cannot change, nor with the opening replies
    expect(refinedCard(asked(one))).toBeNull();
    expect(refinedCard(unrelated)).toBeNull();
    expect(refinedCard(opening)).toBeNull();
  });
});

describe('an applied workout is final', () => {
  test('no late answer turns it into dismissed, expired or failed', () => {
    const state = recovered(opening, [revising(1, 41, 'Core')]);
    const { id } = cards(state)[0];
    const applied = run(state, { type: 'apply-started', id }, { type: 'apply-succeeded', id, plan: CONFIRMED(100) });
    const phase = cards(applied)[0].phase;
    expect(phase.kind).toBe('applied');

    for (const late of [
      { type: 'reject-started', id },
      { type: 'reject-succeeded', id },
      { type: 'reject-failed', id, failure: { message: 'x', retryable: true } },
      { type: 'proposal-gone', id },
      { type: 'apply-started', id },
      { type: 'apply-failed', id, failure: { message: 'x', retryable: true } },
    ] as ChatAction[]) {
      expect(cards(run(applied, late))[0].phase).toEqual(phase);
    }
  });

  test('a dismissed workout is not turned into applied by anything but the backend saying so: apply-succeeded', () => {
    const state = recovered(opening, [revising(1, 41, 'Core')]);
    const { id } = cards(state)[0];
    const dismissed = run(state, { type: 'reject-started', id }, { type: 'reject-succeeded', id });

    expect(cards(dismissed)[0].phase).toEqual({ kind: 'rejected' });
    expect(cards(run(dismissed, { type: 'apply-succeeded', id, plan: CONFIRMED(100) }))[0].phase.kind).toBe('applied');
  });
});
