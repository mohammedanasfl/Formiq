import { fireEvent, screen, waitFor, within } from '@testing-library/react-native';

import type { SavedEquipment } from '../src/api';
import { EquipmentEditScreen } from '../src/profile/EquipmentEditScreen';
import { themes, type ThemeScheme } from '../src/theme';
import { fakeToken, installMockFetch, type MockFetch, type Reply } from '../test-utils/mockFetch';
import { renderWithTheme } from '../test-utils/renderWithTheme';

const dark = themes.dark.colors;
const light = themes.light.colors;

const SESSION = { token: fakeToken(7), userId: 7 };
const PROFILE = '/users/7/profile';

const CATALOG = [
  { id: 1, name: 'Dumbbell', description: null, is_active: true },
  { id: 2, name: 'Bench', description: null, is_active: true },
  { id: 3, name: 'Kettlebell', description: null, is_active: true },
  { id: 4, name: 'Resistance Band', description: null, is_active: true },
];
const piece = (id: number) => ({ id, name: CATALOG.find((item) => item.id === id)!.name });
const savedWith = (ids: number[], noEquipment = false): SavedEquipment => ({ equipment: ids.map(piece), noEquipment });
const answer = (ids: number[], noEquipment = false): Reply => ({
  status: 200,
  body: { first_name: 'Sam', no_equipment: noEquipment, equipment: ids.map(piece) },
});

let backend: MockFetch;

beforeEach(() => {
  backend = installMockFetch();
  backend.on('GET', '/equipment', { status: 200, body: CATALOG });
});

async function renderEditor(saved: SavedEquipment = savedWith([1, 3]), scheme: ThemeScheme = 'dark') {
  const onSaved = jest.fn();
  const onClose = jest.fn();
  const view = await renderWithTheme(
    <EquipmentEditScreen session={SESSION} saved={saved} onSaved={onSaved} onClose={onClose} />,
    scheme,
  );
  await screen.findByRole('checkbox', { name: 'Dumbbell' });
  return { ...view, onSaved, onClose };
}

const chip = (name: string) => screen.getByRole('checkbox', { name });
const NO_EQUIPMENT = 'No equipment. Bodyweight only';
const patches = () => backend.requests.filter((request) => request.method === 'PATCH');
const press = (name: string) => fireEvent.press(screen.getByRole('button', { name }));

describe('<EquipmentEditScreen /> content', () => {
  test('has a heading, says what the equipment is for, and offers Save and Cancel', async () => {
    await renderEditor();

    expect(screen.getByRole('header', { name: 'Edit equipment' })).toBeOnTheScreen();
    screen.getByText(/The coach starts from it when it suggests workouts/);
    screen.getByRole('button', { name: 'Save' });
    screen.getByRole('button', { name: 'Cancel' });
    screen.getByRole('button', { name: 'Back' });
  });

  test('starts from the saved pieces, chosen, and the others not', async () => {
    await renderEditor(savedWith([1, 3]));

    expect(chip('Dumbbell')).toBeChecked();
    expect(chip('Kettlebell')).toBeChecked();
    expect(chip('Bench')).not.toBeChecked();
    expect(chip('Resistance Band')).not.toBeChecked();
    expect(chip(NO_EQUIPMENT)).not.toBeChecked();
  });

  test('starts from "no equipment" when that is what is saved', async () => {
    await renderEditor(savedWith([], true));

    expect(chip(NO_EQUIPMENT)).toBeChecked();
    for (const name of ['Dumbbell', 'Bench', 'Kettlebell', 'Resistance Band']) expect(chip(name)).not.toBeChecked();
  });

  test('starts empty when the person never said', async () => {
    await renderEditor(savedWith([]));

    expect(screen.getAllByRole('checkbox').filter((box) => box.props.accessibilityState?.checked)).toHaveLength(0);
  });

  test('choosing "No equipment" clears the pieces, and choosing a piece clears "No equipment"', async () => {
    await renderEditor(savedWith([1, 3]));

    await fireEvent.press(chip(NO_EQUIPMENT));
    expect(chip(NO_EQUIPMENT)).toBeChecked();
    expect(chip('Dumbbell')).not.toBeChecked();
    expect(chip('Kettlebell')).not.toBeChecked();

    await fireEvent.press(chip('Bench'));
    expect(chip(NO_EQUIPMENT)).not.toBeChecked();
    expect(chip('Bench')).toBeChecked();
  });

  test('is themed like the Profile tab, in the light theme too', async () => {
    await renderEditor(savedWith([1]), 'light');

    expect(screen.getByTestId('equipment-edit-screen')).toHaveStyle({ backgroundColor: light.background });
    await screen.unmount();

    await renderEditor(savedWith([1]), 'dark');
    expect(screen.getByTestId('equipment-edit-screen')).toHaveStyle({ backgroundColor: dark.background });
  });
});

