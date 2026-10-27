import { useCallback, useEffect, useRef, useState } from 'react';

import { describeError, isSessionExpired, type Session } from '../api';
import { localDateKey } from './format';
import { loadTodayWorkout, type SettledTodayWorkout, type TodayWorkoutState } from './todayWorkout';

// How long an answer is used before Home asks again when it regains focus. Nothing in the app changes a
// plan or a session yet, so a short window loses nothing, and it keeps a quick trip to another tab (or into a
// workout and back) from asking the backend three times each time.
export const TODAY_WORKOUT_FRESH_MS = 30_000;

type Options = {
  // for tests: the clock
  now?: () => Date;
  freshMs?: number;
};

// Home's "Today's workout" state, read from the backend (read-only). `focused` is whether Home is what the
// person is looking at: Home is the selected tab, no screen is open over it, and the app is in the
// foreground. It asks when Home first comes into focus and each time it regains it, but:
//   - never twice at once: while a request is out, a new focus joins it;
//   - not again while the answer is fresh (TODAY_WORKOUT_FRESH_MS), unless the day has changed (the answer
//     is for one calendar day), the person asked ("Try again"), or something changed their plans (`invalidate`:
//     a workout applied from the coach), which asks at once when Home is in focus and otherwise when it next is.
// The state lives here, not in the screen, so leaving Home and coming back shows the last answer at once
// and refreshes it quietly, with no flash of "loading". A failed refresh replaces the answer with the error:
// an old answer that could not be confirmed is not shown as if it were current.
export function useTodayWorkout(session: Session, focused: boolean, options: Options = {}) {
  const [state, setState] = useState<TodayWorkoutState>({ kind: 'loading' });
  // what the last good answer was for, and when it came: only decides whether to ask again
  const loaded = useRef<{ userId: number; date: string; at: number } | null>(null);
  // `version` is how many times the plans were said to have changed (invalidate) when the read started: an answer
  // to a read that started before a change may not show it
  const inFlight = useRef<{ userId: number; date: string; version: number } | null>(null);
  const version = useRef(0);
  const focusedNow = useRef(focused);
  focusedNow.current = focused;
  const mounted = useRef(true);
  // read through refs so a new `now` or `freshMs` each render does not make Home ask again
  const nowRef = useRef(options.now ?? (() => new Date()));
  nowRef.current = options.now ?? nowRef.current;
  const freshMs = options.freshMs ?? TODAY_WORKOUT_FRESH_MS;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const load = useCallback(
    (force: boolean) => {
      const moment = nowRef.current();
      const request = { userId: session.userId, date: localDateKey(moment), version: version.current };
      const flying = inFlight.current;
      // a read that started before the plans changed does not stand for this one: it is not joined
      if (flying && flying.userId === request.userId && flying.date === request.date && flying.version === request.version) return;
      const last = loaded.current;
      if (
        !force &&
        last &&
        last.userId === request.userId &&
        last.date === request.date &&
        moment.getTime() - last.at < freshMs
      ) {
        return;
      }

      inFlight.current = request;
      // asking again after a failure shows that it is asking; asking again over an answer does not
      setState((current) => (current.kind === 'error' ? { kind: 'loading' } : current));

      const settle = (next: SettledTodayWorkout | Extract<TodayWorkoutState, { kind: 'error' }>) => {
        if (inFlight.current !== request) return;
        inFlight.current = null;
        // An answer to a read that started before the plans changed (and Home was out of focus, so nothing asked again)
        // is shown, but is not taken as current: the next time Home is in focus it asks again.
        const current = request.version === version.current;
        loaded.current =
          next.kind === 'error' || !current ? null : { userId: request.userId, date: request.date, at: nowRef.current().getTime() };
        if (mounted.current) setState(next);
      };
      loadTodayWorkout(session, moment).then(settle, (error: unknown) =>
        settle({ kind: 'error', message: describeError(error, 'todayWorkout'), retryable: !isSessionExpired(error) }),
      );
    },
    [session, freshMs],
  );

  useEffect(() => {
    if (focused) load(false);
  }, [focused, load]);

  const retry = useCallback(() => load(true), [load]);
  // For after something changed the user's plans (a workout applied from the coach), which the 30 s window would
  // otherwise hide, whichever tab the person is looking at. The last answer is no longer fresh, and a read already on
  // its way is no longer the answer. If Home is what the person is looking at, it asks again now; if not, the next time
  // Home is in focus it asks.
  const invalidate = useCallback(() => {
    version.current += 1;
    loaded.current = null;
    if (focusedNow.current) load(true);
  }, [load]);
  return { state, retry, invalidate };
}
