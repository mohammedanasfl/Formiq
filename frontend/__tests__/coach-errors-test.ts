import { ApiError } from '../src/api';
import {
  coachFailure,
  describeApplyFailure,
  describeCoachFailure,
  describeRecoveryFailure,
  describeRejectFailure,
  EMPTY_ANSWER,
  isGone,
  TARGET_UNAVAILABLE,
} from '../src/coach/coachErrors';

const http = (status: number, detail: string | null = null) => new ApiError('http', status, detail);

describe('describeApplyFailure: what a person reads when a workout could not be applied', () => {
  test('a lost connection can be tried again, and says only that Formiq could not be reached', () => {
    expect(describeApplyFailure(new ApiError('network', null, null))).toEqual({
      message: "Can't reach Formiq. Check your connection and try again.",
      retryable: true,
    });
  });

  test.each(['timeout', 'invalid-response'] as const)(
    'a %s may or may not have saved the workout: it says so, and that trying again will tell',
    (kind) => {
      const failure = describeApplyFailure(new ApiError(kind, null, null));

      expect(failure.retryable).toBe(true);
      expect(failure.message).toMatch(/may not have been applied/);
      expect(failure.message).toMatch(/Formiq will say if it already was/);
    },
  );

  test.each([
    ['this proposal has expired: ask the coach for a new one', /has expired/],
    ['this proposal was already approved', /already applied/],
    ['this proposal was already approved, but the workout plan it saved was changed since', /already applied/],
    ['this proposal was rejected: ask the coach for a new one', /was dismissed/],
    ['the workout plan this proposal replaces was changed or cancelled since it was proposed: ask the coach for a new one', /would replace has changed/],
    ['this approval is for a different version of the proposal than the one proposed', /changed since it was shown/],
    ['this proposal can no longer be saved: exercise 7 is inactive', /can no longer be saved/],
    ['something else entirely', /couldn't apply this workout/],
  ])('409 "%s" can not be fixed by trying again, and says why', (detail, wording) => {
    const failure = describeApplyFailure(http(409, detail));

    expect(failure.retryable).toBe(false);
    expect(failure.message).toMatch(wording);
  });

  test('a 409 with no detail is still a refusal that trying again will not change', () => {
    expect(describeApplyFailure(http(409))).toEqual({
      message: "Formiq couldn't apply this workout. Ask the coach for a new one.",
      retryable: false,
    });
  });

  test.each([
    [401, false, /session has expired/],
    [404, false, /can't find this proposal/],
    [422, false, /couldn't accept this proposal/],
    [503, true, /isn't available/],
    [500, true, /on Formiq's side/],
    [502, true, /on Formiq's side/],
    [400, true, /Something went wrong/],
  ])('status %i: retryable %s', (status, retryable, wording) => {
    const failure = describeApplyFailure(http(status));

    expect(failure.retryable).toBe(retryable);
    expect(failure.message).toMatch(wording);
  });

  test('an error that is not the API\'s can be tried again and claims nothing', () => {
    const failure = describeApplyFailure(new Error('boom'));

    expect(failure.retryable).toBe(true);
    expect(failure.message).toBe('Something went wrong while applying this workout. Try again.');
  });

  test('no message ever says a workout was saved, applied or replaced', () => {
    const failures = [
      new ApiError('network', null, null),
      new ApiError('timeout', null, null),
      http(404),
      http(409, 'this proposal has expired'),
      http(503),
      new Error('x'),
    ].map((error) => describeApplyFailure(error).message);

    for (const message of failures) expect(message).not.toMatch(/\b(was|has been|is now) (saved|applied|replaced|added)\b/i);
  });
});

describe('describeCoachFailure: what a person reads when the coach could not answer', () => {
  test.each([
    [http(502), "The coach couldn't answer. Try again in a moment."],
    [http(503), "The coach isn't available right now. Try again later."],
    [http(401), 'Your session has expired. Log in again.'],
    [new ApiError('network', null, null), "Can't reach Formiq. Check your connection and try again."],
    [new ApiError('timeout', null, null), 'Formiq took too long to answer. Try again.'],
    [new Error('x'), 'Something went wrong. Try again.'],
  ])('%#', (error, message) => {
    expect(describeCoachFailure(error)).toBe(message);
  });
});

describe('coachFailure: whether asking the coach again can help', () => {
  test.each([
    [401, "Your session has expired. Log in again.", false],
    [404, "Formiq can't find your account. Log in again.", false],
    [422, "Formiq couldn't accept that message. Change it and send it again.", false],
    [502, "The coach couldn't answer. Try again in a moment.", true],
    [503, "The coach isn't available right now. Try again later.", true],
    [500, "Something went wrong on Formiq's side. Try again.", true],
  ])('a %s answer: "%s", asking again %s', (status, message, retryable) => {
    expect(coachFailure(http(status))).toEqual({ message, retryable });
  });

  test.each([
    ['network', "Can't reach Formiq. Check your connection and try again."],
    ['timeout', 'Formiq took too long to answer. Try again.'],
    ['invalid-response', 'Formiq sent an answer the app could not read. Try again.'],
  ] as const)('a %s failure can be tried again', (kind, message) => {
    expect(coachFailure(new ApiError(kind, null, null))).toEqual({ message, retryable: true });
  });

  test('anything that is not an API error can be tried again, with a plain sentence', () => {
    expect(coachFailure(new Error('boom'))).toEqual({ message: 'Something went wrong. Try again.', retryable: true });
  });

  test('describeCoachFailure is its sentence', () => {
    expect(describeCoachFailure(http(401))).toBe(coachFailure(http(401)).message);
  });

  test('an answer with neither words nor a workout is a failure that can be tried again, and blames no one', () => {
    expect(EMPTY_ANSWER).toEqual({ message: 'The coach sent an empty answer. Try again.', retryable: true });
  });
});

describe('coachFailure for a message about a saved workout: the answer is about that workout', () => {
  test.each([404, 409])('a %s is the workout that can no longer be edited, and asking again cannot help', (status) => {
    expect(coachFailure(http(status, 'whatever the backend says'), true)).toEqual({ message: TARGET_UNAVAILABLE, retryable: false });
  });

  test('the sentence says it was replaced or cancelled and what to do', () => {
    expect(TARGET_UNAVAILABLE).toBe("This workout can't be edited any more — it was replaced or cancelled. Start over to pick another.");
  });

  test('is known by what was sent, not by the backend\'s wording', () => {
    for (const detail of [null, 'user 7 has no workout plan 41', 'workout plan 41 is CANCELLED', 'anything']) {
      expect(coachFailure(http(404, detail), true).message).toBe(TARGET_UNAVAILABLE);
      expect(coachFailure(http(409, detail), true).message).toBe(TARGET_UNAVAILABLE);
    }
  });

  test('the same statuses to a message about no workout mean what they always did', () => {
    expect(coachFailure(http(404, 'user 7 does not exist'))).toEqual({ message: "Formiq can't find your account. Log in again.", retryable: false });
    expect(coachFailure(http(404), false).message).toBe("Formiq can't find your account. Log in again.");
    expect(coachFailure(http(409)).message).not.toBe(TARGET_UNAVAILABLE);
  });

  test.each([
    [401, 'Your session has expired. Log in again.', false],
    [422, "Formiq couldn't accept that message. Change it and send it again.", false],
    [502, "The coach couldn't answer. Try again in a moment.", true],
    [503, "The coach isn't available right now. Try again later.", true],
  ])('every other answer is as for any message: %s', (status, message, retryable) => {
    expect(coachFailure(http(status), true)).toEqual({ message, retryable });
  });

  test('a lost connection can be tried again, whatever the message was about', () => {
    expect(coachFailure(new ApiError('network', null, null), true).retryable).toBe(true);
  });

  test('describeCoachFailure says the same', () => {
    expect(describeCoachFailure(http(409), true)).toBe(TARGET_UNAVAILABLE);
  });
});

describe('describeRejectFailure: what a person reads when a workout could not be dismissed', () => {
  test('a lost connection can be tried again, and says only that Formiq could not be reached', () => {
    expect(describeRejectFailure(new ApiError('network', null, null))).toEqual({
      message: "Can't reach Formiq. Check your connection and try again.",
      retryable: true,
    });
  });

  test.each(['timeout', 'invalid-response'] as const)('a %s may not have dismissed it: it says so, and trying again is safe', (kind) => {
    const failure = describeRejectFailure(new ApiError(kind, null, null));

    expect(failure.retryable).toBe(true);
    expect(failure.message).toMatch(/may not have been dismissed/);
  });

  test.each([
    [401, false, /session has expired/],
    [409, false, /already applied or changed/],
    [422, false, /couldn't dismiss/],
    [503, true, /isn't available/],
    [500, true, /on Formiq's side/],
    [400, true, /Something went wrong/],
  ])('status %i: retryable %s', (status, retryable, wording) => {
    const failure = describeRejectFailure(http(status));

    expect(failure.retryable).toBe(retryable);
    expect(failure.message).toMatch(wording);
  });

  test('an error that is not the API\'s can be tried again and claims nothing', () => {
    expect(describeRejectFailure(new Error('boom'))).toEqual({
      message: 'Something went wrong while dismissing this workout. Try again.',
      retryable: true,
    });
  });

  test('no message ever says a workout was dismissed or saved', () => {
    const messages = [new ApiError('network', null, null), new ApiError('timeout', null, null), http(409), http(503), new Error('x')].map(
      (error) => describeRejectFailure(error).message,
    );

    for (const message of messages) expect(message).not.toMatch(/\b(was|has been|is now) (dismissed|saved|applied|rejected)\b/i);
  });

  test('a 404 is the answer that the proposal is not there, which is not a failure of the request', () => {
    expect(isGone(http(404))).toBe(true);
    expect(isGone(http(409))).toBe(false);
    expect(isGone(new ApiError('network', null, null))).toBe(false);
    expect(isGone(new Error('x'))).toBe(false);
  });
});

describe('describeRecoveryFailure: what a person reads when the waiting workouts could not be looked up', () => {
  test.each([
    [new ApiError('network', null, null), "Can't reach Formiq. Couldn't check for workouts waiting for your approval."],
    [http(503), "Formiq isn't available right now. Couldn't check for workouts waiting for your approval."],
    [http(500), "Formiq didn't answer. Couldn't check for workouts waiting for your approval."],
    [new ApiError('timeout', null, null), "Formiq didn't answer. Couldn't check for workouts waiting for your approval."],
    [new ApiError('invalid-response', null, null), "Formiq didn't answer. Couldn't check for workouts waiting for your approval."],
    [new Error('x'), "Formiq didn't answer. Couldn't check for workouts waiting for your approval."],
  ])('%#: asking again is safe, so it can be tried again', (error, message) => {
    expect(describeRecoveryFailure(error)).toEqual({ message, retryable: true });
  });

  test('an expired session cannot be helped by asking again', () => {
    expect(describeRecoveryFailure(http(401))).toEqual({ message: 'Your session has expired. Log in again.', retryable: false });
  });

  test('never says there is none', () => {
    for (const error of [new ApiError('network', null, null), http(500), http(401)]) {
      expect(describeRecoveryFailure(error).message).not.toMatch(/\bno workouts?\b|\bnothing\b|\bnone\b/i);
    }
  });
});
