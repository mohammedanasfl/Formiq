import { StyleSheet } from 'react-native';
import { fireEvent, render, screen, within } from '@testing-library/react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { emptyDraft } from '../src/onboarding/draft';
import { GoalScreen } from '../src/onboarding/screens/GoalScreen';
import type { StepScreenProps } from '../src/onboarding/screens/types';
import { layout, radii, ThemeProvider, themes } from '../src/theme';
import { renderWithTheme } from '../test-utils/renderWithTheme';

const dark = themes.dark.colors;
// icons, radios and the arrow are decoration, hidden from screen readers, so queries must ask for them
const HIDDEN = { includeHiddenElements: true };

const BUILD_MUSCLE = 'Build Muscle. Gain strength and build lean muscle mass.';
const LOSE_WEIGHT = 'Lose Weight. Reduce body fat and get leaner.';
const IMPROVE_FITNESS = 'Improve Fitness. Improve endurance and overall fitness.';
const GOALS = [BUILD_MUSCLE, LOSE_WEIGHT, IMPROVE_FITNESS];

async function renderGoal(props: Partial<StepScreenProps> = {}, scheme: 'dark' | 'light' = 'dark') {
  const onChange = jest.fn();
  const onNext = jest.fn();
  await renderWithTheme(
    <GoalScreen draft={emptyDraft} onChange={onChange} onNext={onNext} {...props} />,
    scheme,
  );
  return { onChange, onNext };
}

const card = (name: string) => screen.getByRole('radio', { name });
type Element = ReturnType<typeof card>;

// The color the icon in a card is drawn in: the glyph is the one child of the icon's wrapper.
function iconColor(element: Element, icon: string) {
  const wrapper = within(element).getByTestId(`icon-${icon}`, HIDDEN);
  return StyleSheet.flatten((wrapper.children[0] as Element).props.style).color;
}

describe('<GoalScreen /> content', () => {
  test('has the heading and the supporting line the design asks for', async () => {
    await renderGoal();

    const heading = screen.getByRole('header');
    expect(heading).toHaveTextContent('Your Fitness Goal');
    expect(screen.getAllByRole('header')).toHaveLength(1);
    expect(heading).toHaveStyle({ fontWeight: '700', color: dark.textPrimary });
    expect(screen.getByText('What do you want to achieve with Formiq?')).toHaveStyle({ color: dark.textSecondary });
  });

  test('offers exactly the three supported goals, in this order, each with its title and description', async () => {
    await renderGoal();

    const group = screen.getByLabelText('Goal');
    expect(group).toHaveProp('accessibilityRole', 'radiogroup');
    expect(within(group).getAllByRole('radio').map((option) => option.props.accessibilityLabel)).toEqual(GOALS);
    for (const text of [
      'Build Muscle',
      'Gain strength and build lean muscle mass.',
      'Lose Weight',
      'Reduce body fat and get leaner.',
      'Improve Fitness',
      'Improve endurance and overall fitness.',
    ]) {
      screen.getByText(text);
    }
    // goals the backend does not know are not offered
    expect(screen.queryByText(/stay healthy/i)).toBeNull();
    expect(screen.queryByText(/^other$/i)).toBeNull();
    expect(screen.getAllByRole('radio')).toHaveLength(3);
  });

  test('draws one icon for each goal: three bars, a flame, a runner', async () => {
    await renderGoal();

    expect(within(card(BUILD_MUSCLE)).getByTestId('icon-signal-cellular-3', HIDDEN)).toBeOnTheScreen();
    expect(within(card(LOSE_WEIGHT)).getByTestId('icon-fire', HIDDEN)).toBeOnTheScreen();
    expect(within(card(IMPROVE_FITNESS)).getByTestId('icon-run-fast', HIDDEN)).toBeOnTheScreen();
  });

  test('stacks three wide rows, each a touch target tall with its icon, words and a radio', async () => {
    await renderGoal();

    for (const name of GOALS) {
      const option = card(name);
      const style = StyleSheet.flatten(option.props.style);
      expect(style.flexDirection).toBe('row');
      expect(style.minHeight).toBeGreaterThanOrEqual(layout.touchTarget);
      expect(style.borderRadius).toBe(radii.lg);
      expect(within(option).getByTestId('option-indicator', HIDDEN)).toBeOnTheScreen();
    }
  });
});

