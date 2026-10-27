import { useCallback, useEffect, useReducer, useRef } from 'react';

import type { WorkoutPlan } from '../api';
import type { CoachContext } from '../shell/routes';
import {
  coachFailure,
  describeApplyFailure,
  describeRecoveryFailure,
  describeRejectFailure,
  EMPTY_ANSWER,
  isAlreadyApplied,
  isGone,
} from './coachErrors';
import {
  bindTarget,
  chatReducer,
  historyFrom,
  initialChatState,
  isApplicable,
  isApplying,
  isRejecting,
  isWaiting,
  refinedCard,
  suggestionsFor,
  type ChatItem,
  type ChatOpening,
  type ChatTarget,
} from './chatState';
import { cleanDraft } from './conversation';
import type { CoachGateway, CoachRequest } from './gateway';
import { REFINEMENT_SUGGESTIONS } from './suggestions';

// What the conversation opens with, and the replies it offers before the user has said anything.
export type CoachOpening = ChatOpening;

// What a conversation opens with, for the workout it was opened from ("Edit with AI") or for none.
export type CoachOpeningFor = (launch: CoachContext | null) => CoachOpening;

type CoachChatOptions = {
  // Called after the backend confirmed a workout was saved, with the plan it answered with: for whatever else on
  // screen shows the user's plans (Home).
  onApplied?: (plan: WorkoutPlan) => void;
  // Whether the screen is on show. Each time it comes on show the backend is asked which proposals are waiting for the
  // person (the shell keeps the screen mounted under the other tabs, so coming back is not a new screen).
  active?: boolean;
};

// The workout a request is about travels in its own field; a conversation about no workout sends none.
const aboutTarget = (target: ChatTarget | null): Pick<CoachRequest, 'workoutPlanId'> =>
  target ? { workoutPlanId: target.planId } : {};

