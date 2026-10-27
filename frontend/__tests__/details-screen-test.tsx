import { StyleSheet } from 'react-native';
import { fireEvent, render, screen, within } from '@testing-library/react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { emptyDraft, type ProfileDraft } from '../src/onboarding/draft';
import { DetailsScreen } from '../src/onboarding/screens/DetailsScreen';
import type { StepScreenProps } from '../src/onboarding/screens/types';
import { layout, radii, ThemeProvider, themes } from '../src/theme';
import { renderWithTheme } from '../test-utils/renderWithTheme';

const dark = themes.dark.colors;
// units and icons are decoration, hidden from screen readers, so queries must ask for them
const HIDDEN = { includeHiddenElements: true };

const FILLED: ProfileDraft = {
  ...emptyDraft,
  goal: 'build_muscle',
  firstName: 'Sam',
  age: '30',
  gender: 'other',
  heightCm: '175',
  weight: '70',
};

async function renderDetails(props: Partial<StepScreenProps> = {}, scheme: 'dark' | 'light' = 'dark') {
  const onChange = jest.fn();
  const onNext = jest.fn();
  await renderWithTheme(
    <DetailsScreen draft={emptyDraft} onChange={onChange} onNext={onNext} {...props} />,
    scheme,
  );
  return { onChange, onNext };
}

const next = () => fireEvent.press(screen.getByRole('button', { name: 'Next' }));

describe('<DetailsScreen /> content', () => {
  test('has the heading and the supporting line the design asks for', async () => {
    await renderDetails();

    const heading = screen.getByRole('header');
    expect(heading).toHaveTextContent('Tell us about yourself');
    expect(screen.getAllByRole('header')).toHaveLength(1);
    expect(heading).toHaveStyle({ fontWeight: '700', color: dark.textPrimary });
    expect(screen.getByText('This helps create a plan that fits you.')).toHaveStyle({ color: dark.textSecondary });
  });

  test('asks for the name, age, gender, height and weight, and nothing the next step asks', async () => {
    await renderDetails();

    for (const label of ['First name', 'Last name (optional)', 'Age', 'Height (cm)', 'Weight (kg)']) {
      screen.getByLabelText(label);
    }
    expect(screen.getAllByRole('radio')).toHaveLength(7);
    for (const name of ['Male', 'Female', 'Other', 'cm', 'ft / in', 'kg', 'lb']) {
      screen.getByRole('radio', { name });
    }
    // experience, training days, activity and sleep are on "Your training", the next step
    expect(screen.queryByText(/experience|training days|activity|sleep/i)).toBeNull();
  });

  test('shows what was entered before, and fills nothing in by itself', async () => {
    const { onChange } = await renderDetails({ draft: FILLED });

    expect(screen.getByLabelText('First name')).toHaveDisplayValue('Sam');
    expect(screen.getByLabelText('Age')).toHaveDisplayValue('30');
    expect(screen.getByRole('radio', { name: 'Other' })).toBeChecked();
    expect(screen.getByLabelText('Height (cm)')).toHaveDisplayValue('175');
    expect(screen.getByLabelText('Weight (kg)')).toHaveDisplayValue('70');
    expect(onChange).not.toHaveBeenCalled();
  });

  test('chooses no gender for the person', async () => {
    await renderDetails();

    for (const name of ['Male', 'Female', 'Other']) {
      expect(screen.getByRole('radio', { name })).not.toBeChecked();
    }
  });
});

