import { apiRequest, ApiError, isRecord } from './client';
import { invalid, isInteger, isText } from './readers';
import type { EquipmentChoice, ProfileCreate, SavedEquipment, Session } from './types';

// POST /users/{id}/profile: 201 with the saved profile; 409 when the user already has one.
// Resolves only once the backend has saved it.
export async function createProfile(session: Session, profile: ProfileCreate): Promise<void> {
  await apiRequest(`/users/${session.userId}/profile`, {
    method: 'POST',
    body: profile,
    token: session.token,
  });
}

// GET /users/{id}/profile: 200 when the user has a profile, 404 when they have not made one yet.
export async function hasProfile(session: Session): Promise<boolean> {
  try {
    await apiRequest(`/users/${session.userId}/profile`, { token: session.token });
    return true;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return false;
    throw error;
  }
}

// GET /users/{id}/profile, read for the equipment it keeps: what the person chose when they set up their profile.
// null when they have no profile yet (404). An answer the app cannot read in full is refused, never trimmed: half
// a list shown as the person's equipment would be a wrong answer.
export async function getSavedEquipment(session: Session): Promise<SavedEquipment | null> {
  try {
    return readSavedEquipment(await apiRequest(`/users/${session.userId}/profile`, { token: session.token }));
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

// PATCH /users/{id}/profile with the equipment fields only: the person's equipment becomes exactly this choice
// (ids replace the list; no_equipment true empties it; neither says nothing). Resolves with what the backend answered
// (UserProfileResponse's equipment), so the app shows what the backend kept and never what it asked for. An error
// is a refusal or a failure to hear back: after a timeout or an answer the app cannot read the backend may have
// saved it all the same, and asking again is safe, since the request replaces rather than adds.
export async function saveEquipment(session: Session, choice: EquipmentChoice): Promise<SavedEquipment> {
  return readSavedEquipment(
    await apiRequest(`/users/${session.userId}/profile`, {
      method: 'PATCH',
      body: { equipment_ids: choice.equipment_ids, no_equipment: choice.no_equipment },
      token: session.token,
    }),
  );
}

// UserProfileResponse's `equipment` (each piece with its catalog id and name) and `no_equipment`. Other profile
// fields are not read here. Refuses a pieces list that is not well formed, and one that says the person has no
// equipment and lists some: the backend never saves both.
export function readSavedEquipment(data: unknown): SavedEquipment {
  if (!isRecord(data) || typeof data.no_equipment !== 'boolean' || !Array.isArray(data.equipment)) invalid();
  const equipment = data.equipment.map((item) => {
    if (!isRecord(item) || !isInteger(item.id) || !isText(item.name) || item.name.trim() === '') invalid();
    return { id: item.id, name: item.name };
  });
  if (data.no_equipment && equipment.length > 0) invalid();
  return { equipment, noEquipment: data.no_equipment };
}
