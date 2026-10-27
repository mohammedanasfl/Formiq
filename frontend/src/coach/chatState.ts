import type { CoachHistoryTurn, PendingProposal, WorkoutPlan, WorkoutProposal } from '../api';
import type { CoachContext } from '../shell/routes';
import type { ApplyFailure } from './coachErrors';
import type { SuggestedReply } from './types';

// The conversation on the AI Coach screen as plain data, and the rules that move it on. Kept apart from React so
// each rule of a workout's life (proposed, applying, applied, dismissed, failed, replaced by a newer one, recovered
// after the screen was left) is tested without a screen.

// Where a proposed workout stands. Only the backend saves it or dismisses it: `applied` is reached only from a
// successful approval and `rejected` only from a successful rejection, and a proposal that was only shown is never
// anything but `ready`, `applying`, `apply-failed`, `rejecting`, `reject-failed` or `superseded`.
export type ProposalPhase =
  | { kind: 'ready' }
  | { kind: 'applying' }
  // the backend confirmed it: the plan it saved, as the backend answered (its id, name and day)
  | { kind: 'applied'; planId: number; name: string; scheduledDate: string | null }
  // `retryable`: pressing apply again can help (a lost connection); otherwise the proposal itself is the problem
  | { kind: 'apply-failed'; failure: ApplyFailure }
  | { kind: 'rejecting' }
  // the backend confirmed it: this proposal is no longer offered and nothing was saved
  | { kind: 'rejected' }
  // dismissing it failed: `retryable` means it still waits, and can be applied or dismissed again; otherwise the
  // backend said it can no longer be dismissed (it was applied, or changed), and nothing more is offered
  | { kind: 'reject-failed'; failure: ApplyFailure }
  // the backend does not have it waiting any more (it expired and was cleared): nothing more is offered
  | { kind: 'expired' }
  // it can no longer be applied from here: the coach made a newer version, or another one replaced the same workout
  | { kind: 'superseded'; reason: 'newer-version' | 'workout-replaced' };

export type ChatItem =
  // `inHistory: false` marks a line the app wrote itself (the opening greeting): it is shown, but it is not sent to
  // the coach as something said in the conversation
  | { kind: 'message'; id: string; role: 'assistant' | 'user'; text: string; inHistory?: boolean }
  // `recovered` is set for a proposal the app fetched from the backend after the conversation it was made in was gone
  // (the screen was opened again, or started over): when it was made, so the card can say it is an earlier one
  | { kind: 'proposal'; id: string; proposal: WorkoutProposal; phase: ProposalPhase; recovered: { createdAt: string } | null }
  // Several proposals are waiting and none was made in this conversation: they are listed for the person to choose
  // from. Nothing is chosen for them; each stays waiting on the backend until it is applied or dismissed.
  | { kind: 'choice'; id: string; entries: PendingProposal[] }
  // waiting for the coach; `expectsWorkout`: the request was for a workout (see SuggestedReply)
  | { kind: 'pending'; id: string; expectsWorkout: boolean }
  // the coach could not answer; `retryable`: asking again can help (not when the session has expired)
  | { kind: 'failed'; id: string; message: string; retryable: boolean; expectsWorkout: boolean };

// What a conversation opens with, and the replies it offers before the user has said anything.
export type ChatOpening = {
  items: readonly ChatItem[];
  suggestions: readonly SuggestedReply[];
};

// The saved workout the conversation is about: sent with every message, so the backend lets the coach revise it and
// nothing else, and reads only the proposals that revise it. It starts as the workout the screen was opened from; it
// moves to the saved plan when a revision of it is applied (the original is then cancelled, and a later change must be
// to the plan that replaced it); and, in a conversation opened from no workout, it is the plan a card replaces once the
// person asks for changes to that card (bindTarget). It is never worked out from which card is visible, and it is
// never remembered by the app: after a restart or a new sign-in the conversation has none until they ask again.
export type ChatTarget = { planId: number; title: string };

export type ChatState = {
  items: ChatItem[];
  nextId: number;
  // the replies offered until the user says something, and how many items the conversation opened with
  suggestions: readonly SuggestedReply[];
  openingLength: number;
  // the workout the conversation was opened from ("Edit with AI"), if it was
  launch: CoachContext | null;
  // the saved workout the conversation is about, if there is one: only a saved plan (a numeric id) can be
  target: ChatTarget | null;
  // why the last look for waiting proposals failed, until one succeeds
  recoveryFailure: ApplyFailure | null;
};

