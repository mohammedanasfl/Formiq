import { fireEvent, screen, within } from '@testing-library/react-native';

import { emptyDraft, type ProfileDraft } from '../src/onboarding/draft';
import { ReviewScreen } from '../src/onboarding/screens/ReviewScreen';
import { themes } from '../src/theme';
import { renderWithTheme } from '../test-utils/renderWithTheme';

const dark = themes.dark.colors;
const HIDDEN = { includeHiddenElements: true };

const COMPLETE: ProfileDraft = {
  ...emptyDraft,
  goal: 'lose_weight',
  firstName: 'Sam',
  lastName: 'Lee',
  age: '30',
  gender: 'female',
  heightCm: '175',
  weight: '70',
  experience: 'beginner',
  trainingDays: 1,
  activityLevel: 'very_active',
  sleepHours: '7.5',
  location: 'home',
};

type Props = Partial<React.ComponentProps<typeof ReviewScreen>>;

async function renderReview(props: Props = {}, scheme: 'dark' | 'light' = 'dark') {
  const handlers = { onSave: jest.fn(), onBack: jest.fn(), onEdit: jest.fn() };
  await renderWithTheme(
    <ReviewScreen
      draft={COMPLETE}
      equipmentNames={['Dumbbell', 'Bench']}
      saving={false}
      error={null}
      {...handlers}
      {...props}
    />,
    scheme,
  );
  return handlers;
}

