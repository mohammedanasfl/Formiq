import { StyleSheet } from 'react-native';
import { fireEvent, screen, within } from '@testing-library/react-native';

import { emptyDraft, type ProfileDraft } from '../src/onboarding/draft';
import { TrainingScreen } from '../src/onboarding/screens/TrainingScreen';
import type { StepScreenProps } from '../src/onboarding/screens/types';
import { layout, themes } from '../src/theme';
import { renderWithTheme } from '../test-utils/renderWithTheme';

const dark = themes.dark.colors;
// icons and indicators are decoration, hidden from screen readers
const HIDDEN = { includeHiddenElements: true };

const FILLED: ProfileDraft = {
  ...emptyDraft,
  experience: 'intermediate',
  trainingDays: 4,
  activityLevel: 'light',
  sleepHours: '7.5',
};

async function renderTraining(props: Partial<StepScreenProps> = {}, scheme: 'dark' | 'light' = 'dark') {
  const onChange = jest.fn();
  const onNext = jest.fn();
  await renderWithTheme(
    <TrainingScreen draft={emptyDraft} onChange={onChange} onNext={onNext} {...props} />,
    scheme,
  );
  return { onChange, onNext };
}

const next = () => fireEvent.press(screen.getByRole('button', { name: 'Next' }));

describe('<TrainingScreen /> content', () => {
  test('has the heading and supporting line, in the dark design', async () => {
    await renderTraining();

    const heading = screen.getByRole('header');
    expect(heading).toHaveTextContent('Your training');
    expect(screen.getAllByRole('header')).toHaveLength(1);
    expect(heading).toHaveStyle({ fontWeight: '700', color: dark.textPrimary });
    expect(screen.getByText('How you train now, so your profile fits you.')).toHaveStyle({ color: dark.textSecondary });
    expect(screen.getByTestId('step-frame')).toHaveStyle({ backgroundColor: dark.background });
  });

  test('asks for experience, days a week, daily activity and sleep, with the backend values', async () => {
    const { onChange } = await renderTraining();

    expect(
      within(screen.getByLabelText('Experience')).getAllByRole('radio').map((option) => option.props.accessibilityLabel),
    ).toEqual([
      'Beginner. New to training, or coming back after a long break',
      'Intermediate. You train regularly and know most exercises',
      'Advanced. Years of consistent training',
    ]);
    expect(
      within(screen.getByLabelText('Training days per week')).getAllByRole('radio').map((o) => o.props.accessibilityLabel ?? ''),
    ).toHaveLength(7);
    for (const name of ['Sedentary', 'Light', 'Moderate', 'Very active']) {
      within(screen.getByLabelText('Daily activity')).getByRole('radio', { name });
    }
    screen.getByLabelText('Sleep per night');

    await fireEvent.press(screen.getByRole('radio', { name: /Advanced/ }));
    await fireEvent.press(screen.getByRole('radio', { name: '5' }));
    await fireEvent.press(screen.getByRole('radio', { name: 'Very active' }));
    await fireEvent.changeText(screen.getByLabelText('Sleep per night'), '8');
    expect(onChange.mock.calls).toEqual([
      [{ experience: 'advanced' }],
      [{ trainingDays: 5 }],
      [{ activityLevel: 'very_active' }],
      [{ sleepHours: '8' }],
    ]);
  });

  test('selects and fills in nothing by itself', async () => {
    const { onChange } = await renderTraining();

    expect(screen.queryAllByRole('radio').filter((option) => option.props.accessibilityState?.checked)).toHaveLength(0);
    expect(screen.getByLabelText('Sleep per night')).toHaveDisplayValue('');
    expect(onChange).not.toHaveBeenCalled();
  });

  test('shows what was entered before', async () => {
    await renderTraining({ draft: FILLED });

    expect(screen.getByRole('radio', { name: /Intermediate/ })).toBeChecked();
    expect(screen.getByRole('radio', { name: '4' })).toBeChecked();
    expect(screen.getByRole('radio', { name: 'Light' })).toBeChecked();
    expect(screen.getByLabelText('Sleep per night')).toHaveDisplayValue('7.5');
  });
});