// The conversation on the AI Coach screen: what has been said, the workouts the coach proposed and where each
// stands, and the things the person can do about them: send a message, apply a workout, dismiss one, choose one
// that was waiting from before, start over.
//
// It talks to the coach only through `gateway`, so what answers (the backend's gateway, or the made-up one of
// mock mode) changes nothing here. Rules it keeps:
//   - one request at a time: a message cannot be sent while the coach is answering, or while a workout is being
//     applied or dismissed;
//   - one apply (or one dismissal) at a time, and only a proposal that is still applicable; a second press is
//     ignored, so a workout is never sent for approval or rejection twice from here;
//   - a workout is `applied` only after the gateway says it was saved, and `rejected` only after it says it was
//     dismissed; a failure leaves the proposal as it was (and the workout it would replace is untouched, since only
//     an approval changes it). A dismissal the backend refuses because the workout is already applied (the answer to
//     its approval was lost) asks the approval again, which only returns the saved plan, and shows it applied;
//   - the workout the conversation is about is sent with every message, so the backend lets the coach revise that
//     workout and no other; it is the one the screen was opened from, until a revision of it is applied, and then
//     the plan that replaced it. A conversation opened from no workout (a restart, a new sign-in) is about one once
//     the person asks for changes to a card that replaces it (a suggested change, or "Ask for More Changes"): the
//     plan is then the card's, as the backend gave it, and never one worked out from what is on the screen;
//   - proposals that were waiting before this conversation (the screen was opened again, or started over) are
//     fetched when the screen is shown, never while something else is going on, one request at a time: one is shown
//     as a card, several as a list to choose from, and nothing is applied, dismissed or chosen for the person;
//   - an answer that arrives after the conversation started over, or the screen closed, is dropped;
//   - a conversation opened from a workout keeps that workout for as long as it lasts; opening one from a different
//     workout starts a new conversation, and opening it again from the same one carries on with this.
export function useCoachChat(
  gateway: CoachGateway,
  openingFor: CoachOpeningFor,
  launch: CoachContext | null = null,
  options: CoachChatOptions = {},
) {
  const [state, dispatch] = useReducer(chatReducer, launch, (first) => initialChatState(openingFor(first), first));
  const latest = useRef(state);
  latest.current = state;
  const opening = useRef(openingFor);
  opening.current = openingFor;
  const onApplied = useRef(options.onApplied);
  onApplied.current = options.onApplied;
  const active = options.active ?? true;
  // Bumped when the conversation starts over or the screen goes away: anything still on its way is then stale.
  const epoch = useRef(0);
  // Set at once when work starts, where the state only changes on the next render: a second press in between
  // must not start a second request, a second approval or a second rejection.
  const requesting = useRef(false);
  const applying = useRef(false);
  const rejecting = useRef(false);
  const recovering = useRef(false);
  // the proposals the backend confirmed applied or dismissed through this screen: never offered again, whatever a
  // later list says
  const settled = useRef(new Set<string>());
  const lastRequest = useRef<CoachRequest | null>(null);

  useEffect(
    () => () => {
      epoch.current += 1;
    },
    [],
  );

  const run = useCallback(
    async (request: CoachRequest) => {
      const mine = epoch.current;
      requesting.current = true;
      try {
        const answer = await gateway.send(request);
        if (mine !== epoch.current) return;
        // neither words nor a workout: nothing to show as an answer
        if (!answer.proposal && !answer.reply.trim()) {
          dispatch({ type: 'request-failed', ...EMPTY_ANSWER });
          return;
        }
        dispatch({ type: 'reply', reply: answer.reply, proposal: answer.proposal });
      } catch (error) {
        // a 404 or 409 to a message sent with a workout is about that workout
        if (mine === epoch.current) dispatch({ type: 'request-failed', ...coachFailure(error, request.workoutPlanId !== undefined) });
      } finally {
        if (mine === epoch.current) requesting.current = false;
      }
    },
    [gateway],
  );

  const busy = () => requesting.current || applying.current || rejecting.current;

  // Adds the user's message and asks the coach. Returns whether it was sent: a blank message, or one sent while
  // the coach is answering or a workout is being applied or dismissed, is not.
  // `about` is the card the message is a way of changing (see refined): the conversation is then about the saved
  // workout that card replaces, and the request says so like every later one.
  const send = useCallback(
    (text: string, options: { expectsWorkout?: boolean; about?: string } = {}): boolean => {
      const message = cleanDraft(text);
      if (!message || busy()) return false;
      const request: CoachRequest = {
        message,
        history: historyFrom(latest.current.items),
        ...aboutTarget(bindTarget(latest.current, options.about)),
      };
      lastRequest.current = request;
      dispatch({ type: 'user-sent', text: message, expectsWorkout: options.expectsWorkout === true, about: options.about });
      void run(request);
      return true;
    },
    [run],
  );

  // Asks again after a failure, with the same message: it is not added to the conversation a second time. The workout
  // it is about is the conversation's now, which an apply in between may have moved on.
  const retry = useCallback((): boolean => {
    if (busy() || !lastRequest.current) return false;
    // only a failure that asking again can help: not an expired session
    if (!latest.current.items.some((item) => item.kind === 'failed' && item.retryable)) return false;
    const { workoutPlanId: _earlier, ...same } = lastRequest.current;
    const request: CoachRequest = { ...same, ...aboutTarget(latest.current.target) };
    lastRequest.current = request;
    dispatch({ type: 'retry' });
    void run(request);
    return true;
  }, [run]);

  // The backend saved the workout (it said so): whatever became of the conversation meanwhile, the screen shows it if it
  // is still there, and whatever else on screen shows the user's plans is told (Home), whichever tab is showing.
  const settleApplied = useCallback((item: Extract<ChatItem, { kind: 'proposal' }>, saved: WorkoutPlan, mine: number) => {
    settled.current.add(item.proposal.proposal_id);
    if (mine === epoch.current) dispatch({ type: 'apply-succeeded', id: item.id, plan: saved });
    onApplied.current?.(saved);
  }, []);

  // Sends a proposal for approval. Returns whether it was sent.
  const apply = useCallback(
    async (id: string): Promise<boolean> => {
      const item = latest.current.items.find((entry) => entry.id === id);
      if (!item || item.kind !== 'proposal' || !isApplicable(item.phase)) return false;
      if (busy()) return false;
      const mine = epoch.current;
      applying.current = true;
      dispatch({ type: 'apply-started', id });
      let saved: WorkoutPlan | null = null;
      try {
        saved = await gateway.approve({ proposalId: item.proposal.proposal_id, binding: item.proposal.binding });
      } catch (error) {
        if (mine === epoch.current) dispatch({ type: 'apply-failed', id, failure: describeApplyFailure(error) });
      } finally {
        if (mine === epoch.current) applying.current = false;
      }
      if (saved) settleApplied(item, saved, mine);
      return true;
    },
    [gateway, settleApplied],
  );

  // Dismisses a proposal: the person does not want it. Returns whether it was sent. It is `rejected` only once the
  // backend says so; the backend answering that it is no longer there (it expired) ends the card without claiming
  // it was dismissed.
  const reject = useCallback(
    async (id: string): Promise<boolean> => {
      const item = latest.current.items.find((entry) => entry.id === id);
      if (!item || item.kind !== 'proposal' || !isApplicable(item.phase)) return false;
      if (busy()) return false;
      const mine = epoch.current;
      rejecting.current = true;
      dispatch({ type: 'reject-started', id });
      try {
        await gateway.reject({ proposalId: item.proposal.proposal_id, binding: item.proposal.binding });
        settled.current.add(item.proposal.proposal_id);
        if (mine === epoch.current) dispatch({ type: 'reject-succeeded', id });
      } catch (error) {
        if (isAlreadyApplied(error)) {
          // It was applied, and the answer to that was lost: ask again, which saves nothing and returns the plan it saved
          // (the approval is safe to repeat). Neither "dismissed" nor "couldn't dismiss" is said before that.
          try {
            const saved = await gateway.approve({ proposalId: item.proposal.proposal_id, binding: item.proposal.binding });
            settleApplied(item, saved, mine);
          } catch (confirmation) {
            if (mine === epoch.current) dispatch({ type: 'reject-failed', id, failure: describeApplyFailure(confirmation) });
          }
        } else if (mine === epoch.current) {
          dispatch(isGone(error) ? { type: 'proposal-gone', id } : { type: 'reject-failed', id, failure: describeRejectFailure(error) });
        }
      } finally {
        if (mine === epoch.current) rejecting.current = false;
      }
      return true;
    },
    [gateway, settleApplied],
  );

  // Asks the backend which proposals are waiting for the person, and shows what the conversation does not already
  // show (see the reducer). Not while a message, an approval or a dismissal is under way, and not while it is already
  // asking: it is safe to call as often as the screen likes. Returns whether it asked.
  const recover = useCallback(async (): Promise<boolean> => {
    if (busy() || recovering.current) return false;
    const mine = epoch.current;
    recovering.current = true;
    try {
      const proposals = await gateway.pending();
      if (mine === epoch.current) dispatch({ type: 'recovered', proposals, settled: [...settled.current] });
    } catch (error) {
      if (mine === epoch.current) dispatch({ type: 'recovery-failed', failure: describeRecoveryFailure(error) });
    } finally {
      if (mine === epoch.current) recovering.current = false;
    }
    return true;
  }, [gateway]);

  // The person chose one of the waiting proposals that were listed.
  const review = useCallback((proposalId: string) => dispatch({ type: 'review', proposalId }), []);

  // The person pressed "Ask for More Changes" on a card: what they write next is about it.
  const refine = useCallback((id: string) => dispatch({ type: 'refine', id }), []);

  // Starts a conversation over, for the workout it is opened from or for none. Not while a workout is being
  // applied or dismissed: the request cannot be called back, and the answer would have nowhere to go. Returns whether
  // it started. What was waiting for the person is looked for again, as it is in a conversation that has not begun.
  const restart = useCallback(
    (from: CoachContext | null): boolean => {
      if (applying.current || rejecting.current) return false;
      epoch.current += 1;
      requesting.current = false;
      recovering.current = false;
      lastRequest.current = null;
      gateway.reset?.();
      dispatch({ type: 'reset', to: initialChatState(opening.current(from), from) });
      void recover();
      return true;
    },
    [gateway, recover],
  );

  // "Start over": the conversation the screen opens with when it is opened from no workout.
  const reset = useCallback((): boolean => restart(null), [restart]);

  const waiting = isWaiting(state);
  const applyingNow = isApplying(state);
  const rejectingNow = isRejecting(state);

  // The screen was opened from a workout ("Edit with AI"). A different workout than the conversation is about
  // starts a new conversation; the same one carries on with this one (the saved plan an applied revision of it made
  // counts as the same); no workout (the tab was opened some other way afterwards) changes nothing. If a workout is
  // being applied or dismissed when it arrives, it waits for the answer.
  const seen = useRef(launch);
  useEffect(() => {
    if (launch === seen.current) return;
    const current = latest.current;
    if (launch === null || current.launch?.workoutId === launch.workoutId || current.target?.planId === launch.workoutId) {
      seen.current = launch;
      return;
    }
    if (restart(launch)) seen.current = launch;
  }, [launch, applyingNow, rejectingNow, restart]);

  // The screen is shown (first, or again after another tab): what is waiting for the person is looked for.
  //
  // This effect MUST stay after the one above. Opening the coach from a workout shows the screen and hands it the workout
  // in one render, so both effects run in the same commit: starting the new conversation asks for what is waiting (and
  // makes the answer to any earlier ask stale), and this one, running after it, finds that ask under way and asks nothing
  // more. In the other order this one asked first, the new conversation threw its answer away and asked again: two
  // identical requests for one opening.
  useEffect(() => {
    if (active) void recover();
  }, [active, recover]);

  return {
    items: state.items,
    // the workout this conversation was opened from, if it was
    launch: state.launch,
    // the saved workout it is about now, if it is about one
    target: state.target,
    waiting,
    applying: applyingNow,
    rejecting: rejectingNow,
    // why the last look for waiting proposals failed, until one works
    recoveryFailure: state.recoveryFailure,
    suggestions: suggestionsFor(state, REFINEMENT_SUGGESTIONS),
    // the card the suggested changes are about, when they are on offer: pass it to send as `about`
    refined: refinedCard(state),
    send,
    retry,
    apply,
    reject,
    recover,
    review,
    refine,
    reset,
  };
}
