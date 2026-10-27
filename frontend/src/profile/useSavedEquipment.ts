import { useCallback, useEffect, useRef, useState } from 'react';

import { describeError, getSavedEquipment, isSessionExpired, type SavedEquipment, type Session } from '../api';

// What the Profile tab shows of the person's equipment, as the backend keeps it. `saved` is null when the backend
// has no profile for them.
export type SavedEquipmentState =
  | { kind: 'loading' }
  | { kind: 'ready'; saved: SavedEquipment | null }
  | { kind: 'error'; message: string; retryable: boolean };

// The equipment saved with the person's profile, read from the backend (GET /users/{id}/profile) when the Profile
// tab is what they are looking at (`focused`), and again each time it regains focus. Never twice at once: while a
// request is out, a new focus joins it. The last answer stays on screen while the next is asked for, with no flash
// of "loading". A failed read replaces it with the error: an old answer that could not be confirmed is not shown as
// if it were current, and nothing is shown as saved that the backend did not say.
//
// `replace` is for a change the backend has just answered for (the equipment editor's save): it shows that answer at
// once, and a read that was already on its way when it came is not shown, as it may predate the change.
export function useSavedEquipment(session: Session, focused: boolean) {
  const [state, setState] = useState<SavedEquipmentState>({ kind: 'loading' });
  const inFlight = useRef(false);
  const mounted = useRef(true);
  // counts the answers put in by `replace`: a read shows its result only if none came while it was out
  const replaced = useRef(0);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const load = useCallback(() => {
    if (inFlight.current) return;
    inFlight.current = true;
    const asked = replaced.current;
    // asking again after a failure shows that it is asking; asking again over an answer does not
    setState((current) => (current.kind === 'error' ? { kind: 'loading' } : current));
    getSavedEquipment(session).then(
      (saved) => {
        inFlight.current = false;
        if (mounted.current && replaced.current === asked) setState({ kind: 'ready', saved });
      },
      (error: unknown) => {
        inFlight.current = false;
        if (mounted.current && replaced.current === asked) {
          setState({
            kind: 'error',
            message: describeError(error, 'savedEquipment'),
            retryable: !isSessionExpired(error),
          });
        }
      },
    );
  }, [session]);

  useEffect(() => {
    if (focused) load();
  }, [focused, load]);

  const replace = useCallback((saved: SavedEquipment) => {
    replaced.current += 1;
    if (mounted.current) setState({ kind: 'ready', saved });
  }, []);

  return { state, retry: load, replace };
}