describe('<TrainingScreen /> look', () => {
  test('the experience levels are plain rows with a radio, and no decoration of their own', async () => {
    await renderTraining({ draft: FILLED });

    const group = screen.getByLabelText('Experience');
    for (const option of within(group).getAllByRole('radio')) {
      expect(StyleSheet.flatten(option.props.style).minHeight).toBeGreaterThanOrEqual(layout.touchTarget);
      expect(within(option).getByTestId('option-indicator', HIDDEN)).toBeOnTheScreen();
    }
    expect(within(group).queryByTestId(/^icon-/, HIDDEN)).toBeNull();
    expect(screen.getByRole('radio', { name: /Intermediate/ })).toHaveStyle({ borderColor: dark.accent });
    expect(screen.getByRole('radio', { name: /Beginner/ })).toHaveStyle({ borderColor: dark.borderStrong });
  });

  test('the day and activity choices are chips, outlined in emerald when chosen', async () => {
    await renderTraining({ draft: FILLED });

    for (const [name, selected] of [['4', true], ['3', false], ['Light', true], ['Moderate', false]] as const) {
      const chip = screen.getByRole('radio', { name });
      expect(chip).toHaveStyle({ minHeight: layout.touchTarget });
      expect(chip).toHaveStyle({ borderColor: selected ? dark.accent : dark.borderStrong });
    }
  });

  test('sleep is a number field with its unit at the end, and a hint', async () => {
    await renderTraining();

    const field = screen.getByLabelText('Sleep per night');
    expect(field).toHaveProp('keyboardType', 'decimal-pad');
    expect(field).toHaveProp('accessibilityHint', 'Hours on a typical night, for example 7.5.');
    expect(screen.getByText('hours', HIDDEN)).toHaveProp('accessibilityElementsHidden', true);
  });

  test('keeps the dark look in the light theme', async () => {
    await renderTraining({ draft: FILLED }, 'light');

    expect(screen.getByTestId('step-frame')).toHaveStyle({ backgroundColor: dark.background });
    expect(screen.getByRole('radio', { name: /Intermediate/ })).toHaveStyle({ borderColor: dark.accent });
    expect(screen.getByLabelText('Sleep per night')).toHaveStyle({ backgroundColor: dark.surface });
  });
});

describe('<TrainingScreen /> continuing', () => {
  test('says what is missing, next to each answer and next to the button, and does not move on', async () => {
    const { onNext } = await renderTraining();

    await next();

    expect(onNext).not.toHaveBeenCalled();
    for (const message of [
      'Choose your experience level.',
      'Choose how many days a week.',
      'Choose an activity level.',
      'Enter the hours you usually sleep, from 3 to 14.',
    ]) {
      expect(screen.getByText(message)).toHaveStyle({ color: dark.error });
    }
    // four alerts for the answers, and the line in the footer that points at them
    expect(screen.getAllByRole('alert')).toHaveLength(4);
    expect(within(screen.getByTestId('screen-footer')).getByText('Check the answers marked in red.')).toBeOnTheScreen();
    expect(screen.getByLabelText('Sleep per night')).toHaveStyle({ borderColor: dark.error });
  });

  test('refuses a sleep that is not a number of hours from 3 to 14', async () => {
    for (const sleepHours of ['2', '15', 'lots', '']) {
      const { onNext } = await renderTraining({ draft: { ...FILLED, sleepHours } });
      await next();
      expect(onNext).not.toHaveBeenCalled();
      screen.getByText('Enter the hours you usually sleep, from 3 to 14.');
      await screen.unmount();
    }
  });

  test('moves on when everything is answered, and shows "Done" when edited from the review', async () => {
    const { onNext } = await renderTraining({ draft: FILLED });

    await next();

    expect(onNext).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryByText('Check the answers marked in red.')).toBeNull();
    await screen.unmount();

    await renderTraining({ draft: FILLED, nextLabel: 'Done' });
    screen.getByRole('button', { name: 'Done' });
  });

  test('has step 3 of 6 and a back arrow that goes back', async () => {
    const onBack = jest.fn();
    await renderTraining({ onBack });

    expect(screen.getByRole('progressbar')).toHaveAccessibleName('Step 3 of 6');
    await fireEvent.press(screen.getByRole('button', { name: 'Back' }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  test('scrolls, and keeps Next in a footer above the keyboard', async () => {
    await renderTraining();

    expect(within(screen.getByTestId('screen-scroll')).getAllByRole('radio').length).toBeGreaterThan(10);
    expect(within(screen.getByTestId('screen-footer')).getByRole('button', { name: 'Next' })).toBeOnTheScreen();
    expect(screen.getByTestId('screen-keyboard-avoider')).toBeOnTheScreen();
  });
});
