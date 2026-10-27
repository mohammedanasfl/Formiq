import { createRef, useState, type ComponentRef } from 'react';
import { StyleSheet, Text, TextInput } from 'react-native';
import { fireEvent, screen, userEvent } from '@testing-library/react-native';

import { AppInput } from '../src/components';
import { darkColors, layout, lightColors, spacing } from '../src/theme';
import { renderWithTheme } from '../test-utils/renderWithTheme';

describe('<AppInput />', () => {
  test('the field carries its label as its accessible name', async () => {
    await renderWithTheme(<AppInput label="Email" value="" onChangeText={jest.fn()} />);

    const input = screen.getByLabelText('Email');
    expect(input).toBeOnTheScreen();
    expect(input).toHaveAccessibleName('Email');
  });

  test('shows the label, but hides the visible copy from screen readers', async () => {
    await renderWithTheme(<AppInput label="Email" value="" onChangeText={jest.fn()} />);

    // Hidden elements are left out of queries by default, so the visible label needs the option.
    expect(screen.queryByText('Email')).toBeNull();
    const label = screen.getByText('Email', { includeHiddenElements: true });
    expect(label).toHaveProp('accessibilityElementsHidden', true);
    expect(label).toHaveProp('importantForAccessibility', 'no');
    expect(label).toHaveStyle({ color: darkColors.textSecondary });
  });

  test('with hideLabel, prints no label, and still names the field and shows its messages', async () => {
    await renderWithTheme(
      <AppInput label="Height (cm)" hideLabel value="" onChangeText={jest.fn()} error="Enter a height." />,
    );

    expect(screen.queryByText('Height (cm)', { includeHiddenElements: true })).toBeNull();
    expect(screen.getByLabelText('Height (cm)')).toHaveAccessibleName('Height (cm)');
    expect(screen.getByRole('alert')).toHaveTextContent('Enter a height.');
  });

  test('shows what the user types', async () => {
    function Name() {
      const [value, setValue] = useState('');
      return <AppInput label="Name" value={value} onChangeText={setValue} />;
    }
    await renderWithTheme(<Name />);

    await userEvent.setup().type(screen.getByLabelText('Name'), 'Sam');

    expect(screen.getByLabelText('Name')).toHaveDisplayValue('Sam');
  });

  test('is a touch-target tall field with a visible outline', async () => {
    await renderWithTheme(<AppInput label="Name" value="" onChangeText={jest.fn()} />);

    expect(screen.getByLabelText('Name')).toHaveStyle({
      minHeight: layout.touchTarget,
      borderWidth: layout.borderWidth.thin,
      borderColor: darkColors.borderStrong,
      backgroundColor: darkColors.surface,
      color: darkColors.textPrimary,
    });
  });

  test('shows helper text, and exposes it as the accessibility hint', async () => {
    await renderWithTheme(
      <AppInput label="Email" helperText="We never share it" value="" onChangeText={jest.fn()} />,
    );

    expect(screen.getByText('We never share it')).toHaveStyle({ color: darkColors.textMuted });
    expect(screen.getByLabelText('Email')).toHaveProp('accessibilityHint', 'We never share it');
    expect(screen.queryByRole('alert')).toBeNull();
  });

  test('an error replaces the helper text, is announced, and outlines the field', async () => {
    await renderWithTheme(
      <AppInput
        label="Email"
        helperText="We never share it"
        error="Enter a valid email"
        value=""
        onChangeText={jest.fn()}
      />,
    );

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('Enter a valid email');
    expect(alert).toHaveProp('accessibilityLiveRegion', 'polite');
    expect(alert).toHaveStyle({ color: darkColors.error });
    expect(screen.queryByText('We never share it')).toBeNull();

    const input = screen.getByLabelText('Email');
    expect(input).toHaveProp('accessibilityHint', 'Enter a valid email');
    expect(input).toHaveStyle({
      borderColor: darkColors.error,
      borderWidth: layout.borderWidth.thick,
    });
  });

  test('highlights the field while focused, then returns to normal', async () => {
    const onFocus = jest.fn();
    const onBlur = jest.fn();
    await renderWithTheme(
      <AppInput label="Name" value="" onChangeText={jest.fn()} onFocus={onFocus} onBlur={onBlur} />,
    );
    const input = screen.getByLabelText('Name');

    await fireEvent(input, 'focus');
    expect(screen.getByLabelText('Name')).toHaveStyle({
      borderColor: darkColors.accent,
      borderWidth: layout.borderWidth.thick,
      // The border grows by 1, so the padding shrinks by 1 and the text does not move.
      paddingLeft: spacing.lg - layout.borderWidth.thick,
      paddingRight: spacing.lg - layout.borderWidth.thick,
    });
    expect(onFocus).toHaveBeenCalledTimes(1);

    await fireEvent(input, 'blur');
    expect(screen.getByLabelText('Name')).toHaveStyle({
      borderColor: darkColors.borderStrong,
      borderWidth: layout.borderWidth.thin,
      paddingLeft: spacing.lg - layout.borderWidth.thin,
      paddingRight: spacing.lg - layout.borderWidth.thin,
    });
    expect(onBlur).toHaveBeenCalledTimes(1);
  });

  test('a disabled field is not editable, says so, and shows no error', async () => {
    await renderWithTheme(
      <AppInput label="Email" disabled error="Ignored" value="a@b.c" onChangeText={jest.fn()} />,
    );

    const input = screen.getByLabelText('Email');
    expect(input).toHaveProp('editable', false);
    expect(input).toHaveProp('accessibilityState', { disabled: true });
    expect(input).toHaveStyle({
      backgroundColor: darkColors.disabledBackground,
      color: darkColors.disabledText,
      borderColor: darkColors.border,
    });
    expect(screen.queryByRole('alert')).toBeNull();
  });

  test('passes other text input props through', async () => {
    await renderWithTheme(
      <AppInput
        label="Password"
        secureTextEntry
        placeholder="At least 8 characters"
        value=""
        onChangeText={jest.fn()}
      />,
    );

    const input = screen.getByLabelText('Password');
    expect(input).toHaveProp('secureTextEntry', true);
    expect(input).toHaveProp('placeholder', 'At least 8 characters');
    expect(input).toHaveProp('placeholderTextColor', darkColors.textMuted);
  });

  test('shows something at the end of the field and keeps the text clear of it', async () => {
    await renderWithTheme(
      <>
        <AppInput label="With" trailing={<Text>cm</Text>} value="" onChangeText={jest.fn()} />
        <AppInput label="Without" value="" onChangeText={jest.fn()} />
      </>,
    );

    expect(screen.getByText('cm')).toBeOnTheScreen();
    const withTrailing = screen.getByLabelText('With');
    const without = screen.getByLabelText('Without');
    const paddingRight = (element: typeof withTrailing) =>
      (StyleSheet.flatten(element.props.style) as { paddingRight: number }).paddingRight;
    expect(paddingRight(withTrailing)).toBeGreaterThan(paddingRight(without));
    expect(paddingRight(withTrailing)).toBeGreaterThanOrEqual(layout.touchTarget);
  });

  test('forwards its ref to the text field', async () => {
    const ref = createRef<ComponentRef<typeof TextInput>>();
    await renderWithTheme(<AppInput ref={ref} label="Name" value="" onChangeText={jest.fn()} />);

    expect(ref.current).not.toBeNull();
  });

  test('uses the light theme colors', async () => {
    await renderWithTheme(
      <AppInput label="Email" error="Enter a valid email" value="" onChangeText={jest.fn()} />,
      'light',
    );

    expect(screen.getByLabelText('Email')).toHaveStyle({
      borderColor: lightColors.error,
      backgroundColor: lightColors.surface,
      color: lightColors.textPrimary,
    });
    expect(screen.getByRole('alert')).toHaveStyle({ color: lightColors.error });
  });
});