export type ChatAction =
  // `about`: the card the message is about, when it is a way of changing it (a suggested change, or after "Ask for More
  // Changes"): the conversation is then about the saved workout that card replaces (see bindTarget)
  | { type: 'user-sent'; text: string; expectsWorkout: boolean; about?: string }
  | { type: 'reply'; reply: string; proposal: WorkoutProposal | null }
  | { type: 'request-failed'; message: string; retryable?: boolean }
  | { type: 'retry' }
  | { type: 'apply-started'; id: string }
  | { type: 'apply-succeeded'; id: string; plan: Pick<WorkoutPlan, 'id' | 'name' | 'scheduled_date'> }
  | { type: 'apply-failed'; id: string; failure: ApplyFailure }
  | { type: 'reject-started'; id: string }
  | { type: 'reject-succeeded'; id: string }
  | { type: 'reject-failed'; id: string; failure: ApplyFailure }
  | { type: 'proposal-gone'; id: string }
  // the backend's list of proposals waiting for the person; `settled` are ones this app already applied or dismissed
  | { type: 'recovered'; proposals: readonly PendingProposal[]; settled: readonly string[] }
  | { type: 'recovery-failed'; failure: ApplyFailure }
  // the person chose one of the listed proposals to look at
  | { type: 'review'; proposalId: string }
  // the person pressed "Ask for More Changes" on a card: what they say next is about it
  | { type: 'refine'; id: string }
  | { type: 'reset'; to: ChatState };

const targetOf = (launch: CoachContext | null): ChatTarget | null =>
  launch && typeof launch.workoutId === 'number' ? { planId: launch.workoutId, title: launch.title } : null;

export function initialChatState(opening: ChatOpening, launch: CoachContext | null = null): ChatState {
  return {
    items: [...opening.items],
    nextId: opening.items.length + 1,
    suggestions: opening.suggestions,
    openingLength: opening.items.length,
    launch,
    target: targetOf(launch),
    recoveryFailure: null,
  };
}

// A proposal still waiting on the backend as far as the screen knows: it can be told by what the backend says next.
const live = (phase: ProposalPhase) =>
  phase.kind === 'ready' || phase.kind === 'apply-failed' || phase.kind === 'reject-failed';

// A proposal that can still be applied or dismissed from the screen: shown and not used up, not replaced, not mid-way.
export const isApplicable = (phase: ProposalPhase) =>
  phase.kind === 'ready' ||
  ((phase.kind === 'apply-failed' || phase.kind === 'reject-failed') && phase.failure.retryable);

type ProposalItem = Extract<ChatItem, { kind: 'proposal' }>;

