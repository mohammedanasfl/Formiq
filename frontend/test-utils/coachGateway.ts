import type { CoachReply, PendingProposal, WorkoutPlan } from '../src/api';
import type { CoachGateway, CoachRequest } from '../src/coach/gateway';

// A CoachGateway a test drives by hand: every send, approval and rejection waits until the test settles it, so what
// the screen shows while it waits can be looked at, and the order things finish in is the test's choice. Asking
// which proposals are waiting answers at once from `waiting.list` (an error to reject with, or proposals), unless the
// test holds it (`waiting.hold`) and settles it by hand from `lists`. Nothing here talks to a network.
type Settle<T> = { resolve: (value: T) => void; reject: (error: unknown) => void };

export type FakeGateway = ReturnType<typeof fakeGateway>;

export function fakeGateway() {
  const sends: (Settle<CoachReply> & { request: CoachRequest })[] = [];
  const approvals: (Settle<WorkoutPlan> & { proposalId: string; binding: string })[] = [];
  const rejections: (Settle<void> & { proposalId: string; binding: string })[] = [];
  const lists: Settle<PendingProposal[]>[] = [];
  const waiting: { list: PendingProposal[] | Error; hold: boolean } = { list: [], hold: false };

  const gateway = {
    send: jest.fn(
      (request: CoachRequest) =>
        new Promise<CoachReply>((resolve, reject) => {
          sends.push({ request, resolve, reject });
        }),
    ),
    pending: jest.fn(
      () =>
        new Promise<PendingProposal[]>((resolve, reject) => {
          if (waiting.hold) {
            lists.push({ resolve, reject });
          } else if (waiting.list instanceof Error) {
            reject(waiting.list);
          } else {
            resolve(structuredClone(waiting.list));
          }
        }),
    ),
    approve: jest.fn(
      (proposal: { proposalId: string; binding: string }) =>
        new Promise<WorkoutPlan>((resolve, reject) => {
          approvals.push({ ...proposal, resolve, reject });
        }),
    ),
    reject: jest.fn(
      (proposal: { proposalId: string; binding: string }) =>
        new Promise<void>((resolve, reject) => {
          rejections.push({ ...proposal, resolve, reject });
        }),
    ),
    reset: jest.fn(),
  } satisfies CoachGateway;

  return { gateway, sends, approvals, rejections, lists, waiting };
}
