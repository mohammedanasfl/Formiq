import { fireEvent, screen, within } from '@testing-library/react-native';

import { EDIT_PROFILE_NOTICE, equipmentSummary, ProfileScreen, THEME_NOTE } from '../src/profile/ProfileScreen';
import type { SavedEquipmentState } from '../src/profile/useSavedEquipment';
import { themes, type ThemeScheme } from '../src/theme';
import { renderWithTheme } from '../test-utils/renderWithTheme';

const dark = themes.dark.colors;
const light = themes.light.colors;

const NOT_CHOSEN: SavedEquipmentState = { kind: 'ready', saved: { equipment: [], noEquipment: false } };

async function renderProfile(scheme: ThemeScheme = 'dark', equipment: SavedEquipmentState = NOT_CHOSEN) {
  const onSignOut = jest.fn();
  const onRetryEquipment = jest.fn();
  const onEditEquipment = jest.fn();
  const view = await renderWithTheme(
    <ProfileScreen
      name="Sam"
      equipment={equipment}
      onRetryEquipment={onRetryEquipment}
      onEditEquipment={onEditEquipment}
      onSignOut={onSignOut}
    />,
    scheme,
  );
  return { ...view, onSignOut, onRetryEquipment, onEditEquipment };
}

describe('<ProfileScreen />', () => {
  test('names who is signed in, with an avatar of their first letter', async () => {
    await renderProfile();

    screen.getByRole('header', { name: 'Sam' });
    expect(within(screen.getByTestId('profile-avatar', { includeHiddenElements: true })).getByText('S', { includeHiddenElements: true })).toBeOnTheScreen();
  });

  test('"Edit profile" says editing is not built, and changes nothing', async () => {
    const { onSignOut } = await renderProfile();

    await fireEvent.press(screen.getByRole('button', { name: 'Edit profile. Update your details and goals' }));

    within(screen.getByTestId('toast')).getByText(EDIT_PROFILE_NOTICE);
    expect(EDIT_PROFILE_NOTICE).toBe("Editing your profile isn't built yet.");
    expect(onSignOut).not.toHaveBeenCalled();
  });

  test('offers the dark and the light theme, with the current one chosen, and says it is not remembered yet', async () => {
    await renderProfile();

    const group = screen.getByLabelText('Theme');
    expect(group).toHaveProp('accessibilityRole', 'radiogroup');
    expect(within(group).getByRole('radio', { name: 'Dark' })).toBeChecked();
    expect(within(group).getByRole('radio', { name: 'Light' })).not.toBeChecked();
    screen.getByText(THEME_NOTE);
  });

  test('choosing Light switches the whole app to the light theme, and Dark brings the dark one back', async () => {
    await renderProfile();
    expect(screen.getByRole('header', { name: 'Sam' })).toHaveStyle({ color: dark.textPrimary });

    await fireEvent.press(screen.getByRole('radio', { name: 'Light' }));

    expect(screen.getByRole('radio', { name: 'Light' })).toBeChecked();
    expect(screen.getByRole('radio', { name: 'Dark' })).not.toBeChecked();
    expect(screen.getByRole('header', { name: 'Sam' })).toHaveStyle({ color: light.textPrimary });

    await fireEvent.press(screen.getByRole('radio', { name: 'Dark' }));
    expect(screen.getByRole('radio', { name: 'Dark' })).toBeChecked();
    expect(screen.getByRole('header', { name: 'Sam' })).toHaveStyle({ color: dark.textPrimary });
  });

  test('opens in the light theme with Light chosen', async () => {
    await renderProfile('light');

    expect(screen.getByRole('radio', { name: 'Light' })).toBeChecked();
    expect(screen.getByRole('header', { name: 'Sam' })).toHaveStyle({ color: light.textPrimary });
  });

  test('Log out signs out once', async () => {
    const { onSignOut } = await renderProfile();

    await fireEvent.press(screen.getByRole('button', { name: 'Log out' }));

    expect(onSignOut).toHaveBeenCalledTimes(1);
  });

  test('has no unconnected claim: no email, plan, goal or statistic', async () => {
    await renderProfile();

    expect(screen.queryByText(/@|kcal|kg|cm|goal:|plan:/i)).toBeNull();
  });
});

