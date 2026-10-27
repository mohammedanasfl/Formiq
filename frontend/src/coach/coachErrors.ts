import { ApiError, describeError } from '../api';

// The sentences a person reads when the coach cannot answer, a workout cannot be applied or dismissed, or the
// proposals waiting for them cannot be listed. They never claim a workout was applied or dismissed: an approval that
// times out may or may not have been saved, and they say so.

// Whether trying again can help, and what to say. (Dismissing and listing use the same shape.)
export type ApplyFailure = { message: string; retryable: boolean };

const lower = (detail: string | null) => (detail ?? '').toLowerCase();

// POST /coach/proposals/{id}/approve failed. The backend's own 409 reasons are in
// app/services/plan_proposal_service.py: expired, a different version than the one shown, already approved, the
// replaced plan changed or cancelled, no longer saveable. Retrying helps only where nothing about the proposal
// itself is wrong: a lost connection, a slow answer, a server error.
export function describeApplyFailure(error: unknown): ApplyFailure {
  if (!(error instanceof ApiError)) {
    return { message: 'Something went wrong while applying this workout. Try again.', retryable: true };
  }
  if (error.kind === 'network') {
    return { message: "Can't reach Formiq. Check your connection and try again.", retryable: true };
  }
  if (error.kind === 'timeout' || error.kind === 'invalid-response') {
    return {
      message: "Formiq didn't answer in time, so this workout may not have been applied. Try again: Formiq will say if it already was.",
      retryable: true,
    };
  }
  const detail = lower(error.detail);
  switch (error.status) {
    case 401:
      return { message: 'Your session has expired. Log in again.', retryable: false };
    case 404:
      return { message: "Formiq can't find this proposal any more. Ask the coach for a new one.", retryable: false };
    case 409:
      if (detail.includes('expired')) {
        return { message: 'This proposal has expired. Ask the coach for a new one.', retryable: false };
      }
      if (detail.includes('rejected')) {
        return { message: 'This workout was dismissed. Ask the coach for a new one.', retryable: false };
      }
      if (detail.includes('already approved')) {
        return { message: 'This workout was already applied. Check your plans.', retryable: false };
      }
      if (detail.includes('replaces') || detail.includes('changed or cancelled')) {
        return {
          message: 'The workout this would replace has changed since it was proposed. Ask the coach for a new version.',
          retryable: false,
        };
      }
      if (detail.includes('different version')) {
        return { message: 'This proposal changed since it was shown. Ask the coach for a new one.', retryable: false };
      }
      if (detail.includes('no longer be saved')) {
        return {
          message: "This workout can no longer be saved, because Formiq's exercises changed. Ask the coach for a new one.",
          retryable: false,
        };
      }
      return { message: "Formiq couldn't apply this workout. Ask the coach for a new one.", retryable: false };
    case 422:
      return { message: "Formiq couldn't accept this proposal. Ask the coach for a new one.", retryable: false };
    case 503:
      return { message: "Formiq isn't available right now. Try again in a moment.", retryable: true };
    default:
      return error.status !== null && error.status >= 500
        ? { message: "Something went wrong on Formiq's side. Try again.", retryable: true }
        : { message: 'Something went wrong while applying this workout. Try again.', retryable: true };
  }
}

// POST /coach/proposals/{id}/reject failed (coach.py: 401 for a missing or expired token, 404 for a proposal that is
// not found, 409 for one that was approved or whose binding is for another version, 422 for a malformed one). A 404
// is not a failure of the request but the answer that the proposal is not waiting any more: the caller reads it as that
// (`isGone`). Trying again helps only where nothing about the proposal is wrong: a lost connection, a slow answer, a
// server error. Rejecting is idempotent on the backend, so a retry after a lost answer is safe.
export function describeRejectFailure(error: unknown): ApplyFailure {
  if (!(error instanceof ApiError)) {
    return { message: 'Something went wrong while dismissing this workout. Try again.', retryable: true };
  }
  if (error.kind === 'network') {
    return { message: "Can't reach Formiq. Check your connection and try again.", retryable: true };
  }
  if (error.kind === 'timeout' || error.kind === 'invalid-response') {
    return {
      message: "Formiq didn't answer in time, so this workout may not have been dismissed. Try again.",
      retryable: true,
    };
  }
  switch (error.status) {
    case 401:
      return { message: 'Your session has expired. Log in again.', retryable: false };
    case 409:
      return { message: 'This workout was already applied or changed. Check your plans.', retryable: false };
    case 422:
      return { message: "Formiq couldn't dismiss this workout. Ask the coach for a new one.", retryable: false };
    case 503:
      return { message: "Formiq isn't available right now. Try again in a moment.", retryable: true };
    default:
      return error.status !== null && error.status >= 500
        ? { message: "Something went wrong on Formiq's side. Try again.", retryable: true }
        : { message: 'Something went wrong while dismissing this workout. Try again.', retryable: true };
  }
}

