import type { EquipmentChoice, ProfileCreate } from '../api';
import type { ProfileDraft } from './draft';
import { round1, parseDecimal, parseWholeNumber } from './units';
import { heightInCm, isProfileComplete, weightInKg } from './validation';

// The equipment fields of a request, from a choice (the setup draft's, or the editor's): catalog ids, or "no equipment"
// and no ids, each id once. Never both: choosing "no equipment" empties the list. Neither chosen is sent as it is.
export function equipmentChoice(choice: Pick<ProfileDraft, 'equipmentIds' | 'noEquipment'>): EquipmentChoice {
  return {
    equipment_ids: choice.noEquipment ? [] : [...new Set(choice.equipmentIds)],
    no_equipment: choice.noEquipment,
  };
}

// The request body for POST /users/{id}/profile: exactly the backend's UserProfileCreate fields,
// in its units (centimetres, kilograms). The equipment goes as catalog ids, or as "no equipment" and
// no ids: the draft never holds both, and the body never says both. Neither chosen is sent as it is
// (no ids, not "none"): the backend then keeps that the person did not say. Throws when an answer is
// missing, so an incomplete draft is never sent.
export function buildProfilePayload(draft: ProfileDraft): ProfileCreate {
  const height = heightInCm(draft);
  const weight = weightInKg(draft);
  const age = parseWholeNumber(draft.age);
  const sleep = parseDecimal(draft.sleepHours);
  if (
    !isProfileComplete(draft) ||
    draft.goal === null ||
    draft.gender === null ||
    draft.experience === null ||
    draft.trainingDays === null ||
    draft.activityLevel === null ||
    draft.location === null ||
    height === null ||
    weight === null ||
    age === null ||
    sleep === null
  ) {
    throw new Error('The profile is not complete.');
  }

  const lastName = draft.lastName.trim();
  return {
    first_name: draft.firstName.trim(),
    // an empty last name is left out: the backend refuses empty text
    ...(lastName === '' ? {} : { last_name: lastName }),
    age,
    height_cm: round1(height),
    weight_kg: round1(weight),
    gender: draft.gender,
    fitness_experience: draft.experience,
    goal: draft.goal,
    training_frequency_per_week: draft.trainingDays,
    training_location: draft.location,
    activity_level: draft.activityLevel,
    sleep_hours: sleep,
    ...equipmentChoice(draft),
  };
}
