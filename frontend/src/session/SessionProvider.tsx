import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';

import type { Session } from '../api';

type SessionContextValue = {
  // null until the backend has signed the user in or created their account
  session: Session | null;
  startSession: (session: Session) => void;
  endSession: () => void;
};

const SessionContext = createContext<SessionContextValue | null>(null);

// The signed-in user, held in memory only: closing the app signs them out. Keeping it on the device
// needs secure storage, which a later phase adds.
export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const value = useMemo(
    () => ({ session, startSession: setSession, endSession: () => setSession(null) }),
    [session],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (!value) {
    throw new Error('useSession must be used inside a <SessionProvider>.');
  }
  return value;
}