describe('<EquipmentEditScreen /> saving', () => {
  test('sends the changed choice, and only once the backend answers hands over its answer and closes', async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    backend.on('PATCH', PROFILE, async () => {
      await gate;
      // the backend kept exactly one piece of what was asked
      return answer([2]);
    });
    const { onSaved, onClose } = await renderEditor(savedWith([1, 3]));
    await fireEvent.press(chip('Dumbbell'));
    await fireEvent.press(chip('Kettlebell'));
    await fireEvent.press(chip('Bench'));
    await fireEvent.press(chip('Resistance Band'));

    await press('Save');

    expect(patches()).toHaveLength(1);
    expect(patches()[0].body).toEqual({ equipment_ids: [2, 4], no_equipment: false });
    expect(patches()[0].headers.Authorization).toBe(`Bearer ${SESSION.token}`);
    // nothing is saved, and the screen is not left, until the backend says so
    expect(onSaved).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();

    release();

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(onSaved).toHaveBeenCalledWith(savedWith([2]));
  });

  test('saves "no equipment" as that: no ids', async () => {
    backend.on('PATCH', PROFILE, answer([], true));
    const { onSaved, onClose } = await renderEditor(savedWith([1, 3]));
    await fireEvent.press(chip(NO_EQUIPMENT));

    await press('Save');

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(patches()[0].body).toEqual({ equipment_ids: [], no_equipment: true });
    expect(onSaved).toHaveBeenCalledWith({ equipment: [], noEquipment: true });
  });

  test('saves the pieces of a person who had none', async () => {
    backend.on('PATCH', PROFILE, answer([1, 4]));
    const { onSaved, onClose } = await renderEditor(savedWith([], true));
    await fireEvent.press(chip('Dumbbell'));
    await fireEvent.press(chip('Resistance Band'));

    await press('Save');

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(patches()[0].body).toEqual({ equipment_ids: [1, 4], no_equipment: false });
    expect(onSaved).toHaveBeenCalledWith(savedWith([1, 4]));
  });

  test('emptying the list is saved too, as "never said"', async () => {
    backend.on('PATCH', PROFILE, answer([]));
    const { onSaved, onClose } = await renderEditor(savedWith([1]));
    await fireEvent.press(chip('Dumbbell'));

    await press('Save');

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(patches()[0].body).toEqual({ equipment_ids: [], no_equipment: false });
    expect(onSaved).toHaveBeenCalledWith({ equipment: [], noEquipment: false });
  });

  test('says it is saving, ignores a second press, and cannot be left meanwhile', async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    backend.on('PATCH', PROFILE, async () => {
      await gate;
      return answer([1, 2, 3]);
    });
    const { onClose } = await renderEditor(savedWith([1, 3]));
    await fireEvent.press(chip('Bench'));

    await press('Save');

    const saving = screen.getByRole('button', { name: 'Saving…' });
    expect(saving).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Back' })).toBeDisabled();
    await fireEvent.press(saving);
    await fireEvent.press(screen.getByRole('button', { name: 'Cancel' }));
    await fireEvent.press(screen.getByRole('button', { name: 'Back' }));
    expect(patches()).toHaveLength(1);
    expect(onClose).not.toHaveBeenCalled();

    release();
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });

  test('choosing exactly what is saved changes nothing: Save closes without asking the backend', async () => {
    const { onSaved, onClose } = await renderEditor(savedWith([1, 3]));

    await press('Save');

    expect(patches()).toHaveLength(0);
    expect(onSaved).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  test('taking a piece away and putting it back is no change either', async () => {
    const { onSaved, onClose } = await renderEditor(savedWith([1, 3]));
    await fireEvent.press(chip('Dumbbell'));
    await fireEvent.press(chip('Dumbbell'));
    await fireEvent.press(chip('Bench'));
    await fireEvent.press(chip('Bench'));

    await press('Save');

    expect(patches()).toHaveLength(0);
    expect(onSaved).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  test('a saved piece the catalog does not list is not shown, and is neither a change nor sent with one', async () => {
    // saved: Dumbbell and a retired piece (id 99) the catalog no longer lists
    const retired = { id: 99, name: 'Old Rack' };
    const saved: SavedEquipment = { equipment: [piece(1), retired], noEquipment: false };
    backend.on('PATCH', PROFILE, answer([1, 2]));
    const { onSaved, onClose } = await renderEditor(saved);
    expect(screen.queryByRole('checkbox', { name: 'Old Rack' })).toBeNull();

    // nothing changed among what is offered: nothing is asked
    await press('Save');
    expect(patches()).toHaveLength(0);
    expect(onClose).toHaveBeenCalledTimes(1);
    onClose.mockClear();

    // a change: the retired id is not in what is sent (the backend refuses a retired id)
    await fireEvent.press(chip('Bench'));
    await press('Save');
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(patches()[0].body).toEqual({ equipment_ids: [1, 2], no_equipment: false });
    expect(onSaved).toHaveBeenCalledWith(savedWith([1, 2]));
  });
});

describe('<EquipmentEditScreen /> leaving without saving', () => {
  test('Cancel leaves with nothing sent and nothing handed over, even after a change', async () => {
    const { onSaved, onClose } = await renderEditor(savedWith([1, 3]));
    await fireEvent.press(chip('Bench'));

    await press('Cancel');

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onSaved).not.toHaveBeenCalled();
    expect(patches()).toHaveLength(0);
  });

  test('Back does the same', async () => {
    const { onSaved, onClose } = await renderEditor(savedWith([1, 3]));
    await fireEvent.press(chip(NO_EQUIPMENT));

    await press('Back');

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onSaved).not.toHaveBeenCalled();
    expect(patches()).toHaveLength(0);
  });
});