describe('<DetailsScreen /> fields', () => {
  test('the names take words with capitals, as names, and offer them to autofill', async () => {
    await renderDetails();

    const first = screen.getByLabelText('First name');
    expect(first).toHaveProp('autoCapitalize', 'words');
    expect(first).toHaveProp('autoComplete', 'given-name');
    const last = screen.getByLabelText('Last name (optional)');
    expect(last).toHaveProp('autoCapitalize', 'words');
    expect(last).toHaveProp('autoComplete', 'family-name');
  });

  test('numbers get number keyboards, and each field shows its unit at its end', async () => {
    await renderDetails();

    expect(screen.getByLabelText('Age')).toHaveProp('keyboardType', 'number-pad');
    expect(screen.getByLabelText('Age')).toHaveProp('maxLength', 3);
    expect(screen.getByLabelText('Height (cm)')).toHaveProp('keyboardType', 'decimal-pad');
    expect(screen.getByLabelText('Weight (kg)')).toHaveProp('keyboardType', 'decimal-pad');
    for (const unit of ['years', 'cm', 'kg']) {
      expect(screen.getAllByText(unit, HIDDEN).length).toBeGreaterThan(0);
    }
  });

  test('"next" on the keyboard moves through the text fields, and the last one says "done"', async () => {
    await renderDetails();

    for (const label of ['First name', 'Last name (optional)', 'Age', 'Height (cm)']) {
      const field = screen.getByLabelText(label);
      expect(field).toHaveProp('returnKeyType', 'next');
      // keeps the keyboard up while the focus moves on
      expect(field).toHaveProp('submitBehavior', 'submit');
    }
    expect(screen.getByLabelText('Weight (kg)')).toHaveProp('returnKeyType', 'done');
  });

  test('in feet and inches, height is two fields, and inches are optional', async () => {
    await renderDetails({ draft: { ...emptyDraft, heightUnit: 'ft', weightUnit: 'lb' } });

    expect(screen.getByRole('radio', { name: 'ft / in' })).toBeChecked();
    expect(screen.getByLabelText('Height (feet)')).toHaveProp('keyboardType', 'number-pad');
    expect(screen.getByLabelText('Height (inches)')).toHaveProp('keyboardType', 'number-pad');
    screen.getByText('Optional.');
    expect(screen.getByText('ft', HIDDEN)).toBeOnTheScreen();
    expect(screen.getByText('in', HIDDEN)).toBeOnTheScreen();
    expect(screen.getByLabelText('Weight (lb)')).toBeOnTheScreen();
    expect(screen.queryByLabelText('Height (cm)')).toBeNull();
  });

  test('the measurement names are shown on the row of their unit switch, and said once with the field', async () => {
    await renderDetails();

    // the field carries the name and the unit for a screen reader; the row's name is for the eye
    expect(screen.queryByText('Height')).toBeNull();
    expect(screen.getByText('Height', HIDDEN)).toBeOnTheScreen();
    expect(screen.getByText('Weight', HIDDEN)).toBeOnTheScreen();
    expect(screen.queryByText('Height (cm)', HIDDEN)).toBeNull(); // not printed above the field too
  });
});

describe('<DetailsScreen /> units', () => {
  test('the unit switches are labelled groups with the chosen unit checked and filled in emerald', async () => {
    await renderDetails();

    expect(screen.getByLabelText('Height unit')).toHaveProp('accessibilityRole', 'radiogroup');
    expect(screen.getByLabelText('Weight unit')).toHaveProp('accessibilityRole', 'radiogroup');
    const cm = screen.getByRole('radio', { name: 'cm' });
    const feet = screen.getByRole('radio', { name: 'ft / in' });
    expect(cm).toBeChecked();
    expect(feet).not.toBeChecked();
    expect(cm).toHaveStyle({ backgroundColor: dark.primary });
    expect(within(cm).getByText('cm')).toHaveStyle({ color: dark.textOnPrimary });
    expect(feet).toHaveStyle({ backgroundColor: 'transparent' });
    expect(within(feet).getByText('ft / in')).toHaveStyle({ color: dark.textSecondary });
  });

  test('each unit takes taps over a full touch target', async () => {
    await renderDetails();

    for (const name of ['cm', 'ft / in', 'kg', 'lb']) {
      const unit = screen.getByRole('radio', { name });
      const { minHeight } = StyleSheet.flatten(unit.props.style);
      const { top, bottom } = unit.props.hitSlop;
      expect(minHeight + top + bottom).toBe(layout.touchTarget);
    }
  });

  test('changing a unit converts what was typed, and only that', async () => {
    const { onChange } = await renderDetails({ draft: FILLED });

    await fireEvent.press(screen.getByRole('radio', { name: 'ft / in' }));
    await fireEvent.press(screen.getByRole('radio', { name: 'lb' }));
    await fireEvent.press(screen.getByRole('radio', { name: 'cm' })); // already chosen: nothing changes

    expect(onChange.mock.calls).toEqual([
      [{ heightUnit: 'ft', heightFeet: '5', heightInches: '9' }],
      [{ weightUnit: 'lb', weight: '154.3' }],
      [{}],
    ]);
  });

  test('an empty field just changes its unit', async () => {
    const { onChange } = await renderDetails();

    await fireEvent.press(screen.getByRole('radio', { name: 'ft / in' }));
    await fireEvent.press(screen.getByRole('radio', { name: 'lb' }));

    expect(onChange.mock.calls).toEqual([[{ heightUnit: 'ft' }], [{ weightUnit: 'lb' }]]);
  });
});

