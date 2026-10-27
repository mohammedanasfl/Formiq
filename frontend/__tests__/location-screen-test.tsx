import { StyleSheet } from 'react-native';
import { fireEvent, screen, within } from '@testing-library/react-native';

import { emptyDraft } from '../src/onboarding/draft';
import { LocationScreen } from '../src/onboarding/screens/LocationScreen';
import type { StepScreenProps } from '../src/onboarding/screens/types';
import { layout, radii, themes } from '../src/theme';
import { renderWithTheme } from '../test-utils/renderWithTheme';

const dark = themes.dark.colors;
const HIDDEN = { includeHiddenElements: true };

const GYM = 'Gym. You can use a gym: machines, barbells, dumbbells and more';
const HOME = 'Home. You train at home with your body weight and the equipment you own';

async function renderLocation(props: Partial<StepScreenProps> = {}, scheme: 'dark' | 'light' = 'dark') {
  const onChange = jest.fn();
  const onNext = jest.fn();
  await renderWithTheme(
    <LocationScreen draft={emptyDraft} onChange={onChange} onNext={onNext} {...props} />,
    scheme,
  );
  return { onChange, onNext };
}

const card = (name: string) => screen.getByRole('radio', { name });

describe('<LocationScreen />', () => {
  test('has the heading and a short question, in the dark design', async () => {
    await renderLocation();

    expect(screen.getByRole('header')).toHaveTextContent('Workout location');
    expect(screen.getAllByRole('header')).toHaveLength(1);
    expect(screen.getByText('Where do you plan to work out?')).toHaveStyle({ color: dark.textSecondary });
    expect(screen.getByTestId('step-frame')).toHaveStyle({ backgroundColor: dark.background });
  });

  test('offers gym and home, in this order, each with what it means', async () => {
    await renderLocation();

    const group = screen.getByLabelText('Workout location');
    expect(group).toHaveProp('accessibilityRole', 'radiogroup');
    expect(within(group).getAllByRole('radio').map((option) => option.props.accessibilityLabel)).toEqual([GYM, HOME]);
    expect(within(card(GYM)).getByTestId('icon-dumbbell', HIDDEN)).toBeOnTheScreen();
    expect(within(card(HOME)).getByTestId('icon-home-variant-outline', HIDDEN)).toBeOnTheScreen();
  });

  test('the two are wide rows like the goals: a touch target tall, with a radio', async () => {
    await renderLocation();

    for (const name of [GYM, HOME]) {
      const style = StyleSheet.flatten(card(name).props.style);
      expect(style.flexDirection).toBe('row');
      expect(style.minHeight).toBeGreaterThanOrEqual(layout.touchTarget);
      expect(style.borderRadius).toBe(radii.lg);
      expect(within(card(name)).getByTestId('option-indicator', HIDDEN)).toBeOnTheScreen();
    }
  });

  test('chooses nothing by itself, and shows the chosen place outlined in emerald', async () => {
    await renderLocation();
    expect(card(GYM)).not.toBeChecked();
    expect(card(HOME)).not.toBeChecked();
    await screen.unmount();

    await renderLocation({ draft: { ...emptyDraft, location: 'home' } });
    expect(card(HOME)).toBeChecked();
    expect(card(HOME)).toHaveStyle({ borderColor: dark.accent, borderWidth: layout.borderWidth.thick });
    expect(card(GYM)).not.toBeChecked();
    expect(card(GYM)).toHaveStyle({ borderColor: dark.borderStrong, borderWidth: layout.borderWidth.thin });
  });

  test('sends the backend value of the place pressed', async () => {
    const { onChange } = await renderLocation();

    await fireEvent.press(card(GYM));
    await fireEvent.press(card(HOME));

    expect(onChange.mock.calls).toEqual([[{ location: 'gym' }], [{ location: 'home' }]]);
  });

  test('asks for a place before moving on, with the message in the footer', async () => {
    const { onNext } = await renderLocation();

    await fireEvent.press(screen.getByRole('button', { name: 'Next' }));

    expect(onNext).not.toHaveBeenCalled();
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('Choose where you will work out.');
    expect(alert).toHaveStyle({ color: dark.error });
    expect(within(screen.getByTestId('screen-footer')).getByRole('alert')).toBe(alert);
  });

  test('moves on once a place is chosen, and says "Done" when edited from the review', async () => {
    const { onNext } = await renderLocation({ draft: { ...emptyDraft, location: 'gym' } });

    await fireEvent.press(screen.getByRole('button', { name: 'Next' }));
    expect(onNext).toHaveBeenCalledTimes(1);
    await screen.unmount();

    await renderLocation({ draft: { ...emptyDraft, location: 'gym' }, nextLabel: 'Done' });
    screen.getByRole('button', { name: 'Done' });
  });

  test('is step 4 of 6, goes back, and keeps the dark look in the light theme', async () => {
    const onBack = jest.fn();
    await renderLocation({ onBack, draft: { ...emptyDraft, location: 'gym' } }, 'light');

    expect(screen.getByRole('progressbar')).toHaveAccessibleName('Step 4 of 6');
    await fireEvent.press(screen.getByRole('button', { name: 'Back' }));
    expect(onBack).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('step-frame')).toHaveStyle({ backgroundColor: dark.background });
    expect(card(GYM)).toHaveStyle({ borderColor: dark.accent });
  });
});
