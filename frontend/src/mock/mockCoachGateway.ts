import { ApiError, type PendingProposal, type WorkoutPlan, type WorkoutProposal } from '../api';
import type { CoachGateway, CoachRequest } from '../coach/gateway';
import {
  MOCK_ALREADY_REPLACED,
  MOCK_LENGTH_QUESTION,
  MOCK_NO_MORE_REVISIONS,
  MOCK_TYPED_REPLIES,
} from './coachMock';
import {
  MOCK_REPLACED_PLAN_ID,
  mockPendingProposal,
  mockProposal,
  mockReplacedPlan,
  mockReplyFor,
  mockSavedPlan,
  type MockScenario,
} from './coachProposalsMock';

// MOCK: a made-up stand-in for the backend, behind the same CoachGateway the real one implements. It calls no
// network and no model. It answers deterministically from the words of the message and from what it has already
// proposed, and it behaves as the backend does where the screen depends on it: a proposal is kept until it is
// approved or rejected (and expires after 30 minutes), approving saves a new PLANNED plan and cancels the one it
// revises, approving it again returns that same plan, a rejected proposal cannot be approved, a proposal cannot be
// rejected once approved, and an approval of a proposal whose plan has since been replaced is refused with the
// backend's own 409. Like the backend's, what it proposed outlives the conversation: only `reset` forgets it.

// How long each answer takes: long enough to see the card loading and applying, short enough not to slow a review.
export const MOCK_REPLY_DELAY_MS = 900;
export const MOCK_PROPOSAL_DELAY_MS = 1500;
export const MOCK_APPLY_DELAY_MS = 1200;
export const MOCK_REJECT_DELAY_MS = 800;
export const MOCK_PENDING_DELAY_MS = 400;

// Switches that make the NEXT request, approval or dismissal fail, once, and that put proposals "waiting from before"
// in the backend's list, so every state can be looked at without breaking anything. They live in the screen's menu
// (MockCoachScreen); a real gateway has nothing like them. `waiting` seeds that many proposals the next time the screen
// asks for those waiting (then goes back to 0): 1 shows one card, 2 the list to choose from.
export type MockSwitches = { failNextRequest: boolean; failNextApply: boolean; failNextReject: boolean; waiting: 0 | 1 | 2 };