describe('<ProfileScreen /> equipment', () => {
  const saved = (equipment: { id: number; name: string }[], noEquipment = false): SavedEquipmentState => ({
    kind: 'ready',
    saved: { equipment, noEquipment },
  });

  test('shows the equipment saved with the profile, by name', async () => {
    await renderProfile('dark', saved([{ id: 1, name: 'Dumbbell' }, { id: 3, name: 'Kettlebell' }]));

    screen.getByRole('header', { name: 'Equipment' });
    const card = screen.getByTestId('profile-equipment');
    expect(card).toHaveAccessibleName('Equipment: Dumbbell, Kettlebell');
    within(card).getByText('Dumbbell, Kettlebell');
  });

  test('shows "no equipment" as that', async () => {
    await renderProfile('dark', saved([], true));

    within(screen.getByTestId('profile-equipment')).getByText('No equipment (bodyweight only)');
  });

  test('says "Not chosen" for a profile that never said, and for no profile at all', async () => {
    await renderProfile('dark', saved([]));
    within(screen.getByTestId('profile-equipment')).getByText('Not chosen');
    await screen.unmount();

    await renderProfile('dark', { kind: 'ready', saved: null });
    within(screen.getByTestId('profile-equipment')).getByText('Not chosen');
  });

  test('shows progress while the backend is asked, and no equipment meanwhile', async () => {
    await renderProfile('dark', { kind: 'loading' });

    expect(screen.getByRole('progressbar', { name: 'Loading your equipment' })).toBeOnTheScreen();
    expect(screen.queryByTestId('profile-equipment')).toBeNull();
    expect(screen.queryByText('Not chosen')).toBeNull();
  });

  test('says why it cannot show it, offers to try again, and shows no equipment', async () => {
    const { onRetryEquipment } = await renderProfile('dark', {
      kind: 'error',
      message: "Can't reach Formiq. Check your connection and try again.",
      retryable: true,
    });

    expect(screen.getByRole('alert')).toHaveTextContent("Can't reach Formiq. Check your connection and try again.");
    expect(screen.queryByTestId('profile-equipment')).toBeNull();
    expect(screen.queryByText('Not chosen')).toBeNull();

    await fireEvent.press(screen.getByRole('button', { name: 'Try again' }));
    expect(onRetryEquipment).toHaveBeenCalledTimes(1);
  });

  test('offers no retry when only logging in again helps', async () => {
    await renderProfile('dark', { kind: 'error', message: 'Your session has expired. Log in again.', retryable: false });

    screen.getByRole('alert');
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull();
  });

  test('is told apart in the light theme too', async () => {
    await renderProfile('light', saved([{ id: 2, name: 'Bench' }]));

    expect(within(screen.getByTestId('profile-equipment')).getByText('Bench')).toHaveStyle({ color: light.textPrimary });
  });

  test('is what the backend said: the summary of each state', () => {
    expect(equipmentSummary(null)).toBe('Not chosen');
    expect(equipmentSummary({ equipment: [], noEquipment: false })).toBe('Not chosen');
    expect(equipmentSummary({ equipment: [], noEquipment: true })).toBe('No equipment (bodyweight only)');
    expect(equipmentSummary({ equipment: [{ id: 1, name: 'Bench' }], noEquipment: false })).toBe('Bench');
  });
});

describe('<ProfileScreen /> editing the equipment', () => {
  const SAVED = { equipment: [{ id: 1, name: 'Dumbbell' }], noEquipment: false };
  const edit = () => screen.getByRole('link', { name: 'Edit equipment' });

  test('offers "Edit" at the equipment heading, which opens the editor from what is saved', async () => {
    const { onEditEquipment } = await renderProfile('dark', { kind: 'ready', saved: SAVED });

    within(edit()).getByText('Edit');
    await fireEvent.press(edit());

    expect(onEditEquipment).toHaveBeenCalledTimes(1);
    expect(onEditEquipment).toHaveBeenCalledWith(SAVED);
  });

  test('offers it for "no equipment" and for "not chosen" too: both can be changed', async () => {
    await renderProfile('dark', { kind: 'ready', saved: { equipment: [], noEquipment: true } });
    expect(edit()).toBeOnTheScreen();
    await screen.unmount();

    await renderProfile('dark', NOT_CHOSEN);
    expect(edit()).toBeOnTheScreen();
  });

  test.each([
    ['while it is being read', { kind: 'loading' } as SavedEquipmentState],
    ['when it could not be read', { kind: 'error', message: 'x', retryable: true } as SavedEquipmentState],
    ['when there is no profile to change', { kind: 'ready', saved: null } as SavedEquipmentState],
  ])('does not offer it %s: there is nothing to start from', async (_name, state) => {
    const { onEditEquipment } = await renderProfile('dark', state);

    expect(screen.queryByRole('link', { name: 'Edit equipment' })).toBeNull();
    expect(onEditEquipment).not.toHaveBeenCalled();
  });

  test('"Edit profile" is still the notice: only the equipment has an editor', async () => {
    const { onEditEquipment } = await renderProfile('dark', { kind: 'ready', saved: SAVED });

    await fireEvent.press(screen.getByRole('button', { name: 'Edit profile. Update your details and goals' }));

    within(screen.getByTestId('toast')).getByText(EDIT_PROFILE_NOTICE);
    expect(onEditEquipment).not.toHaveBeenCalled();
  });
});

