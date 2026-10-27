import type { Equipment, EquipmentChoice, SavedEquipment } from '../api';
import { equipmentChoice } from '../onboarding/profilePayload';

// What the equipment editor holds while it is open: the same two fields as the setup step's draft, seeded from what
// the backend has saved.
export type EquipmentSelection = { equipmentIds: number[]; noEquipment: boolean };

export function selectionFromSaved(saved: SavedEquipment): EquipmentSelection {
  return { equipmentIds: saved.equipment.map((item) => item.id), noEquipment: saved.noEquipment };
}

// What is chosen among what the editor offers. Once the catalog is known, a saved piece it does not list (the catalog
// lists active equipment only, and a profile can still hold a retired one) is left out: the person cannot see it, and
// the backend refuses a retired id, so sending it would fail every save without a way to fix it. Before the catalog
// is known, nothing is left out.
export function offeredSelection(selection: EquipmentSelection, offered: readonly Equipment[] | null): EquipmentSelection {
  if (offered === null) return selection;
  const listed = new Set(offered.map((item) => item.id));
  return { ...selection, equipmentIds: selection.equipmentIds.filter((id) => listed.has(id)) };
}

// Whether two selections say the same thing: the same pieces (order and repeats do not matter) or both "none". "Never
// said" (no pieces, not "none") is its own answer, different from "none".
export function sameSelection(a: EquipmentSelection, b: EquipmentSelection): boolean {
  if (a.noEquipment !== b.noEquipment) return false;
  const first = new Set(a.equipmentIds);
  const second = new Set(b.equipmentIds);
  return first.size === second.size && [...first].every((id) => second.has(id));
}

// What Save sends for the selection, or null when it changes nothing against what is saved (nothing is asked of the
// backend then). Both sides are judged among what is offered, so a retired piece the person cannot see neither
// counts as a change nor goes with one.
export function equipmentChange(
  saved: SavedEquipment,
  selection: EquipmentSelection,
  offered: readonly Equipment[] | null,
): EquipmentChoice | null {
  const wanted = offeredSelection(selection, offered);
  if (sameSelection(offeredSelection(selectionFromSaved(saved), offered), wanted)) return null;
  return equipmentChoice(wanted);
}