describe('<EquipmentEditScreen /> when the save fails', () => {
  test('stays open with what was chosen, says why, and neither hands over nor closes', async () => {
    backend.on('PATCH', PROFILE, 'network-error');
    const { onSaved, onClose } = await renderEditor(savedWith([1, 3]));
    await fireEvent.press(chip('Bench'));
    await fireEvent.press(chip('Dumbbell'));

    await press('Save');

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent("Can't reach Formiq. Check your connection and try again.");
    expect(alert).toHaveStyle({ borderColor: dark.error });
    expect(onSaved).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    // the choice is kept, and Save is there again
    expect(chip('Bench')).toBeChecked();
    expect(chip('Kettlebell')).toBeChecked();
    expect(chip('Dumbbell')).not.toBeChecked();
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeEnabled();
    expect(screen.queryByText(/saved/i)).toBeNull();
  });

  test.each([
    ['a server error', { status: 500 } as Reply, "Something went wrong on Formiq's side. Try again."],
    [
      'a refused piece',
      { status: 400, body: { detail: 'equipment 4 is retired' } } as Reply,
      "Formiq couldn't accept some of that equipment. Go back, open the list again and choose again.",
    ],
    ['no profile', { status: 404, body: { detail: 'user 7 has no profile' } } as Reply, 'Formiq could not find your profile, so nothing was changed.'],
    ['an answer it cannot read', { status: 200, body: { equipment: 'Bench' } } as Reply, 'Formiq sent an answer the app could not read. Try again.'],
  ])('%s is said, and nothing is handed over', async (_name, reply, message) => {
    backend.on('PATCH', PROFILE, reply);
    const { onSaved, onClose } = await renderEditor(savedWith([1]));
    await fireEvent.press(chip('Bench'));

    await press('Save');

    expect(await screen.findByRole('alert')).toHaveTextContent(message);
    expect(onSaved).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  test('can be tried again, and then saves and closes, the old error gone', async () => {
    backend.on('PATCH', PROFILE, { status: 500 });
    backend.on('PATCH', PROFILE, answer([1, 2]));
    const { onSaved, onClose } = await renderEditor(savedWith([1]));
    await fireEvent.press(chip('Bench'));
    await press('Save');
    await screen.findByRole('alert');

    await press('Save');

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(patches()).toHaveLength(2);
    expect(patches()[1].body).toEqual({ equipment_ids: [1, 2], no_equipment: false });
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(onSaved).toHaveBeenCalledWith(savedWith([1, 2]));
  });

  test('the choice can be changed after a failure, and the new one is what is sent', async () => {
    backend.on('PATCH', PROFILE, { status: 500 });
    backend.on('PATCH', PROFILE, answer([], true));
    const { onClose } = await renderEditor(savedWith([1]));
    await fireEvent.press(chip('Bench'));
    await press('Save');
    await screen.findByRole('alert');

    await fireEvent.press(chip(NO_EQUIPMENT));
    await press('Save');

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(patches()[1].body).toEqual({ equipment_ids: [], no_equipment: true });
  });

  test('Cancel still leaves after a failure, with nothing handed over', async () => {
    backend.on('PATCH', PROFILE, { status: 500 });
    const { onSaved, onClose } = await renderEditor(savedWith([1]));
    await fireEvent.press(chip('Bench'));
    await press('Save');
    await screen.findByRole('alert');

    await press('Cancel');

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onSaved).not.toHaveBeenCalled();
  });

  test('an expired session says so and cannot be saved again: only logging in again helps; Cancel still leaves', async () => {
    backend.on('PATCH', PROFILE, { status: 401, body: { detail: 'invalid token' } });
    const { onSaved, onClose } = await renderEditor(savedWith([1]));
    await fireEvent.press(chip('Bench'));

    await press('Save');

    expect(await screen.findByRole('alert')).toHaveTextContent('Your session has expired. Log in again.');
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    await fireEvent.press(screen.getByRole('button', { name: 'Save' }));
    expect(patches()).toHaveLength(1);
    expect(onSaved).not.toHaveBeenCalled();

    await press('Cancel');
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe('<EquipmentEditScreen /> the equipment list', () => {
  test('shows progress while the list loads, and no chips', async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    backend.reset();
    backend.on('GET', '/equipment', async () => {
      await gate;
      return { status: 200, body: CATALOG };
    });
    await renderWithTheme(
      <EquipmentEditScreen session={SESSION} saved={savedWith([1])} onSaved={jest.fn()} onClose={jest.fn()} />,
    );

    expect(screen.getByRole('progressbar', { name: 'Loading equipment' })).toBeOnTheScreen();
    expect(screen.queryByRole('checkbox')).toBeNull();

    release();
    expect(await screen.findByRole('checkbox', { name: 'Dumbbell' })).toBeChecked();
  });

  test('a list that cannot be loaded says why and can be asked for again; the saved equipment is not touched', async () => {
    backend.reset();
    backend.on('GET', '/equipment', 'network-error');
    backend.on('GET', '/equipment', { status: 200, body: CATALOG });
    const onSaved = jest.fn();
    const onClose = jest.fn();
    await renderWithTheme(<EquipmentEditScreen session={SESSION} saved={savedWith([1])} onSaved={onSaved} onClose={onClose} />);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent("Can't reach Formiq. Check your connection and try again.");
    screen.getByText('Your saved equipment stays as it is until you can choose again.');
    expect(screen.queryByRole('checkbox')).toBeNull();
    expect(patches()).toHaveLength(0);

    await press('Try again');

    expect(await screen.findByRole('checkbox', { name: 'Dumbbell' })).toBeChecked();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  test('with no list to choose from, Save changes nothing and asks nothing of the backend', async () => {
    backend.reset();
    backend.on('GET', '/equipment', { status: 500 });
    const onSaved = jest.fn();
    const onClose = jest.fn();
    await renderWithTheme(<EquipmentEditScreen session={SESSION} saved={savedWith([1, 3])} onSaved={onSaved} onClose={onClose} />);
    await screen.findByRole('alert');

    await press('Save');

    expect(patches()).toHaveLength(0);
    expect(onSaved).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  test('"No equipment" is offered even when the catalog lists nothing', async () => {
    backend.reset();
    backend.on('GET', '/equipment', { status: 200, body: [] });
    backend.on('PATCH', PROFILE, answer([], true));
    const onSaved = jest.fn();
    const onClose = jest.fn();
    await renderWithTheme(<EquipmentEditScreen session={SESSION} saved={savedWith([])} onSaved={onSaved} onClose={onClose} />);
    await screen.findByText('Formiq has no equipment listed right now.');

    await fireEvent.press(chip(NO_EQUIPMENT));
    await press('Save');

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(within(screen.getByTestId('equipment-edit-screen')).getAllByRole('checkbox')).toHaveLength(1);
    expect(onSaved).toHaveBeenCalledWith({ equipment: [], noEquipment: true });
  });
});
