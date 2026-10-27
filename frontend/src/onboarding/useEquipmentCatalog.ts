import { useCallback, useState } from 'react';

import { describeError, listEquipment, type Equipment } from '../api';

export type EquipmentCatalog = {
  status: 'idle' | 'loading' | 'ready' | 'error';
  items: Equipment[];
  message: string | null;
  load: () => Promise<void>;
};

// The equipment the exercise catalog lists (GET /equipment). Held by the flow, so going back and
// forth between steps does not ask the backend again.
export function useEquipmentCatalog(): EquipmentCatalog {
  const [state, setState] = useState<Omit<EquipmentCatalog, 'load'>>({
    status: 'idle',
    items: [],
    message: null,
  });

  const load = useCallback(async () => {
    setState((current) => ({ ...current, status: 'loading', message: null }));
    try {
      setState({ status: 'ready', items: await listEquipment(), message: null });
    } catch (error) {
      setState({ status: 'error', items: [], message: describeError(error, 'equipment') });
    }
  }, []);

  return { ...state, load };
}
