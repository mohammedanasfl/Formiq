import { act, fireEvent, screen, within } from '@testing-library/react-native';
import { Keyboard, StyleSheet, Text } from 'react-native';

import {
  AppScreen,
  AppText,
  ChoiceChips,
  FieldError,
  LinkButton,
  Notice,
  OptionCard,
  PasswordInput,
  ProgressSteps,
} from '../src/components';
import { darkColors, layout, lightColors } from '../src/theme';
import { renderWithTheme } from '../test-utils/renderWithTheme';

describe('<ProgressSteps />', () => {
  test('reads as one progress value, and fills the steps reached', async () => {
    await renderWithTheme(<ProgressSteps current={3} total={6} />);

    const progress = screen.getByRole('progressbar');
    expect(progress).toHaveAccessibleName('Step 3 of 6');
    expect(progress).toHaveProp('accessibilityValue', { min: 1, max: 6, now: 3 });
    screen.getByText('Step 3 of 6', { includeHiddenElements: true });
    for (const reached of [1, 2, 3]) {
      expect(screen.getByTestId(`progress-segment-${reached}`)).toHaveStyle({ backgroundColor: darkColors.primary });
    }
    for (const ahead of [4, 5, 6]) {
      expect(screen.getByTestId(`progress-segment-${ahead}`)).toHaveStyle({ backgroundColor: darkColors.border });
    }
  });

  test('uses the light theme colors', async () => {
    await renderWithTheme(<ProgressSteps current={1} total={2} />, 'light');

    expect(screen.getByTestId('progress-segment-1')).toHaveStyle({ backgroundColor: lightColors.primary });
    expect(screen.getByTestId('progress-segment-2')).toHaveStyle({ backgroundColor: lightColors.border });
  });

  test('compact: short, equal segments in a centered row, with no printed step text', async () => {
    await renderWithTheme(<ProgressSteps current={2} total={6} compact />, 'light');

    const progress = screen.getByRole('progressbar');
    expect(progress).toHaveAccessibleName('Step 2 of 6');
    expect(progress).toHaveProp('accessibilityValue', { min: 1, max: 6, now: 2 });
    expect(progress).toHaveStyle({ alignSelf: 'center' });
    expect(screen.queryByText('Step 2 of 6', { includeHiddenElements: true })).toBeNull();
    for (let segment = 1; segment <= 6; segment++) {
      const style = screen.getByTestId(`progress-segment-${segment}`);
      expect(style).toHaveStyle({ width: 20, height: 4 });
      // the steps ahead are drawn a little stronger than in the full bar, to show on a photo
      expect(style).toHaveStyle({ backgroundColor: segment <= 2 ? lightColors.primary : lightColors.borderStrong });
    }
  });
});

