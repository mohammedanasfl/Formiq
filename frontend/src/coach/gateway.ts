import type { CoachHistoryTurn, CoachReply, PendingProposal, WorkoutPlan } from '../api';

// What the AI Coach screen needs from outside: the four things it asks of Formiq. The screen and its state are
// written against this and nothing else, so the real gateway (src/coach/apiGateway.ts, the backend's) and the
// made-up one of mock mode (src/mock/mockCoachGateway.ts) are interchangeable, and no test or preview needs Gemini
// or a network. Each method says which backend route it stands for (Phase 2.1). Every method rejects with an
// `ApiError` (src/api/client.ts) when it fails.
export type CoachRequest = {
  message: string;
  // the earlier turns of the conversation, oldest first: text only, as the coach API takes them
  history: CoachHistoryTurn[];
  // The saved workout the conversation is about (a plan's id), when it is about one: the backend checks it before it
  // asks the model anything and lets the proposal revise that plan and no other. Left out when there is none.
  workoutPlanId?: number;
};

export interface CoachGateway {
  // POST /coach/message: the coach's reply and, when it proposed a workout, the proposal. Nothing is saved. The
  // proposal carries what it replaces and how it differs (`revision`, `changes`), worked out by the backend.
  send(request: CoachRequest): Promise<CoachReply>;

  // GET /coach/proposals/pending: the proposals that can still be approved, the most recently made first. Only
  // reads: nothing is proposed, applied or dismissed by asking.
  pending(): Promise<PendingProposal[]>;

  // POST /coach/proposals/{proposal_id}/approve: saves the proposal exactly as shown (`binding` is its digest),
  // once, and resolves with the plan that was saved (201; 200 with the same plan when the same user asks again after
  // an answer was lost and the plan is still as saved). A proposal that replaces a plan cancels that plan in the same
  // transaction. The only route that saves a workout.
  approve(proposal: { proposalId: string; binding: string }): Promise<WorkoutPlan>;

  // POST /coach/proposals/{proposal_id}/reject: the person does not want it; it is no longer offered. Resolves once
  // the backend answered 204. Saves nothing and changes no plan.
  reject(proposal: { proposalId: string; binding: string }): Promise<void>;

  // A gateway that remembers a conversation (the mock does) forgets it when the screen starts over.
  reset?(): void;
}