describe('<ReviewScreen /> content', () => {
  test('has the heading and a plain instruction, step 6 of 6, in the dark design', async () => {
    await renderReview();

    expect(screen.getByRole('header', { name: 'Review profile' })).toHaveStyle({ color: dark.textPrimary });
    expect(screen.getByText('Check your answers, then save.')).toHaveStyle({ color: dark.textSecondary });
    expect(screen.getByRole('progressbar')).toHaveAccessibleName('Step 6 of 6');
    expect(screen.getByTestId('step-frame')).toHaveStyle({ backgroundColor: dark.background });
  });

  test('says first that nothing is saved yet', async () => {
    await renderReview();

    screen.getByText('Not saved yet');
    screen.getByText('Nothing is stored in your Formiq account until you tap Save profile.');
  });

  test('shows every answer under a heading for its section, each with an Edit link of its own', async () => {
    const { onEdit } = await renderReview();

    const headings = screen.getAllByRole('header').map((heading) => heading.props.children);
    expect(headings).toEqual(['Review profile', 'Goal', 'Personal details', 'Training', 'Workout location', 'Equipment']);
    for (const [name, step] of [
      ['Edit goal', 'goal'],
      ['Edit personal details', 'details'],
      ['Edit training', 'training'],
      ['Edit workout location', 'location'],
      ['Edit equipment', 'equipment'],
    ] as const) {
      onEdit.mockClear();
      await fireEvent.press(screen.getByRole('link', { name }));
      expect(onEdit).toHaveBeenCalledWith(step);
    }
    for (const row of [
      'Name: Sam Lee',
      'Age: 30',
      'Gender: Female',
      'Height: 175 cm',
      'Weight: 70 kg',
      'Experience: Beginner',
      'Training days: 1 day a week',
      'Daily activity: Very active',
      'Sleep: 7.5 hours a night',
    ]) {
      screen.getByLabelText(row);
    }
    for (const value of ['Lose Weight', 'Home', 'Dumbbell, Bench']) screen.getByText(value);
  });

  test('a section of one answer shows only the answer: its heading already names it', async () => {
    await renderReview();

    expect(screen.getAllByText('Goal')).toHaveLength(1);
    expect(screen.queryByLabelText('Goal: Lose Weight')).toBeNull();
    expect(screen.queryByLabelText('Location: Home')).toBeNull();
    expect(screen.getAllByText('Equipment')).toHaveLength(1);
  });

  test('says what was typed in other units, next to what will be saved', async () => {
    await renderReview({
      draft: { ...COMPLETE, heightUnit: 'ft', heightFeet: '5', heightInches: '9', weightUnit: 'lb', weight: '154.3' },
    });

    screen.getByLabelText('Height: 5 ft 9 in (175.3 cm)');
    screen.getByLabelText('Weight: 154.3 lb (70 kg)');
  });

  test('shows the equipment as it is: names, "No equipment", or not chosen, and does not say it stays on the device', async () => {
    await renderReview();
    screen.getByText('Dumbbell, Bench');
    expect(screen.queryByText(/Only on this device/)).toBeNull();
    expect(screen.queryByText(/doesn't store equipment/)).toBeNull();
    await screen.unmount();

    await renderReview({ draft: { ...COMPLETE, noEquipment: true }, equipmentNames: [] });
    screen.getByText('No equipment');
    await screen.unmount();

    await renderReview({ equipmentNames: [] });
    screen.getByText('Not chosen');
  });

  test('is plain: no box around each section and no decoration beside the headings', async () => {
    await renderReview();

    // the arrows of the back button and of the save button are the only icons on the page
    expect(
      screen.getAllByTestId(/^icon-/, HIDDEN).map((icon) => icon.props.testID).sort(),
    ).toEqual(['icon-arrow-left', 'icon-arrow-right']);
    // the only box is the note at the top
    expect(screen.getAllByText('Edit')).toHaveLength(5);
  });

  test('keeps the dark look in the light theme', async () => {
    await renderReview({}, 'light');

    expect(screen.getByTestId('step-frame')).toHaveStyle({ backgroundColor: dark.background });
    expect(screen.getByText('Lose Weight')).toHaveStyle({ color: dark.textPrimary });
    expect(screen.getByText('Age')).toHaveStyle({ color: dark.textSecondary });
    expect(screen.getAllByText('Edit')[0]).toHaveStyle({ color: dark.accent });
  });
});

describe('<ReviewScreen /> saving', () => {
  test('offers "Save profile", and presses it', async () => {
    const { onSave } = await renderReview();

    const button = screen.getByRole('button', { name: 'Save profile' });
    expect(button).toHaveStyle({ backgroundColor: dark.primary });
    expect(within(screen.getByTestId('screen-footer')).getByRole('button', { name: 'Save profile' })).toBe(button);
    await fireEvent.press(button);
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  test('while saving: a busy button that cannot be pressed again, and a back arrow that does nothing', async () => {
    const { onSave, onBack } = await renderReview({ saving: true });

    const button = screen.getByRole('button', { name: 'Saving…' });
    expect(button).toBeDisabled();
    expect(button).toHaveProp('accessibilityState', { disabled: true });
    expect(screen.queryByRole('button', { name: 'Save profile' })).toBeNull();
    await fireEvent.press(button);
    expect(onSave).not.toHaveBeenCalled();

    const back = screen.getByRole('button', { name: 'Back' });
    expect(back).toBeDisabled();
    // dimmed, so it does not look like it works
    expect(back).toHaveStyle({ opacity: 0.4 });
    await fireEvent.press(back);
    expect(onBack).not.toHaveBeenCalled();
  });

  test('a failed save says why in the footer, in red, keeps every answer, and offers to try again', async () => {
    const { onSave } = await renderReview({ error: "Can't reach Formiq. Check your connection and try again." });

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent("Can't reach Formiq. Check your connection and try again.");
    expect(alert).toHaveStyle({ borderColor: dark.error });
    expect(within(screen.getByTestId('screen-footer')).getByRole('alert')).toBe(alert);
    screen.getByText('Lose Weight');
    screen.getByText('Not saved yet');
    expect(screen.queryByRole('button', { name: 'Save profile' })).toBeNull();

    await fireEvent.press(screen.getByRole('button', { name: 'Try again' }));
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  test('goes back, when it is not saving', async () => {
    const { onBack } = await renderReview();

    expect(screen.getByRole('button', { name: 'Back' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Back' })).toHaveStyle({ opacity: 1 });
    await fireEvent.press(screen.getByRole('button', { name: 'Back' }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});