// The backend answered that the proposal is not there for this user: it expired and was cleared, or it never was.
export const isGone = (error: unknown): boolean => error instanceof ApiError && error.kind === 'http' && error.status === 404;

// The backend refused to dismiss a proposal because it is already approved (the 409 of app/services/plan_proposal_service.py:
// "this proposal was already approved: it cannot be rejected"): it was applied, as when the answer to the approval was
// lost. A dismissal is never reported as done, or as failed, until the approval has been asked again, which the backend
// answers with the plan that approval saved.
export const isAlreadyApplied = (error: unknown): boolean =>
  error instanceof ApiError && error.kind === 'http' && error.status === 409 && lower(error.detail).includes('already approved');

// GET /coach/proposals/pending failed. The list only reads, so asking again is always safe; it is offered unless the
// problem is the person's session.
export function describeRecoveryFailure(error: unknown): ApplyFailure {
  if (error instanceof ApiError && error.kind === 'http' && error.status === 401) {
    return { message: 'Your session has expired. Log in again.', retryable: false };
  }
  const reason =
    error instanceof ApiError && error.kind === 'network'
      ? "Can't reach Formiq."
      : error instanceof ApiError && error.kind === 'http' && error.status === 503
        ? "Formiq isn't available right now."
        : "Formiq didn't answer.";
  return { message: `${reason} Couldn't check for workouts waiting for your approval.`, retryable: true };
}

// The conversation is about a saved workout and the backend would not use it: this is what the person reads. It is the
// answer to a message sent WITH a workout (a 404: no such plan for this user, a 409: it is not PLANNED any more, as when
// it was replaced or cancelled elsewhere), so it is known by what was sent, never by the wording of the backend's detail.
export const TARGET_UNAVAILABLE =
  "This workout can't be edited any more — it was replaced or cancelled. Start over to pick another.";

// POST /coach/message failed (coach.py: 401 for a missing or expired token, 404 when the user no longer exists,
// 422 for a message the backend refuses, 502 when the model cannot answer, 503 when no key is configured; with a
// workout_plan_id also 404 for a plan that is not the user's or not there, and 409 for one that is not PLANNED). Asking
// again can help unless the problem is the person's session, the message, or the workout the message is about.
export type CoachFailure = { message: string; retryable: boolean };

export function coachFailure(error: unknown, aboutWorkout: boolean = false): CoachFailure {
  if (error instanceof ApiError && error.kind === 'http') {
    if (aboutWorkout && (error.status === 404 || error.status === 409)) {
      return { message: TARGET_UNAVAILABLE, retryable: false };
    }
    switch (error.status) {
      case 401:
        return { message: 'Your session has expired. Log in again.', retryable: false };
      case 404:
        return { message: "Formiq can't find your account. Log in again.", retryable: false };
      case 422:
        return { message: "Formiq couldn't accept that message. Change it and send it again.", retryable: false };
      case 502:
        return { message: "The coach couldn't answer. Try again in a moment.", retryable: true };
      case 503:
        return { message: "The coach isn't available right now. Try again later.", retryable: true };
    }
  }
  return { message: describeError(error, 'coach'), retryable: true };
}

export const describeCoachFailure = (error: unknown, aboutWorkout: boolean = false): string =>
  coachFailure(error, aboutWorkout).message;

// What the person reads when the coach answered with neither words nor a workout.
export const EMPTY_ANSWER: CoachFailure = {
  message: 'The coach sent an empty answer. Try again.',
  retryable: true,
};
