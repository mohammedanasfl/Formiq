import { fireEvent, screen } from '@testing-library/react-native';

import { AppButton } from '../src/components';
import { darkColors, layout, lightColors } from '../src/theme';
import { renderWithTheme } from '../test-utils/renderWithTheme';

describe('<AppButton />', () => {
  test('is a primary button by default, and accessible as a button', async () => {
    await renderWithTheme(<AppButton label="Start" onPress={jest.fn()} />);

    const button = screen.getByRole('button', { name: 'Start' });
    expect(button).toBeEnabled();
    expect(button).toHaveStyle({
      backgroundColor: darkColors.primary,
      borderColor: darkColors.primary,
    });
    expect(screen.getByText('Start')).toHaveStyle({ color: darkColors.textOnPrimary });
  });

  test('is at least a touch target tall', async () => {
    await renderWithTheme(<AppButton label="Start" onPress={jest.fn()} />);

    expect(screen.getByRole('button')).toHaveStyle({ minHeight: layout.touchTarget });
  });

  test('the secondary variant is an outlined surface', async () => {
    await renderWithTheme(<AppButton label="Later" variant="secondary" onPress={jest.fn()} />);

    expect(screen.getByRole('button', { name: 'Later' })).toHaveStyle({
      backgroundColor: darkColors.surface,
      borderColor: darkColors.borderStrong,
    });
    expect(screen.getByText('Later')).toHaveStyle({ color: darkColors.textPrimary });
  });

  test('the overlay variant is a see-through dark fill with the secondary outline, for use on a photo', async () => {
    await renderWithTheme(<AppButton label="Later" variant="overlay" onPress={jest.fn()} />);

    const button = screen.getByRole('button', { name: 'Later' });
    expect(button).toHaveStyle({
      backgroundColor: `${darkColors.background}99`,
      borderColor: darkColors.borderStrong,
    });
    expect(screen.getByText('Later')).toHaveStyle({ color: darkColors.textPrimary });

    // pressed: a lighter, more solid fill, so the press is seen
    await fireEvent(button, 'responderGrant', {
      nativeEvent: { touches: [], changedTouches: [], timestamp: 0 },
      persist: () => undefined,
    });
    expect(screen.getByRole('button', { name: 'Later' })).toHaveStyle({
      backgroundColor: `${darkColors.surfaceMuted}CC`,
    });
  });

  test('calls onPress when pressed', async () => {
    const onPress = jest.fn();
    await renderWithTheme(<AppButton label="Start" onPress={onPress} />);

    await fireEvent.press(screen.getByRole('button', { name: 'Start' }));

    expect(onPress).toHaveBeenCalledTimes(1);
  });

  test.each(['primary', 'secondary', 'overlay'] as const)(
    'a disabled %s button ignores presses and says it is disabled',
    async (variant) => {
      const onPress = jest.fn();
      await renderWithTheme(
        <AppButton label="Start" variant={variant} disabled onPress={onPress} />,
      );

      const button = screen.getByRole('button', { name: 'Start' });
      await fireEvent.press(button);

      expect(onPress).not.toHaveBeenCalled();
      expect(button).toBeDisabled();
      expect(button).toHaveProp('accessibilityState', { disabled: true });
      expect(button).toHaveStyle({ backgroundColor: darkColors.disabledBackground });
      expect(screen.getByText('Start')).toHaveStyle({ color: darkColors.disabledText });
    },
  );

  test('an enabled button reports enabled', async () => {
    await renderWithTheme(<AppButton label="Start" onPress={jest.fn()} />);

    expect(screen.getByRole('button')).toHaveProp('accessibilityState', { disabled: false });
  });

  test('passes an accessibility hint to the screen reader', async () => {
    await renderWithTheme(
      <AppButton label="Approve" accessibilityHint="Saves this plan" onPress={jest.fn()} />,
    );

    expect(screen.getByRole('button', { name: 'Approve' })).toHaveProp(
      'accessibilityHint',
      'Saves this plan',
    );
  });

  test('uses the light theme colors', async () => {
    await renderWithTheme(
      <>
        <AppButton label="Primary" onPress={jest.fn()} />
        <AppButton label="Secondary" variant="secondary" onPress={jest.fn()} />
      </>,
      'light',
    );

    expect(screen.getByRole('button', { name: 'Primary' })).toHaveStyle({
      backgroundColor: lightColors.primary,
    });
    expect(screen.getByText('Primary')).toHaveStyle({ color: lightColors.textOnPrimary });
    expect(screen.getByRole('button', { name: 'Secondary' })).toHaveStyle({
      backgroundColor: lightColors.surface,
      borderColor: lightColors.borderStrong,
    });
  });

  test('darkens or lightens while pressed', async () => {
    await renderWithTheme(<AppButton label="Start" onPress={jest.fn()} />);
    const button = screen.getByRole('button', { name: 'Start' });

    await fireEvent(button, 'responderGrant', {
      nativeEvent: { touches: [], changedTouches: [], timestamp: 0 },
      persist: () => undefined,
    });

    expect(screen.getByRole('button', { name: 'Start' })).toHaveStyle({
      backgroundColor: darkColors.primaryPressed,
    });
  });

  test('is named by its label whatever its state', async () => {
    await renderWithTheme(
      <>
        <AppButton label="Idle" onPress={jest.fn()} />
        <AppButton label="Off" disabled onPress={jest.fn()} />
        <AppButton label="Working…" loading onPress={jest.fn()} />
      </>,
    );

    for (const name of ['Idle', 'Off', 'Working…']) {
      expect(screen.getByRole('button', { name })).toHaveProp('accessibilityLabel', name);
    }
    // a `busy` state replaced the name on Android ("busy" instead of the label): it is never set
    for (const button of screen.getAllByRole('button')) {
      expect(button.props.accessibilityState?.busy).toBeUndefined();
    }
  });

  test('while loading it ignores presses, is disabled and keeps its normal colors', async () => {
    const onPress = jest.fn();
    await renderWithTheme(<AppButton label="Saving…" loading onPress={onPress} />);

    const button = screen.getByRole('button', { name: 'Saving…' });
    await fireEvent.press(button);

    expect(onPress).not.toHaveBeenCalled();
    expect(button).toBeDisabled();
    expect(button).toHaveProp('accessibilityState', { disabled: true });
    expect(button).toHaveStyle({ backgroundColor: darkColors.primary });
    expect(screen.getByText('Saving…')).toHaveStyle({ color: darkColors.textOnPrimary });
  });

  test('lets a caller adjust the layout style', async () => {
    await renderWithTheme(
      <AppButton label="Start" onPress={jest.fn()} style={{ marginTop: 16 }} />,
    );

    expect(screen.getByRole('button')).toHaveStyle({
      marginTop: 16,
      backgroundColor: darkColors.primary,
    });
  });
});

