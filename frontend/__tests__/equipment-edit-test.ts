import { equipmentChoice } from '../src/onboarding/profilePayload';
import { emptyDraft } from '../src/onboarding/draft';
import { equipmentChange, offeredSelection, sameSelection, selectionFromSaved } from '../src/profile/equipmentEdit';

const DUMBBELL = { id: 1, name: 'Dumbbell' };
const BENCH = { id: 2, name: 'Bench' };
const BAND = { id: 3, name: 'Resistance Band' };
const CATALOG = [DUMBBELL, BENCH, BAND];

const saved = (equipment: { id: number; name: string }[], noEquipment = false) => ({ equipment, noEquipment });

describe('equipmentChoice', () => {
  test('sends each id once', () => {
    expect(equipmentChoice({ equipmentIds: [1, 3, 1], noEquipment: false })).toEqual({
      equipment_ids: [1, 3],
      no_equipment: false,
    });
  });

  test('"no equipment" goes with no ids, whatever the list held', () => {
    expect(equipmentChoice({ equipmentIds: [1, 3], noEquipment: true })).toEqual({ equipment_ids: [], no_equipment: true });
  });

  test('neither chosen is sent as it is, so the backend keeps that nothing was said', () => {
    expect(equipmentChoice({ equipmentIds: [], noEquipment: false })).toEqual({ equipment_ids: [], no_equipment: false });
    expect(equipmentChoice(emptyDraft)).toEqual({ equipment_ids: [], no_equipment: false });
  });
});

describe('selectionFromSaved', () => {
  test('starts from the saved pieces, or from "no equipment"', () => {
    expect(selectionFromSaved(saved([DUMBBELL, BAND]))).toEqual({ equipmentIds: [1, 3], noEquipment: false });
    expect(selectionFromSaved(saved([], true))).toEqual({ equipmentIds: [], noEquipment: true });
    expect(selectionFromSaved(saved([]))).toEqual({ equipmentIds: [], noEquipment: false });
  });
});

describe('sameSelection', () => {
  test('the same pieces are the same whatever their order or repeats', () => {
    expect(sameSelection({ equipmentIds: [1, 3], noEquipment: false }, { equipmentIds: [3, 1, 1], noEquipment: false })).toBe(true);
  });

  test('other pieces, or more or fewer, are not', () => {
    expect(sameSelection({ equipmentIds: [1], noEquipment: false }, { equipmentIds: [2], noEquipment: false })).toBe(false);
    expect(sameSelection({ equipmentIds: [1], noEquipment: false }, { equipmentIds: [1, 2], noEquipment: false })).toBe(false);
    expect(sameSelection({ equipmentIds: [1, 2], noEquipment: false }, { equipmentIds: [1], noEquipment: false })).toBe(false);
  });

  test('"no equipment" and "never said" are different answers', () => {
    expect(sameSelection({ equipmentIds: [], noEquipment: true }, { equipmentIds: [], noEquipment: false })).toBe(false);
    expect(sameSelection({ equipmentIds: [], noEquipment: true }, { equipmentIds: [], noEquipment: true })).toBe(true);
    expect(sameSelection({ equipmentIds: [], noEquipment: false }, { equipmentIds: [], noEquipment: false })).toBe(true);
  });
});

describe('offeredSelection', () => {
  test('leaves a selection as it is until the catalog is known', () => {
    const selection = { equipmentIds: [1, 99], noEquipment: false };
    expect(offeredSelection(selection, null)).toBe(selection);
  });

  test('leaves out a piece the catalog does not list', () => {
    expect(offeredSelection({ equipmentIds: [1, 99, 3], noEquipment: false }, CATALOG)).toEqual({
      equipmentIds: [1, 3],
      noEquipment: false,
    });
  });
});

describe('equipmentChange', () => {
  test('is null for the selection that is saved: nothing to ask the backend', () => {
    expect(equipmentChange(saved([DUMBBELL, BAND]), { equipmentIds: [3, 1], noEquipment: false }, CATALOG)).toBeNull();
    expect(equipmentChange(saved([], true), { equipmentIds: [], noEquipment: true }, CATALOG)).toBeNull();
    expect(equipmentChange(saved([]), { equipmentIds: [], noEquipment: false }, CATALOG)).toBeNull();
    // and before the catalog is known
    expect(equipmentChange(saved([DUMBBELL]), { equipmentIds: [1], noEquipment: false }, null)).toBeNull();
  });

  test('is the choice to send when it differs', () => {
    expect(equipmentChange(saved([DUMBBELL]), { equipmentIds: [1, 2], noEquipment: false }, CATALOG)).toEqual({
      equipment_ids: [1, 2],
      no_equipment: false,
    });
    expect(equipmentChange(saved([DUMBBELL]), { equipmentIds: [], noEquipment: true }, CATALOG)).toEqual({
      equipment_ids: [],
      no_equipment: true,
    });
  });

  test('emptying the list is a change, sent as "never said"', () => {
    expect(equipmentChange(saved([DUMBBELL]), { equipmentIds: [], noEquipment: false }, CATALOG)).toEqual({
      equipment_ids: [],
      no_equipment: false,
    });
  });

  test('going from "no equipment" to some pieces is a change', () => {
    expect(equipmentChange(saved([], true), { equipmentIds: [2], noEquipment: false }, CATALOG)).toEqual({
      equipment_ids: [2],
      no_equipment: false,
    });
  });

  test('a saved piece the catalog no longer lists is neither a change nor sent with one', () => {
    const retired = { id: 99, name: 'Old Rack' };

    // nothing else changed: nothing to send
    expect(equipmentChange(saved([DUMBBELL, retired]), { equipmentIds: [1, 99], noEquipment: false }, CATALOG)).toBeNull();
    // something else changed: only what is offered goes
    expect(equipmentChange(saved([DUMBBELL, retired]), { equipmentIds: [1, 99, 2], noEquipment: false }, CATALOG)).toEqual({
      equipment_ids: [1, 2],
      no_equipment: false,
    });
  });
});