// Where something that arrives later than the conversation moved on goes: at the end, or just before the message
// the coach is still answering (and the dots for it), so that the answer lands under its own question.
function insertionPoint(items: readonly ChatItem[]): number {
  const waiting = items.findIndex((item) => item.kind === 'pending');
  if (waiting < 0) return items.length;
  const asked = waiting > 0 ? items[waiting - 1] : null;
  return asked?.kind === 'message' && asked.role === 'user' ? waiting - 1 : waiting;
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  const { items } = state;
  switch (action.type) {
    case 'reset':
      return action.to;

    case 'user-sent':
      return {
        ...state,
        target: bindTarget(state, action.about),
        items: [
          // asking something new leaves an earlier failure in the conversation, but only the latest can be asked again:
          // "Try Again" repeats the last request, never an older one
          ...items.map((item) => (item.kind === 'failed' && item.retryable ? { ...item, retryable: false } : item)),
          { kind: 'message', id: `m${state.nextId}`, role: 'user', text: action.text },
          { kind: 'pending', id: `m${state.nextId + 1}`, expectsWorkout: action.expectsWorkout },
        ],
        nextId: state.nextId + 2,
      };

    case 'reply': {
      const at = items.findIndex((item) => item.kind === 'pending');
      // nobody is waiting for it (the conversation started over): it is dropped
      if (at < 0) return state;
      let nextId = state.nextId;
      // a card with no words of the coach's is just the card: an empty bubble would say nothing
      const arrived: ChatItem[] = action.reply.trim()
        ? [{ kind: 'message', id: `m${nextId++}`, role: 'assistant', text: action.reply }]
        : [];
      if (action.proposal) {
        arrived.push({ kind: 'proposal', id: `m${nextId++}`, proposal: action.proposal, phase: { kind: 'ready' }, recovered: null });
      }
      // A newer proposal ends the older versions of the same workout: the card shown last is the one to apply. A waiting
      // proposal for another saved plan, or a new workout beside a revision, is not an older version of it: the backend
      // still has it waiting, and the person may apply it.
      const newer = action.proposal;
      const before = newer
        ? items.slice(0, at).map((item) =>
            item.kind === 'proposal' && live(item.phase) && sameWorkout(item.proposal, newer)
              ? { ...item, phase: { kind: 'superseded', reason: 'newer-version' } as const }
              : item,
          )
        : items.slice(0, at);
      return { ...state, items: [...before, ...arrived, ...items.slice(at + 1)], nextId };
    }

    case 'request-failed': {
      const at = items.findIndex((item) => item.kind === 'pending');
      if (at < 0) return state;
      const pending = items[at] as Extract<ChatItem, { kind: 'pending' }>;
      const failed: ChatItem = {
        kind: 'failed',
        id: pending.id,
        message: action.message,
        retryable: action.retryable ?? true,
        expectsWorkout: pending.expectsWorkout,
      };
      return { ...state, items: items.map((item, index) => (index === at ? failed : item)) };
    }

    case 'retry': {
      // only the latest request can be asked again: an older failure stays where it was, whatever came before it
      const at = lastRetryable(items);
      if (at < 0) return state;
      const failed = items[at] as Extract<ChatItem, { kind: 'failed' }>;
      const pending: ChatItem = { kind: 'pending', id: failed.id, expectsWorkout: failed.expectsWorkout };
      return { ...state, items: items.map((item, index) => (index === at ? pending : item)) };
    }

    case 'apply-started':
      return withPhase(state, action.id, { kind: 'applying' });

    case 'apply-failed':
      return withPhase(state, action.id, { kind: 'apply-failed', failure: action.failure });

    case 'apply-succeeded': {
      const done = items.find((item) => item.id === action.id);
      const replaced = done?.kind === 'proposal' ? (done.proposal.revision?.replaces_plan_id ?? null) : null;
      return {
        ...state,
        // The workout this conversation is about has just been replaced by the plan the backend saved: the next change
        // is to that plan, not to the cancelled one (which the backend would now refuse).
        target:
          replaced !== null && state.target?.planId === replaced
            ? { planId: action.plan.id, title: action.plan.name }
            : state.target,
        items: items.flatMap((item): ChatItem[] => {
          if (item.id === action.id) {
            const { id, name, scheduled_date } = action.plan;
            return [{ ...item, phase: { kind: 'applied', planId: id, name, scheduledDate: scheduled_date } } as ChatItem];
          }
          // another proposal for the workout that has just been replaced would be refused by the backend: it
          // cancelled that workout, so it is ended here instead of left to fail
          if (item.kind === 'proposal' && replaced !== null && item.proposal.revision?.replaces_plan_id === replaced && live(item.phase)) {
            return [{ ...item, phase: { kind: 'superseded', reason: 'workout-replaced' } } as ChatItem];
          }
          // and one waiting in the list of choices is no longer offered either
          if (item.kind === 'choice' && replaced !== null) {
            const entries = item.entries.filter((entry) => entry.revision?.replaces_plan_id !== replaced);
            return entries.length === 0 ? [] : [{ ...item, entries }];
          }
          return [item];
        }),
      };
    }

    case 'reject-started':
      return withPhase(state, action.id, { kind: 'rejecting' });

    case 'reject-succeeded':
      return withPhase(state, action.id, { kind: 'rejected' });

    case 'reject-failed':
      return withPhase(state, action.id, { kind: 'reject-failed', failure: action.failure });

    case 'proposal-gone':
      return withPhase(state, action.id, { kind: 'expired' });

    case 'recovered': {
      // what the screen already shows a card for (in any state) is never added again, nor what this app applied or
      // dismissed; the backend's list is the truth about the rest
      const shown = new Set([
        ...items.flatMap((item) => (item.kind === 'proposal' ? [item.proposal.proposal_id] : [])),
        ...action.settled,
      ]);
      const fresh = action.proposals.filter((proposal) => !shown.has(proposal.proposal_id));
      const listed = items.findIndex((item) => item.kind === 'choice');
      if (listed >= 0) {
        // the list is refreshed from the backend: what is no longer waiting there is no longer offered
        const next = items.flatMap((item): ChatItem[] =>
          item.kind !== 'choice' ? [item] : fresh.length === 0 ? [] : [{ ...item, entries: fresh }],
        );
        return { ...state, items: next, recoveryFailure: null };
      }
      if (fresh.length === 0) return state.recoveryFailure === null ? state : { ...state, recoveryFailure: null };
      const at = insertionPoint(items);
      let nextId = state.nextId;
      const arrived: ChatItem[] =
        fresh.length === 1
          ? [
              {
                kind: 'message',
                id: `m${nextId++}`,
                role: 'assistant',
                text: 'You have a workout waiting for your approval. It was proposed earlier: look it over before you apply it.',
                inHistory: false,
              },
              recoveredCard(`m${nextId++}`, fresh[0]),
            ]
          : [{ kind: 'choice', id: `m${nextId++}`, entries: fresh }];
      return { ...state, items: [...items.slice(0, at), ...arrived, ...items.slice(at)], nextId, recoveryFailure: null };
    }

    case 'recovery-failed':
      return { ...state, recoveryFailure: action.failure };

    case 'refine': {
      const target = bindTarget(state, action.id);
      return target === state.target ? state : { ...state, target };
    }

    case 'review': {
      const chosen = items.flatMap((item) => (item.kind === 'choice' ? item.entries : [])).find((entry) => entry.proposal_id === action.proposalId);
      if (!chosen) return state;
      // it leaves the list, and the list goes when it is empty
      const remaining = items.flatMap((item): ChatItem[] => {
        if (item.kind !== 'choice') return [item];
        const entries = item.entries.filter((entry) => entry.proposal_id !== action.proposalId);
        return entries.length === 0 ? [] : [{ ...item, entries }];
      });
      const at = insertionPoint(remaining);
      const card = recoveredCard(`m${state.nextId}`, chosen);
      return { ...state, items: [...remaining.slice(0, at), card, ...remaining.slice(at)], nextId: state.nextId + 1 };
    }
  }
}