describe('<AppButton /> leading icon and compact size', () => {
  const HIDDEN = { includeHiddenElements: true };

  test('a leading icon sits before the label, is hidden from screen readers, and does not rename the button', async () => {
    await renderWithTheme(<AppButton label="Start Workout" leadingIcon="play" trailingIcon="arrow-right" onPress={jest.fn()} />);

    const button = screen.getByRole('button', { name: 'Start Workout' });
    const children = button.children as { props?: { testID?: string } }[];
    // the icon, the label, the other icon: in that order
    expect(children[0].props?.testID).toBe('icon-play');
    expect(children[children.length - 1].props?.testID).toBe('icon-arrow-right');
    expect(screen.getByTestId('icon-play', HIDDEN)).toHaveProp('accessibilityElementsHidden', true);
  });

  test('a leading icon is not shown while the button is loading: the spinner takes its place', async () => {
    await renderWithTheme(<AppButton label="Saving…" leadingIcon="play" loading onPress={jest.fn()} />);

    expect(screen.queryByTestId('icon-play', HIDDEN)).toBeNull();
  });

  test('a compact button is slimmer, with a narrower label, but its touch area is still a full target', async () => {
    await renderWithTheme(<AppButton label="Edit" compact onPress={jest.fn()} />);

    const button = screen.getByRole('button', { name: 'Edit' });
    expect(button).toHaveStyle({ minHeight: 34, paddingHorizontal: 16 });
    // 34 dp of button and 7 dp of reach on each side make 48
    expect(button).toHaveProp('hitSlop', (layout.touchTarget - 34) / 2);
    expect(34 + 2 * (layout.touchTarget - 34) / 2).toBe(layout.touchTarget);
    expect(screen.getByText('Edit')).toHaveStyle({ fontSize: 13.5 });
  });

  test('an ordinary button is a full target by itself, and has no extra reach', async () => {
    await renderWithTheme(<AppButton label="Edit" onPress={jest.fn()} />);

    const button = screen.getByRole('button', { name: 'Edit' });
    expect(button).toHaveStyle({ minHeight: layout.touchTarget });
    expect(button.props.hitSlop).toBeUndefined();
  });
});