describe('<OptionCard />', () => {
  // the icon, the indicator and the check are decoration, hidden from screen readers
  const HIDDEN = { includeHiddenElements: true };

  test('is a radio that reports whether it is checked, and can be pressed', async () => {
    const onPress = jest.fn();
    await renderWithTheme(
      <>
        <OptionCard title="Gym" description="A gym" selected onPress={onPress} />
        <OptionCard title="Home" selected={false} onPress={onPress} />
      </>,
    );

    expect(screen.getByRole('radio', { name: /Gym/ })).toBeChecked();
    expect(screen.getByRole('radio', { name: /Gym/ })).toHaveAccessibleName('Gym. A gym');
    expect(screen.getByRole('radio', { name: 'Home' })).not.toBeChecked();
    await fireEvent.press(screen.getByRole('radio', { name: 'Home' }));
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  test('can be a checkbox for choosing several', async () => {
    await renderWithTheme(<OptionCard role="checkbox" title="Dumbbell" selected onPress={jest.fn()} />);

    expect(screen.getByRole('checkbox', { name: 'Dumbbell' })).toBeChecked();
  });

  test('shows selected with an emerald outline, a tint and a filled radio, not by color alone', async () => {
    await renderWithTheme(
      <>
        <OptionCard title="On" icon="dumbbell" selected onPress={jest.fn()} />
        <OptionCard title="Off" icon="dumbbell" selected={false} onPress={jest.fn()} />
      </>,
    );

    expect(screen.getByRole('radio', { name: 'On' })).toHaveStyle({
      borderColor: darkColors.accent,
      borderWidth: layout.borderWidth.thick,
      backgroundColor: `${darkColors.primarySubtle}E6`,
    });
    expect(screen.getByRole('radio', { name: 'Off' })).toHaveStyle({
      borderColor: darkColors.borderStrong,
      borderWidth: layout.borderWidth.thin,
      backgroundColor: `${darkColors.surface}E6`,
    });
    // the radio is drawn but hidden from screen readers, which hear "checked" instead
    expect(screen.getAllByTestId('option-indicator', HIDDEN)).toHaveLength(2);
    expect(screen.queryByTestId('option-indicator')).toBeNull();
    expect(within(screen.getByRole('radio', { name: 'On' })).getByTestId('option-indicator-dot', HIDDEN)).toHaveStyle({
      backgroundColor: darkColors.accent,
    });
    expect(screen.getAllByTestId('option-indicator-dot', HIDDEN)).toHaveLength(1);
  });

  test('draws a checkbox as a square that fills with a check when selected', async () => {
    await renderWithTheme(
      <>
        <OptionCard role="checkbox" title="On" selected onPress={jest.fn()} />
        <OptionCard role="checkbox" title="Off" selected={false} onPress={jest.fn()} />
      </>,
    );

    const [on, off] = screen.getAllByTestId('option-indicator', HIDDEN);
    expect(on).toHaveStyle({ backgroundColor: darkColors.accent, borderColor: darkColors.accent });
    expect(off).toHaveStyle({ backgroundColor: 'transparent', borderColor: darkColors.borderStrong });
    expect(screen.getAllByTestId('check-mark', HIDDEN)).toHaveLength(1);
    expect(screen.queryByTestId('option-indicator-dot', HIDDEN)).toBeNull();
  });

  test('has no icon column when it has no icon, and keeps its size when selected', async () => {
    await renderWithTheme(
      <>
        <OptionCard title="Plain" selected onPress={jest.fn()} />
        <OptionCard title="Plain too" selected={false} onPress={jest.fn()} />
      </>,
    );

    expect(screen.queryByTestId(/^icon-/, HIDDEN)).toBeNull();
    const room = (name: string) => {
      const { padding, borderWidth } = StyleSheet.flatten(screen.getByRole('radio', { name }).props.style);
      return padding + borderWidth;
    };
    expect(room('Plain')).toBe(room('Plain too'));
  });

  test('as a chip it is a touch target tall, shows its icon, and swaps it for a check when selected', async () => {
    await renderWithTheme(
      <>
        <OptionCard variant="chip" role="checkbox" icon="dumbbell" title="Dumbbell" selected={false} onPress={jest.fn()} />
        <OptionCard variant="chip" role="checkbox" icon="kettlebell" title="Kettlebell" selected onPress={jest.fn()} />
      </>,
    );

    const off = screen.getByRole('checkbox', { name: 'Dumbbell' });
    const on = screen.getByRole('checkbox', { name: 'Kettlebell' });
    expect(off).toHaveStyle({ minHeight: layout.touchTarget, borderColor: darkColors.borderStrong });
    expect(on).toHaveStyle({ minHeight: layout.touchTarget, borderColor: darkColors.accent, borderWidth: layout.borderWidth.thick });
    expect(within(off).getByTestId('icon-dumbbell', HIDDEN)).toBeOnTheScreen();
    expect(within(off).queryByTestId('check-mark', HIDDEN)).toBeNull();
    expect(within(on).queryByTestId('icon-kettlebell', HIDDEN)).toBeNull();
    expect(within(on).getByTestId('check-mark', HIDDEN)).toHaveStyle({ borderColor: darkColors.accent });
    // a chip has no indicator at its end: the check is where the icon was
    expect(screen.queryByTestId('option-indicator', HIDDEN)).toBeNull();
    // the width does not depend on the state: the icon and the check take the same square
    const room = (element: typeof on) => {
      const { padding, borderWidth } = StyleSheet.flatten(element.props.style);
      return padding + borderWidth;
    };
    expect(room(on)).toBe(room(off));
  });

  test('is a touch target tall and follows the theme it is given', async () => {
    await renderWithTheme(<OptionCard title="Gym" selected={false} onPress={jest.fn()} />, 'light');

    // the screens that use it are fixed dark; the card itself reads its colors from the theme
    const style = StyleSheet.flatten(screen.getByRole('radio').props.style);
    expect(style.minHeight).toBeGreaterThanOrEqual(layout.touchTarget);
    expect(screen.getByRole('radio')).toHaveStyle({
      borderColor: lightColors.borderStrong,
      backgroundColor: `${lightColors.surface}E6`,
    });
  });
});

describe('<ChoiceChips />', () => {
  const OPTIONS = [
    { value: 'a', label: 'Alpha' },
    { value: 'b', label: 'Beta' },
  ];

  test('is a labelled group of radios, one of them checked', async () => {
    await renderWithTheme(<ChoiceChips label="Pick" options={OPTIONS} value="b" onChange={jest.fn()} />);

    // a group is not itself focusable (that would hide the options inside it), so it has no role query
    expect(screen.getByLabelText('Pick')).toHaveProp('accessibilityRole', 'radiogroup');
    expect(screen.getByRole('radio', { name: 'Beta' })).toBeChecked();
    expect(screen.getByRole('radio', { name: 'Alpha' })).not.toBeChecked();
    expect(screen.getByRole('radio', { name: 'Alpha' })).toHaveStyle({ minHeight: layout.touchTarget });
  });

  test('reports the value pressed, text or number', async () => {
    const onText = jest.fn();
    const onNumber = jest.fn();
    await renderWithTheme(
      <>
        <ChoiceChips label="Text" options={OPTIONS} value={null} onChange={onText} />
        <ChoiceChips
          label="Number"
          options={[{ value: 3, label: '3' }]}
          value={null}
          onChange={onNumber}
        />
      </>,
    );

    await fireEvent.press(screen.getByRole('radio', { name: 'Alpha' }));
    await fireEvent.press(screen.getByRole('radio', { name: '3' }));

    expect(onText).toHaveBeenCalledWith('a');
    expect(onNumber).toHaveBeenCalledWith(3);
  });

  test('shows an error as an announced alert, replacing the helper text', async () => {
    await renderWithTheme(
      <ChoiceChips label="Pick" options={OPTIONS} value={null} onChange={jest.fn()} helperText="Help" error="Choose one." />,
    );

    expect(screen.getByRole('alert')).toHaveTextContent('Choose one.');
    expect(screen.getByRole('alert')).toHaveProp('accessibilityLiveRegion', 'polite');
    expect(screen.queryByText('Help')).toBeNull();
  });

  test('shows helper text when there is no error', async () => {
    await renderWithTheme(<ChoiceChips label="Pick" options={OPTIONS} value={null} onChange={jest.fn()} helperText="Help" />);

    screen.getByText('Help');
    expect(screen.queryByRole('alert')).toBeNull();
  });

  test('the chosen chip is outlined in emerald and tinted, the others are plain', async () => {
    await renderWithTheme(<ChoiceChips label="Pick" options={OPTIONS} value="b" onChange={jest.fn()} />);

    expect(screen.getByRole('radio', { name: 'Beta' })).toHaveStyle({
      borderColor: darkColors.accent,
      borderWidth: layout.borderWidth.thick,
      backgroundColor: darkColors.primarySubtle,
    });
    expect(screen.getByRole('radio', { name: 'Alpha' })).toHaveStyle({
      borderColor: darkColors.borderStrong,
      borderWidth: layout.borderWidth.thin,
      backgroundColor: darkColors.surface,
    });
    expect(screen.getByText('Beta')).toHaveStyle({ color: darkColors.textPrimary });
  });

  test('with columns, the chips are equal in width, a touch target tall, and none is lost', async () => {
    const days = [1, 2, 3, 4, 5, 6, 7].map((day) => ({ value: day, label: String(day) }));
    await renderWithTheme(<ChoiceChips label="Days" options={days} value={null} onChange={jest.fn()} columns={4} />);

    const chips = screen.getAllByRole('radio');
    expect(chips.map((chip) => chip.props.accessibilityState.checked)).toEqual(Array(7).fill(false));
    for (const chip of chips) {
      expect(chip).toHaveStyle({ flex: 1, minHeight: layout.touchTarget });
    }
    expect(screen.getByRole('radio', { name: '7' })).toBeOnTheScreen();
  });

  test('keeps the size of a chip when its border grows: the padding gives back what the border takes', async () => {
    await renderWithTheme(<ChoiceChips label="Pick" options={OPTIONS} value="a" onChange={jest.fn()} />);

    const room = (name: string) => {
      const { paddingHorizontal, borderWidth } = StyleSheet.flatten(screen.getByRole('radio', { name }).props.style);
      return paddingHorizontal + borderWidth;
    };
    expect(room('Alpha')).toBe(room('Beta'));
  });
});

describe('<PasswordInput />', () => {
  test('hides the password until asked, and the toggle says what it will do', async () => {
    await renderWithTheme(<PasswordInput label="Password" value="secret" onChangeText={jest.fn()} />);

    const field = screen.getByLabelText('Password');
    expect(field).toHaveProp('secureTextEntry', true);
    expect(field).toHaveProp('autoCapitalize', 'none');
    expect(field).toHaveProp('autoCorrect', false);

    await fireEvent.press(screen.getByRole('button', { name: 'Show password' }));
    expect(screen.getByLabelText('Password')).toHaveProp('secureTextEntry', false);
    expect(screen.getByRole('button', { name: 'Hide password' })).toBeOnTheScreen();
    expect(screen.queryByRole('button', { name: 'Show password' })).toBeNull();

    await fireEvent.press(screen.getByRole('button', { name: 'Hide password' }));
    expect(screen.getByLabelText('Password')).toHaveProp('secureTextEntry', true);
  });

  test('the toggle is a touch target, and the field keeps its validation message', async () => {
    await renderWithTheme(
      <PasswordInput label="Password" value="" onChangeText={jest.fn()} error="Use at least 8 characters." />,
    );

    expect(screen.getByRole('button', { name: 'Show password' })).toHaveStyle({
      minHeight: layout.touchTarget,
      minWidth: layout.touchTarget,
    });
    expect(screen.getByRole('alert')).toHaveTextContent('Use at least 8 characters.');
  });
});

describe('<Notice />', () => {
  test('an error is one announced element, in the error color', async () => {
    await renderWithTheme(<Notice tone="error" title="Oops">Something failed.</Notice>);

    const alert = screen.getByRole('alert');
    expect(alert).toHaveProp('accessible', true);
    expect(alert).toHaveProp('accessibilityLiveRegion', 'polite');
    expect(alert).toHaveStyle({ borderColor: darkColors.error });
    expect(screen.getByText('Something failed.')).toHaveStyle({ color: darkColors.error });
  });

  test('an info note is not an alert', async () => {
    await renderWithTheme(<Notice title="Not saved yet">Details.</Notice>);

    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.getByText('Not saved yet')).toHaveStyle({ color: darkColors.textPrimary });
    expect(screen.getByText('Details.')).toHaveStyle({ color: darkColors.textSecondary });
  });

  test('follows the light theme', async () => {
    await renderWithTheme(<Notice tone="error">Failed.</Notice>, 'light');

    expect(screen.getByRole('alert')).toHaveStyle({
      borderColor: lightColors.error,
      backgroundColor: lightColors.surface,
    });
  });
});

describe('<LinkButton /> and <FieldError />', () => {
  test('a link is as tall as a button and can be pressed', async () => {
    const onPress = jest.fn();
    await renderWithTheme(<LinkButton label="Edit" accessibilityLabel="Edit goal" onPress={onPress} />);

    const link = screen.getByRole('link', { name: 'Edit goal' });
    expect(link).toHaveStyle({ minHeight: layout.touchTarget });
    await fireEvent.press(link);
    expect(onPress).toHaveBeenCalledTimes(1);
    expect(screen.getByText('Edit')).toHaveStyle({ color: darkColors.accent });
  });

  test('a field error is announced', async () => {
    await renderWithTheme(<FieldError>Choose one.</FieldError>);

    expect(screen.getByRole('alert')).toHaveTextContent('Choose one.');
    expect(screen.getByRole('alert')).toHaveProp('accessibilityLiveRegion', 'polite');
    expect(screen.getByRole('alert')).toHaveStyle({ color: darkColors.error });
  });
});

describe('<AppScreen scrollable />', () => {
  test('scrolls its content, keeps taps working with the keyboard open, and dismisses it on drag', async () => {
    await renderWithTheme(
      <AppScreen scrollable footer={<Text>Footer</Text>}>
        <AppText>Content</AppText>
      </AppScreen>,
    );

    const scroll = screen.getByTestId('screen-scroll');
    expect(scroll).toHaveProp('keyboardShouldPersistTaps', 'handled');
    expect(scroll).toHaveProp('keyboardDismissMode', 'on-drag');
    expect(within(scroll).getByText('Content')).toBeOnTheScreen();
  });

  test('makes room for the keyboard when it opens, and gives it back when it closes', async () => {
    // Jest has no real keyboard: catch the listener the screen registers and call it as the system would.
    const listeners = new Map<string, (event: unknown) => void>();
    jest.spyOn(Keyboard, 'addListener').mockImplementation(((name: string, listener: (event: unknown) => void) => {
      listeners.set(name, listener);
      return { remove: () => listeners.delete(name) };
    }) as never);
    const keyboardOpens = () =>
      act(async () => {
        listeners.get('keyboardWillShow')?.({
          duration: 0,
          easing: 'keyboard',
          endCoordinates: { screenX: 0, screenY: 500, width: 360, height: 300 },
        });
      });
    const keyboardCloses = () => act(async () => listeners.get('keyboardWillHide')?.({}));

    await renderWithTheme(<AppScreen scrollable />);
    await fireEvent(screen.getByTestId('screen-keyboard-avoider'), 'layout', {
      nativeEvent: { layout: { x: 0, y: 0, width: 360, height: 800 } },
      persist: () => undefined,
    });

    expect(listeners.has('keyboardWillShow')).toBe(true);
    await keyboardOpens();
    expect(screen.getByTestId('screen-keyboard-avoider')).toHaveStyle({ paddingBottom: 300 });

    await keyboardCloses();
    expect(screen.getByTestId('screen-keyboard-avoider')).toHaveStyle({ paddingBottom: 0 });
  });

  test('keeps the footer outside the scrolling content, so it is always in reach', async () => {
    await renderWithTheme(
      <AppScreen scrollable footer={<Text>Footer</Text>}>
        <AppText>Content</AppText>
      </AppScreen>,
    );

    expect(within(screen.getByTestId('screen-scroll')).queryByText('Footer')).toBeNull();
    expect(within(screen.getByTestId('screen-footer')).getByText('Footer')).toBeOnTheScreen();
  });

  test('draws no footer area when there is no footer', async () => {
    await renderWithTheme(<AppScreen scrollable />);

    expect(screen.queryByTestId('screen-footer')).toBeNull();
  });
});
