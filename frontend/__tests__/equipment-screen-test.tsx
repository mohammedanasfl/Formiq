import { StyleSheet } from 'react-native';
import { fireEvent, screen, within } from '@testing-library/react-native';

import { emptyDraft, type ProfileDraft } from '../src/onboarding/draft';
import { equipmentIcon } from '../src/onboarding/icons';
import { EquipmentScreen } from '../src/onboarding/screens/EquipmentScreen';
import type { StepScreenProps } from '../src/onboarding/screens/types';
import type { EquipmentCatalog } from '../src/onboarding/useEquipmentCatalog';
import { layout, themes } from '../src/theme';
import { renderWithTheme } from '../test-utils/renderWithTheme';

const dark = themes.dark.colors;
const HIDDEN = { includeHiddenElements: true };

const ITEMS = [
  { id: 1, name: 'Dumbbell' },
  { id: 2, name: 'Treadmill' },
  { id: 3, name: 'Bench' },
  { id: 4, name: 'Other Equipment' },
];

function catalogWith(overrides: Partial<EquipmentCatalog> = {}): EquipmentCatalog {
  return { status: 'ready', items: ITEMS, message: null, load: jest.fn().mockResolvedValue(undefined), ...overrides };
}

async function renderEquipment(
  props: Partial<StepScreenProps> & { catalog?: EquipmentCatalog; draft?: ProfileDraft } = {},
  scheme: 'dark' | 'light' = 'dark',
) {
  const onChange = jest.fn();
  const onNext = jest.fn();
  const catalog = props.catalog ?? catalogWith();
  await renderWithTheme(
    <EquipmentScreen draft={emptyDraft} onChange={onChange} onNext={onNext} {...props} catalog={catalog} />,
    scheme,
  );
  return { onChange, onNext, catalog };
}

const chip = (name: string) => screen.getByRole('checkbox', { name });

