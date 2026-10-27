import { apiRequest, ApiError, isRecord } from './client';
import type { Equipment } from './types';

// GET /equipment: the active equipment of the exercise catalog, no sign-in needed. Entries the app
// cannot read are left out, rather than shown half-formed.
export async function listEquipment(): Promise<Equipment[]> {
  const data = await apiRequest('/equipment');
  if (!Array.isArray(data)) throw new ApiError('invalid-response', null, null);
  return data.flatMap((item): Equipment[] =>
    isRecord(item) &&
    typeof item.id === 'number' &&
    typeof item.name === 'string' &&
    item.name.trim() !== ''
      ? [{ id: item.id, name: item.name }]
      : [],
  );
}
