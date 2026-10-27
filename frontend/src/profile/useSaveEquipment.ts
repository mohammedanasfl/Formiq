import { useCallback, useEffect, useRef, useState } from 'react';

import { describeError, isSessionExpired, saveEquipment, type EquipmentChoice, type SavedEquipment, type Session } from '../api';

export type SaveEquipmentState =
  | { kind: 'idle' }
  | { kind: 'saving' }
  // the backend answered, with what it kept (also handed to `onSaved`)
  | { kind: 'saved'; saved: SavedEquipment }
  // `retryable` is false when only logging in again helps
  | { kind: 'error'; message: string; retryable: boolean };

// Saves a choice of equipment for the person (PATCH /users/{id}/profile) and says how that went. It is `saved` only
// with the backend's own answer, and `onSaved` gets that answer, never the choice that was asked for; a failure is
// an error, with nothing saved to show. One save at a time: a press while one is out is ignored. `onSaved` is called
// when the answer comes even if the screen that asked has gone (the back button was pressed meanwhile), so what the
// Profile tab shows follows the backend either way.
export function useSaveEquipment(session: Session, onSaved: (saved: SavedEquipment) => void) {
  const [state, setState] = useState<SaveEquipmentState>({ kind: 'idle' });
  const saving = useRef(false);
  const mounted = useRef(true);
  const latestOnSaved = useRef(onSaved);
  latestOnSaved.current = onSaved;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const save = useCallback(
    (choice: EquipmentChoice) => {
      if (saving.current) return;
      saving.current = true;
      setState({ kind: 'saving' });
      saveEquipment(session, choice).then(
        (saved) => {
          saving.current = false;
          latestOnSaved.current(saved);
          if (mounted.current) setState({ kind: 'saved', saved });
        },
        (error: unknown) => {
          saving.current = false;
          if (mounted.current) {
            setState({
              kind: 'error',
              message: describeError(error, 'saveEquipment'),
              retryable: !isSessionExpired(error),
            });
          }
        },
      );
    },
    [session],
  );

  return { state, save };
}