describe('<GoalScreen /> selection', () => {
  test('an unselected card has a subtle grey outline, a muted icon and an empty radio', async () => {
    await renderGoal();

    for (const [name, icon] of [
      [BUILD_MUSCLE, 'signal-cellular-3'],
      [LOSE_WEIGHT, 'fire'],
      [IMPROVE_FITNESS, 'run-fast'],
    ]) {
      const option = card(name);
      expect(option).not.toBeChecked();
      expect(option).toHaveStyle({ borderColor: dark.borderStrong, borderWidth: layout.borderWidth.thin });
      expect(iconColor(option, icon)).toBe(dark.textMuted);
      expect(within(option).getByTestId('option-indicator', HIDDEN)).toHaveStyle({ borderColor: dark.borderStrong });
      expect(within(option).queryByTestId('option-indicator-dot', HIDDEN)).toBeNull();
    }
  });

  test('the selected card has an emerald outline, an emerald icon and a filled emerald radio', async () => {
    await renderGoal({ draft: { ...emptyDraft, goal: 'lose_weight' } });

    const selected = card(LOSE_WEIGHT);
    expect(selected).toBeChecked();
    expect(selected).toHaveStyle({ borderColor: dark.accent, borderWidth: layout.borderWidth.thick });
    expect(iconColor(selected, 'fire')).toBe(dark.accent);
    expect(within(selected).getByTestId('option-indicator', HIDDEN)).toHaveStyle({ borderColor: dark.accent });
    expect(within(selected).getByTestId('option-indicator-dot', HIDDEN)).toHaveStyle({ backgroundColor: dark.accent });

    // only one is selected, and the others stay plain
    for (const name of [BUILD_MUSCLE, IMPROVE_FITNESS]) {
      expect(card(name)).not.toBeChecked();
      expect(card(name)).toHaveStyle({ borderColor: dark.borderStrong });
    }
    expect(screen.getAllByTestId('option-indicator-dot', HIDDEN)).toHaveLength(1);
  });

  test('sends the exact backend value of the goal that was pressed', async () => {
    const { onChange } = await renderGoal();

    await fireEvent.press(card(BUILD_MUSCLE));
    await fireEvent.press(card(LOSE_WEIGHT));
    await fireEvent.press(card(IMPROVE_FITNESS));

    expect(onChange.mock.calls).toEqual([
      [{ goal: 'build_muscle' }],
      [{ goal: 'lose_weight' }],
      [{ goal: 'general_fitness' }],
    ]);
  });

  test('keeps the size of a card when it is selected: the padding gives back what the border takes', async () => {
    await renderGoal({ draft: { ...emptyDraft, goal: 'build_muscle' } });

    const room = (name: string) => {
      const { padding, borderWidth } = StyleSheet.flatten(card(name).props.style);
      return padding + borderWidth;
    };
    expect(room(BUILD_MUSCLE)).toBe(room(LOSE_WEIGHT)); // selected, then not selected
  });
});

describe('<GoalScreen /> continuing', () => {
  test('has one wide emerald "Continue" button with an arrow, in the footer', async () => {
    await renderGoal();

    const footer = screen.getByTestId('screen-footer');
    const buttons = within(footer).getAllByRole('button');
    expect(buttons.map((button) => button.props.accessibilityLabel)).toEqual(['Continue']);
    expect(buttons[0]).toHaveStyle({ backgroundColor: dark.primary, minHeight: 56, borderRadius: radii.lg });
    expect(within(buttons[0]).getByTestId('icon-arrow-right', HIDDEN)).toBeOnTheScreen();
    expect(screen.getByText('Continue')).toHaveStyle({ color: dark.textOnPrimary });
  });

  test('says "Continue" whatever label the flow offers going forward, and "Done" when the goal is edited', async () => {
    await renderGoal({ nextLabel: 'Next' });
    screen.getByRole('button', { name: 'Continue' });
    expect(screen.queryByRole('button', { name: 'Next' })).toBeNull();
    await screen.unmount();

    await renderGoal({ nextLabel: 'Done' });
    screen.getByRole('button', { name: 'Done' });
    expect(screen.queryByRole('button', { name: 'Continue' })).toBeNull();
  });

  test('asks for a goal before moving on, with an announced error', async () => {
    const { onNext } = await renderGoal();

    await fireEvent.press(screen.getByRole('button', { name: 'Continue' }));

    expect(onNext).not.toHaveBeenCalled();
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('Choose a goal to continue.');
    expect(alert).toHaveStyle({ color: dark.error });
    // in the footer, so it is in view whatever the scroll position (it would hide below the cards on a small screen)
    expect(within(screen.getByTestId('screen-footer')).getByRole('alert')).toBe(alert);
    expect(within(screen.getByTestId('screen-scroll')).queryByRole('alert')).toBeNull();
  });

  test('moves on when a goal is chosen', async () => {
    const { onNext } = await renderGoal({ draft: { ...emptyDraft, goal: 'general_fitness' } });

    await fireEvent.press(screen.getByRole('button', { name: 'Continue' }));

    expect(onNext).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('alert')).toBeNull();
  });
});