describe('<EquipmentScreen /> content', () => {
  test('has the heading and the supporting line, step 5 of 6, in the dark design', async () => {
    await renderEquipment();

    expect(screen.getByRole('header')).toHaveTextContent('Available equipment');
    expect(screen.getByText('Select the equipment you have access to.')).toHaveStyle({ color: dark.textSecondary });
    expect(screen.getByRole('progressbar')).toHaveAccessibleName('Step 5 of 6');
    expect(screen.getByTestId('step-frame')).toHaveStyle({ backgroundColor: dark.background });
  });

  test('no longer says the choice is not saved: it goes with the profile', async () => {
    await renderEquipment();

    expect(screen.queryByText('Not saved yet')).toBeNull();
    expect(screen.queryByText(/doesn't store your equipment/)).toBeNull();
    expect(screen.queryByText(/stays on this device/)).toBeNull();
    // what is still true of the list is still said
    screen.getByText(/doesn't mean there are exercises for it/);
  });

  test('lists "No equipment" as a row and each catalog item as a chip, all checkboxes', async () => {
    await renderEquipment();

    expect(screen.getAllByRole('checkbox')).toHaveLength(1 + ITEMS.length);
    expect(chip('No equipment. Bodyweight only')).not.toBeChecked();
    for (const item of ITEMS) expect(chip(item.name)).not.toBeChecked();
    expect(screen.queryByRole('radio')).toBeNull();
  });

  test('chips are a touch target tall and carry one icon each, from one family', async () => {
    await renderEquipment();

    for (const [name, icon] of [
      ['Dumbbell', 'icon-dumbbell'],
      ['Treadmill', 'icon-run'],
      ['Bench', 'icon-bench'],
      ['Other Equipment', 'icon-shape-outline'],
    ] as const) {
      const option = chip(name);
      expect(StyleSheet.flatten(option.props.style).minHeight).toBeGreaterThanOrEqual(layout.touchTarget);
      expect(within(option).getAllByTestId(/^icon-/, HIDDEN)).toHaveLength(1);
      expect(within(option).getByTestId(icon, HIDDEN)).toBeOnTheScreen();
    }
  });

  test('a chosen chip is outlined in emerald and shows a check where its icon was', async () => {
    await renderEquipment({ draft: { ...emptyDraft, equipmentIds: [1] } });

    const chosen = chip('Dumbbell');
    expect(chosen).toBeChecked();
    expect(chosen).toHaveStyle({ borderColor: dark.accent, borderWidth: layout.borderWidth.thick });
    expect(within(chosen).getByTestId('check-mark', HIDDEN)).toBeOnTheScreen();
    expect(within(chosen).queryByTestId('icon-dumbbell', HIDDEN)).toBeNull();
    expect(chip('Bench')).toHaveStyle({ borderColor: dark.borderStrong, borderWidth: layout.borderWidth.thin });
    expect(within(chip('Bench')).queryByTestId('check-mark', HIDDEN)).toBeNull();
  });

  test('"No equipment" is a row with a square indicator, and is shown checked when chosen', async () => {
    await renderEquipment({ draft: { ...emptyDraft, noEquipment: true } });

    const row = chip('No equipment. Bodyweight only');
    expect(row).toBeChecked();
    expect(row).toHaveStyle({ borderColor: dark.accent });
    expect(within(row).getByTestId('option-indicator', HIDDEN)).toHaveStyle({ backgroundColor: dark.accent });
  });
});

describe('<EquipmentScreen /> choosing', () => {
  test('choosing an item clears "No equipment", and choosing it again removes it', async () => {
    const { onChange } = await renderEquipment({ draft: { ...emptyDraft, noEquipment: true } });

    await fireEvent.press(chip('Bench'));
    expect(onChange).toHaveBeenLastCalledWith({ noEquipment: false, equipmentIds: [3] });
    await screen.unmount();

    const second = await renderEquipment({ draft: { ...emptyDraft, equipmentIds: [1, 3] } });
    await fireEvent.press(chip('Bench'));
    expect(second.onChange).toHaveBeenLastCalledWith({ noEquipment: false, equipmentIds: [1] });
    await fireEvent.press(chip('Treadmill'));
    expect(second.onChange).toHaveBeenLastCalledWith({ noEquipment: false, equipmentIds: [1, 3, 2] });
  });

  test('"No equipment" empties the list', async () => {
    const { onChange } = await renderEquipment({ draft: { ...emptyDraft, equipmentIds: [1, 3] } });

    await fireEvent.press(chip('No equipment. Bodyweight only'));

    expect(onChange).toHaveBeenLastCalledWith({ noEquipment: true, equipmentIds: [] });
  });

  test('the step needs no answer: Next always moves on, and Back goes back', async () => {
    const onBack = jest.fn();
    const { onNext } = await renderEquipment({ onBack });

    await fireEvent.press(screen.getByRole('button', { name: 'Next' }));
    await fireEvent.press(screen.getByRole('button', { name: 'Back' }));

    expect(onNext).toHaveBeenCalledTimes(1);
    expect(onBack).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('alert')).toBeNull();
  });
});

describe('<EquipmentScreen /> loading the catalog', () => {
  test('asks for the catalog when it has not been asked for, and shows progress meanwhile', async () => {
    const catalog = catalogWith({ status: 'idle', items: [] });
    await renderEquipment({ catalog });

    expect(catalog.load).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('progressbar', { name: 'Loading equipment' })).toBeOnTheScreen();
    expect(screen.queryByRole('checkbox')).toBeNull();
  });

  test('does not ask again while it loads, or once it has loaded', async () => {
    const loading = catalogWith({ status: 'loading', items: [] });
    await renderEquipment({ catalog: loading });
    expect(loading.load).not.toHaveBeenCalled();
    screen.getByText('Loading equipment…');
    await screen.unmount();

    const ready = catalogWith();
    await renderEquipment({ catalog: ready });
    expect(ready.load).not.toHaveBeenCalled();
  });

  test('a failed load says why, offers to try again, and still lets the person move on', async () => {
    const catalog = catalogWith({ status: 'error', items: [], message: "Can't reach Formiq. Check your connection and try again." });
    const { onNext } = await renderEquipment({ catalog });

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent("Can't reach Formiq. Check your connection and try again.");
    expect(alert).toHaveStyle({ borderColor: dark.error });
    screen.getByText('You can also continue without choosing equipment.');
    expect(screen.queryByRole('checkbox')).toBeNull();

    await fireEvent.press(screen.getByRole('button', { name: 'Try again' }));
    expect(catalog.load).toHaveBeenCalledTimes(1);

    await fireEvent.press(screen.getByRole('button', { name: 'Next' }));
    expect(onNext).toHaveBeenCalledTimes(1);
  });

  test('an empty catalog is said to be empty, and "No equipment" is still there', async () => {
    await renderEquipment({ catalog: catalogWith({ items: [] }) });

    screen.getByText('Formiq has no equipment listed right now.');
    expect(screen.getAllByRole('checkbox')).toHaveLength(1);
  });

  test('keeps the dark look in the light theme', async () => {
    await renderEquipment({ draft: { ...emptyDraft, equipmentIds: [1] } }, 'light');

    expect(screen.getByTestId('step-frame')).toHaveStyle({ backgroundColor: dark.background });
    expect(chip('Dumbbell')).toHaveStyle({ borderColor: dark.accent });
    expect(chip('Bench')).toHaveStyle({ borderColor: dark.borderStrong });
  });
});

describe('equipmentIcon', () => {
  test('finds a fitting picture for every item of the catalog, and a neutral one for the unknown', () => {
    // the names the catalog has (backend/app/catalog/free_exercise_db.py and the seeded items)
    const expected: Record<string, string> = {
      Barbell: 'weight-lifter',
      Bench: 'bench',
      'Cable Machine': 'cog-outline',
      Dumbbell: 'dumbbell',
      'Exercise Ball': 'volleyball',
      'EZ Curl Bar': 'arm-flex',
      'Foam Roller': 'cylinder',
      Kettlebell: 'kettlebell',
      'Leg Press Machine': 'cog-outline',
      Machine: 'cog-outline',
      'Medicine Ball': 'basketball',
      'Other Equipment': 'shape-outline',
      'Pull-up Bar': 'human-handsup',
      'Resistance Band': 'infinity',
      'Rowing Machine': 'rowing',
      'Smith Machine': 'cog-outline',
      'Squat Rack': 'weight-lifter',
      'Stationary Bike': 'bike',
      Treadmill: 'run',
    };
    for (const [name, icon] of Object.entries(expected)) expect([name, equipmentIcon(name)]).toEqual([name, icon]);
    expect(equipmentIcon('Something New')).toBe('shape-outline');
  });
});