function recoveredCard(id: string, pending: PendingProposal): ProposalItem {
  const { created_at: createdAt, ...proposal } = pending;
  return { kind: 'proposal', id, proposal, phase: { kind: 'ready' }, recovered: { createdAt } };
}

// A card the backend confirmed applied stays applied: no late answer (a dismissal, an expiry, a failure) turns it into
// anything else, so a saved workout is never drawn as dismissed or failed.
function withPhase(state: ChatState, id: string, phase: ProposalPhase): ChatState {
  return {
    ...state,
    items: state.items.map((item) =>
      item.kind === 'proposal' && item.id === id && item.phase.kind !== 'applied' ? { ...item, phase } : item,
    ),
  };
}

function lastRetryable(items: readonly ChatItem[]): number {
  for (let at = items.length - 1; at >= 0; at -= 1) {
    const item = items[at];
    if (item.kind === 'failed' && item.retryable) return at;
  }
  return -1;
}

// What a proposal is a version of: the saved plan it would replace, or null for a new workout. Revisions of one plan are
// versions of one workout, and so are new workouts among themselves; a new workout and a revision, or revisions of two
// plans, are not.
const lineage = (proposal: WorkoutProposal): number | null => proposal.revision?.replaces_plan_id ?? null;
const sameWorkout = (a: WorkoutProposal, b: WorkoutProposal) => lineage(a) === lineage(b);

export const isWaiting = (state: ChatState) => state.items.some((item) => item.kind === 'pending');
export const isApplying = (state: ChatState) =>
  state.items.some((item) => item.kind === 'proposal' && item.phase.kind === 'applying');
export const isRejecting = (state: ChatState) =>
  state.items.some((item) => item.kind === 'proposal' && item.phase.kind === 'rejecting');

// What the coach changes when the person asks for more changes. The backend reads the newest proposal waiting for the
// plan the request names (the conversation's target), or, when the request names none, the newest of all. So a card for
// a saved plan can be changed once the conversation is bound to that plan (bindTarget), when no newer proposal waits for
// the same plan; a card for a new workout, which nothing binds the coach to, only when nothing newer waits at all; and,
// in a conversation about a saved plan, only a revision of that plan: any other card can only be applied or dismissed.
// A proposal is made to expire 30 minutes after it was made, so the one that expires last is the newest.
export type NewestWaiting = { proposalId: string; name: string };

function waitingProposals(items: readonly ChatItem[]): WorkoutProposal[] {
  return items.flatMap((item) => {
    if (item.kind === 'proposal') return isApplicable(item.phase) ? [item.proposal] : [];
    if (item.kind === 'choice') return item.entries;
    return [];
  });
}

const expiresAt = (proposal: WorkoutProposal) => Date.parse(proposal.expires_at);