describe('<GoalScreen /> top bar', () => {
  test('shows the compact progress, "Step 1 of 6", without printing it', async () => {
    await renderGoal();

    expect(screen.getByRole('progressbar')).toHaveAccessibleName('Step 1 of 6');
    expect(screen.queryByText('Step 1 of 6', HIDDEN)).toBeNull();
    expect(screen.getByTestId('progress-segment-1')).toHaveStyle({ backgroundColor: dark.primary });
    for (const ahead of [2, 3, 4, 5, 6]) {
      expect(screen.getByTestId(`progress-segment-${ahead}`)).toHaveStyle({ backgroundColor: dark.borderStrong });
    }
  });

  test('has a back arrow only where there is a step before it', async () => {
    await renderGoal();
    expect(screen.queryByRole('button', { name: 'Back' })).toBeNull();
    // the bar is as tall as the back button either way, so the progress does not move between steps
    expect(screen.getByTestId('step-top-bar')).toHaveStyle({ minHeight: layout.touchTarget });
    await screen.unmount();

    const onBack = jest.fn();
    await renderGoal({ onBack });
    const back = screen.getByRole('button', { name: 'Back' });
    expect(screen.getByTestId('step-top-bar')).toHaveStyle({ minHeight: layout.touchTarget });
    expect(back).toHaveStyle({ width: layout.touchTarget, height: layout.touchTarget });
    expect(within(back).getByTestId('icon-arrow-left', HIDDEN)).toBeOnTheScreen();
    await fireEvent.press(back);
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});

describe('<GoalScreen /> look', () => {
  test('sits on the gym photo under a dark layer, and the photo is hidden from screen readers', async () => {
    await renderGoal();

    const photo = screen.getByTestId('step-photo');
    expect(photo).toHaveProp('source', require('../assets/images/signup-background.png'));
    expect(photo).toHaveProp('resizeMode', 'cover');
    expect(photo).toHaveProp('importantForAccessibility', 'no');
    expect(photo).not.toHaveProp('accessibilityLabel');
    expect(photo).toHaveStyle({ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, width: '100%', height: '100%' });
    const scrim = screen.getByTestId('step-photo-scrim');
    expect(scrim).toHaveStyle({ backgroundColor: dark.background });
    expect(StyleSheet.flatten(scrim.props.style).opacity).toBeGreaterThan(0);
  });

  test('keeps the dark look in the light theme', async () => {
    await renderGoal({ draft: { ...emptyDraft, goal: 'build_muscle' } }, 'light');

    expect(screen.getByTestId('step-frame')).toHaveStyle({ backgroundColor: dark.background });
    expect(screen.getByRole('header')).toHaveStyle({ color: dark.textPrimary });
    expect(card(BUILD_MUSCLE)).toHaveStyle({ borderColor: dark.accent });
    expect(card(LOSE_WEIGHT)).toHaveStyle({ borderColor: dark.borderStrong });
    expect(screen.getByRole('button', { name: 'Continue' })).toHaveStyle({ backgroundColor: dark.primary });
  });

  test('keeps clear of the system bars', async () => {
    const insets = { top: 47, bottom: 34, left: 0, right: 0 };
    await render(
      <SafeAreaProvider initialMetrics={{ frame: { x: 0, y: 0, width: 390, height: 844 }, insets }}>
        <ThemeProvider>
          <GoalScreen draft={emptyDraft} onChange={jest.fn()} onNext={jest.fn()} />
        </ThemeProvider>
      </SafeAreaProvider>,
    );

    expect(screen.getByTestId('step-screen')).toHaveStyle({ paddingTop: insets.top, paddingBottom: insets.bottom });
  });

  test('scrolls the cards and keeps the button in a footer above the keyboard, with text that grows to a limit', async () => {
    await renderGoal();

    const scroll = screen.getByTestId('screen-scroll');
    expect(within(scroll).getAllByRole('radio')).toHaveLength(3);
    expect(within(scroll).queryByRole('button', { name: 'Continue' })).toBeNull();
    expect(within(screen.getByTestId('screen-footer')).getByRole('button', { name: 'Continue' })).toBeOnTheScreen();
    expect(screen.getByTestId('screen-keyboard-avoider')).toBeOnTheScreen();
    expect(screen.getByText('Build Muscle')).toHaveProp('maxFontSizeMultiplier', layout.maxFontScale);
    expect(screen.getByText('Gain strength and build lean muscle mass.')).toHaveProp(
      'maxFontSizeMultiplier',
      layout.maxFontScale,
    );
  });
});