export function createMockSwitches(initial: Partial<MockSwitches> = {}) {
  let state: MockSwitches = { failNextRequest: false, failNextApply: false, failNextReject: false, waiting: 0, ...initial };
  const listeners = new Set<() => void>();
  return {
    get: () => state,
    set(patch: Partial<MockSwitches>) {
      state = { ...state, ...patch };
      listeners.forEach((listener) => listener());
    },
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}
export type MockSwitchStore = ReturnType<typeof createMockSwitches>;

const wait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

const REPLACED_MESSAGE =
  'the workout plan this proposal replaces was changed or cancelled since it was proposed: ask the coach for a new one';
const PROPOSAL_TTL_MS = 30 * 60_000;

type Issued = {
  proposal: WorkoutProposal;
  scenario: MockScenario;
  createdAt: Date;
  status: 'PENDING' | 'APPROVED' | 'REJECTED';
  // the plan its approval saved
  saved: WorkoutPlan | null;
};

// The first words that call for each thing. A change to a workout is recognised by the workout waiting, not by words:
// whatever the person says while one waits is a change to it.
const WANTS_AB_WORKOUT = /\b(abs?|core)\b|different (ab|workout)|replace|swap|^keep same duration$/i;
const WANTS_NEW_WORKOUT = /(upper[- ]?body|create|build)/i;
const WANTS_LENGTH = /^try different length$/i;

export function createMockCoachGateway(
  switches: MockSwitchStore = createMockSwitches(),
  now: () => Date = () => new Date(),
): CoachGateway {
  let plans = new Map<number, WorkoutPlan>();
  let issued = new Map<string, Issued>();
  // the proposal waiting for the person, the one a change is a change to
  let waiting: Issued | null = null;
  let sequence = 0;
  let typed = 0;
  let nextPlanId = 100;

  const reset = () => {
    plans = new Map([[MOCK_REPLACED_PLAN_ID, mockReplacedPlan(now())]]);
    issued = new Map();
    waiting = null;
    sequence = 0;
    typed = 0;
    nextPlanId = 100;
  };
  reset();

  const propose = (scenario: MockScenario) => {
    sequence += 1;
    const proposal = mockProposal(scenario, now(), sequence);
    const entry: Issued = { proposal, scenario, createdAt: now(), status: 'PENDING', saved: null };
    issued.set(proposal.proposal_id, entry);
    waiting = entry;
    return { reply: mockReplyFor(scenario), proposal };
  };

  const answer = (message: string) => {
    if (waiting) {
      if (waiting.scenario === 'new') return propose('new-refined');
      if (waiting.scenario === 'edit') return propose('edit-refined');
      return { reply: MOCK_NO_MORE_REVISIONS, proposal: null };
    }
    if (WANTS_LENGTH.test(message.trim())) return { reply: MOCK_LENGTH_QUESTION, proposal: null };
    if (WANTS_AB_WORKOUT.test(message.trim())) {
      return plans.get(MOCK_REPLACED_PLAN_ID)?.status === 'PLANNED'
        ? propose('edit')
        : { reply: MOCK_ALREADY_REPLACED, proposal: null };
    }
    if (WANTS_NEW_WORKOUT.test(message) && /workout/i.test(message)) return propose('new');
    const reply = MOCK_TYPED_REPLIES[typed % MOCK_TYPED_REPLIES.length];
    typed += 1;
    return { reply, proposal: null };
  };

  // Whether the backend would still list it: waiting, not expired, and, for a revision, the plan it replaces still as it
  // was (PLANNED).
  const isWaiting = (entry: Issued) =>
    entry.status === 'PENDING' &&
    now().getTime() < entry.createdAt.getTime() + PROPOSAL_TTL_MS &&
    (!entry.proposal.revision || plans.get(entry.proposal.revision.replaces_plan_id)?.status === 'PLANNED');

  // proposals made earlier, as if the person had been given them before: made 12 and 5 minutes ago. The newest is the
  // one the coach would change if the person asked for a change, as the backend's coach changes the newest waiting one.
  const seed = (count: 1 | 2) => {
    const scenarios: MockScenario[] = count === 1 ? ['edit'] : ['new', 'edit'];
    scenarios.forEach((scenario, index) => {
      sequence += 1;
      const minutesAgo = count === 1 ? 12 : index === 0 ? 12 : 5;
      const seeded = mockPendingProposal(scenario, now(), sequence, minutesAgo);
      const { created_at: createdAt, ...proposal } = seeded;
      const entry: Issued = { proposal, scenario, createdAt: new Date(createdAt), status: 'PENDING', saved: null };
      issued.set(proposal.proposal_id, entry);
      waiting = entry;
    });
  };

  return {
    async send({ message }: CoachRequest) {
      const before = { waiting, typed, sequence };
      const reply = answer(message);
      await wait(reply.proposal ? MOCK_PROPOSAL_DELAY_MS : MOCK_REPLY_DELAY_MS);
      if (switches.get().failNextRequest) {
        switches.set({ failNextRequest: false });
        // the answer was never delivered: it changed nothing, so what it would have used up (a fixed line, a
        // workout waiting for someone) is as it was, and asking again gets the same answer
        if (reply.proposal) issued.delete(reply.proposal.proposal_id);
        ({ waiting, typed, sequence } = before);
        throw new ApiError('network', null, null);
      }
      return reply;
    },

    // The list is the state as it is when asked (the backend reads it then), and arrives after the pause. The most
    // recently made first, as the backend orders it (made at the same moment: the one made last).
    async pending(): Promise<PendingProposal[]> {
      const seeds = switches.get().waiting;
      if (seeds === 1 || seeds === 2) {
        switches.set({ waiting: 0 });
        seed(seeds);
      }
      const list = [...issued.values()]
        .map((entry, order) => ({ entry, order }))
        .filter(({ entry }) => isWaiting(entry))
        .sort((a, b) => b.entry.createdAt.getTime() - a.entry.createdAt.getTime() || b.order - a.order)
        .map(({ entry }) => structuredClone({ ...entry.proposal, created_at: entry.createdAt.toISOString() }));
      await wait(MOCK_PENDING_DELAY_MS);
      return list;
    },

    async approve({ proposalId, binding }) {
      await wait(MOCK_APPLY_DELAY_MS);
      if (switches.get().failNextApply) {
        switches.set({ failNextApply: false });
        throw new ApiError('network', null, null);
      }
      const entry = issued.get(proposalId);
      if (!entry) throw new ApiError('http', 404, `there is no workout plan proposal ${proposalId}`);
      if (binding !== entry.proposal.binding) {
        throw new ApiError('http', 409, 'this approval is for a different version of the proposal than the one proposed');
      }
      // approving again returns the plan the first approval saved (the backend does so as long as the plan is still as
      // saved; nothing in the mock changes a plan it saved)
      if (entry.status === 'APPROVED' && entry.saved) return structuredClone(entry.saved);
      if (entry.status === 'REJECTED') throw new ApiError('http', 409, 'this proposal was rejected: ask the coach for a new one');
      if (now().getTime() >= entry.createdAt.getTime() + PROPOSAL_TTL_MS) {
        throw new ApiError('http', 409, 'this proposal has expired: ask the coach for a new one');
      }
      const replaced = entry.proposal.revision ? plans.get(entry.proposal.revision.replaces_plan_id) : null;
      if (entry.proposal.revision && replaced?.status !== 'PLANNED') throw new ApiError('http', 409, REPLACED_MESSAGE);

      // the new plan is saved and the one it revises is cancelled, together: neither happens alone
      const saved = mockSavedPlan(entry.proposal, nextPlanId);
      nextPlanId += 1;
      plans.set(saved.id, saved);
      if (replaced) plans.set(replaced.id, { ...replaced, status: 'CANCELLED' });
      entry.status = 'APPROVED';
      entry.saved = saved;
      if (waiting === entry) waiting = null;
      return structuredClone(saved);
    },

    async reject({ proposalId, binding }) {
      await wait(MOCK_REJECT_DELAY_MS);
      if (switches.get().failNextReject) {
        switches.set({ failNextReject: false });
        throw new ApiError('network', null, null);
      }
      const entry = issued.get(proposalId);
      if (!entry) throw new ApiError('http', 404, `there is no workout plan proposal ${proposalId}`);
      if (binding !== entry.proposal.binding) {
        throw new ApiError('http', 409, 'this rejection is for a different version of the proposal than the one proposed');
      }
      if (entry.status === 'APPROVED') throw new ApiError('http', 409, 'this proposal was already approved: it cannot be rejected');
      // rejecting again is the same answer
      entry.status = 'REJECTED';
      if (waiting === entry) waiting = null;
    },

    reset,
  };
}