// The newest waiting proposal that the card `about` is a version of (any, for a new workout, or when no card is given).
export function newestWaiting(items: readonly ChatItem[], about?: WorkoutProposal): NewestWaiting | null {
  const plan = about === undefined ? null : lineage(about);
  let newest: WorkoutProposal | null = null;
  for (const proposal of waitingProposals(items)) {
    if (plan !== null && lineage(proposal) !== plan) continue;
    if (newest === null || expiresAt(proposal) > expiresAt(newest)) newest = proposal;
  }
  return newest ? { proposalId: newest.proposal_id, name: newest.name } : null;
}

// Whether "Ask for More Changes" works on this card: it can still be applied, it is about what the conversation is about
// (`target`: a saved plan, or none), and no newer proposal waits that the coach would change instead.
export function canAskForChanges(items: readonly ChatItem[], item: ProposalItem, target: ChatTarget | null = null): boolean {
  if (!isApplicable(item.phase)) return false;
  const plan = lineage(item.proposal);
  if (target !== null && plan !== target.planId) return false;
  const expires = expiresAt(item.proposal);
  return waitingProposals(items).every((other) => !(expiresAt(other) > expires && (plan === null || lineage(other) === plan)));
}

// The saved workout a message about this card is about. A conversation that is already about one stays about it. Otherwise
// asking for changes to a card that replaces a saved plan, and that the coach can be asked to change, makes the
// conversation about that plan, so the backend reads that card's proposals and holds the coach to it. Nothing else
// does: not a card being on the screen, not being the newest, not a list of waiting workouts.
export function bindTarget(state: ChatState, cardId: string | undefined): ChatTarget | null {
  if (state.target !== null || cardId === undefined) return state.target;
  const card = state.items.find((item): item is ProposalItem => item.kind === 'proposal' && item.id === cardId);
  const revision = card?.proposal.revision;
  if (!card || !revision || !canAskForChanges(state.items, card, null)) return null;
  return { planId: revision.replaces_plan_id, title: revision.replaces_plan_name };
}

// The most turns a request carries and the longest one (backend/app/schemas/coach.py: MAX_HISTORY_TURNS,
// MAX_HISTORY_TEXT_LENGTH).
export const MAX_HISTORY_TURNS = 50;
export const MAX_HISTORY_TEXT_LENGTH = 8000;

// The earlier turns of the conversation as the coach API takes them: only what was said, as text, the assistant's
// turns as "coach". A card is not text: what the coach said about it is its reply, which is a turn of its own. The
// request carries no proposal and no plan in the history: the coach reads the workout waiting for approval itself,
// and the workout the conversation is about travels in its own field.
export function historyFrom(items: readonly ChatItem[]): CoachHistoryTurn[] {
  return items
    .filter((item): item is Extract<ChatItem, { kind: 'message' }> => item.kind === 'message' && item.inHistory !== false)
    .map((item) => ({
      role: item.role === 'user' ? ('user' as const) : ('coach' as const),
      text: item.text.slice(0, MAX_HISTORY_TEXT_LENGTH),
    }))
    .slice(-MAX_HISTORY_TURNS);
}

// Whether the person has said nothing yet: all that came after the opening is what the app found for them (workouts
// waiting from before, and the line that says so), not anything said or asked in this conversation.
const untouched = (state: ChatState) =>
  state.items
    .slice(state.openingLength)
    .every((item) => item.kind === 'choice' || (item.kind === 'proposal' && item.recovered !== null) || (item.kind === 'message' && item.inHistory === false));

// The card the suggested changes are about: the last one, while nothing is going on and the coach can be asked to change
// it. The replies sent with it are messages about it (bindTarget).
function refinable(state: ChatState): ProposalItem | null {
  if (isWaiting(state) || isApplying(state) || isRejecting(state)) return null;
  const last = state.items[state.items.length - 1];
  return last?.kind === 'proposal' && canAskForChanges(state.items, last, state.target) ? last : null;
}

export const refinedCard = (state: ChatState): string | null => refinable(state)?.id ?? null;

// Which suggested replies to offer: the ones the screen opened with until the user says anything, ways to change
// the workout while the last thing on the screen is one that can be changed, and none otherwise.
export function suggestionsFor(state: ChatState, refinements: readonly SuggestedReply[]): readonly SuggestedReply[] {
  if (isWaiting(state) || isApplying(state) || isRejecting(state)) return [];
  const last = state.items[state.items.length - 1];
  if (last?.kind === 'proposal' && isApplicable(last.phase)) return refinable(state) ? refinements : [];
  return untouched(state) ? state.suggestions : [];
}