describe('<DetailsScreen /> moving on', () => {
  test('checks every answer first: each field says what is wrong, and the footer says to look for them', async () => {
    const { onNext } = await renderDetails();

    await next();

    expect(onNext).not.toHaveBeenCalled();
    for (const message of [
      'Enter your first name.',
      'Enter your age as a whole number from 13 to 100.',
      'Choose an option.',
      'Enter a height from 100 to 250 cm.',
      'Enter a weight from 30 to 300 kg.',
    ]) {
      expect(screen.getByText(message)).toHaveStyle({ color: dark.error });
    }
    expect(screen.getAllByRole('alert')).toHaveLength(5);
    expect(screen.getByLabelText('First name')).toHaveStyle({ borderColor: dark.error });
    // the reminder is in the footer, in view whatever the scroll position; the fields announce themselves
    const reminder = within(screen.getByTestId('screen-footer')).getByText('Check the answers marked in red.');
    expect(reminder).toHaveStyle({ color: dark.error });
    expect(reminder).not.toHaveProp('accessibilityRole', 'alert');
  });

  test('moves on with complete answers, and shows no reminder', async () => {
    const { onNext } = await renderDetails({ draft: FILLED });

    await next();

    expect(onNext).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('Check the answers marked in red.')).toBeNull();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  test('the button is "Next" with an arrow, or "Done" when editing from the review', async () => {
    await renderDetails();
    const button = within(screen.getByTestId('screen-footer')).getByRole('button', { name: 'Next' });
    expect(button).toHaveStyle({ backgroundColor: dark.primary, minHeight: 56, borderRadius: radii.lg });
    expect(within(button).getByTestId('icon-arrow-right', HIDDEN)).toBeOnTheScreen();
    await screen.unmount();

    await renderDetails({ nextLabel: 'Done' });
    screen.getByRole('button', { name: 'Done' });
  });

  test('shows step 2 of 6, and a back arrow that goes back', async () => {
    const onBack = jest.fn();
    await renderDetails({ onBack });

    expect(screen.getByRole('progressbar')).toHaveAccessibleName('Step 2 of 6');
    expect(screen.getByTestId('progress-segment-2')).toHaveStyle({ backgroundColor: dark.primary });
    expect(screen.getByTestId('progress-segment-3')).toHaveStyle({ backgroundColor: dark.borderStrong });
    await fireEvent.press(screen.getByRole('button', { name: 'Back' }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});

describe('<DetailsScreen /> look and layout', () => {
  test('sits on the gym photo like the goal step, and keeps the dark look in the light theme', async () => {
    await renderDetails({}, 'light');

    expect(screen.getByTestId('step-frame')).toHaveStyle({ backgroundColor: dark.background });
    expect(screen.getByTestId('step-photo')).toHaveProp('source', require('../assets/images/signup-background.png'));
    expect(screen.getByLabelText('First name')).toHaveStyle({
      backgroundColor: dark.surface,
      borderColor: dark.borderStrong,
      color: dark.textPrimary,
    });
    expect(screen.getByRole('radio', { name: 'Male' })).toHaveStyle({ borderColor: dark.borderStrong });
  });

  test('scrolls the form and keeps the button in a footer above the keyboard', async () => {
    await renderDetails();

    const scroll = screen.getByTestId('screen-scroll');
    expect(scroll).toHaveProp('keyboardShouldPersistTaps', 'handled');
    expect(within(scroll).getByLabelText('Weight (kg)')).toBeOnTheScreen();
    expect(within(scroll).queryByRole('button', { name: 'Next' })).toBeNull();
    expect(within(screen.getByTestId('screen-footer')).getByRole('button', { name: 'Next' })).toBeOnTheScreen();
    expect(screen.getByTestId('screen-keyboard-avoider')).toBeOnTheScreen();
  });

  test('keeps clear of the system bars', async () => {
    const insets = { top: 47, bottom: 34, left: 0, right: 0 };
    await render(
      <SafeAreaProvider initialMetrics={{ frame: { x: 0, y: 0, width: 390, height: 844 }, insets }}>
        <ThemeProvider>
          <DetailsScreen draft={emptyDraft} onChange={jest.fn()} onNext={jest.fn()} />
        </ThemeProvider>
      </SafeAreaProvider>,
    );

    expect(screen.getByTestId('step-screen')).toHaveStyle({ paddingTop: insets.top, paddingBottom: insets.bottom });
  });
});
