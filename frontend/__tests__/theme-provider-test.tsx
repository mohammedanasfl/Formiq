import { Appearance, Pressable, Text } from 'react-native';
import { fireEvent, render, screen } from '@testing-library/react-native';
import * as SystemUI from 'expo-system-ui';

import { darkColors, lightColors, ThemeProvider, useTheme } from '../src/theme';

jest.mock('expo-system-ui', () => ({
  setBackgroundColorAsync: jest.fn(() => Promise.resolve()),
}));

function Probe() {
  const { scheme, colors, setScheme } = useTheme();

  return (
    <>
      <Text testID="scheme">{scheme}</Text>
      <Text testID="background">{colors.background}</Text>
      <Pressable accessibilityRole="button" onPress={() => setScheme('light')}>
        <Text>Use light</Text>
      </Pressable>
      <Pressable accessibilityRole="button" onPress={() => setScheme('dark')}>
        <Text>Use dark</Text>
      </Pressable>
    </>
  );
}

describe('ThemeProvider', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.spyOn(Appearance, 'setColorScheme').mockImplementation(() => undefined);
  });

  test('is dark by default', async () => {
    await render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );

    expect(screen.getByTestId('scheme')).toHaveTextContent('dark');
    expect(screen.getByTestId('background')).toHaveTextContent(darkColors.background);
  });

  test('can start in the light theme', async () => {
    await render(
      <ThemeProvider initialScheme="light">
        <Probe />
      </ThemeProvider>,
    );

    expect(screen.getByTestId('scheme')).toHaveTextContent('light');
    expect(screen.getByTestId('background')).toHaveTextContent(lightColors.background);
  });

  test('switches theme programmatically, both ways', async () => {
    await render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );

    await fireEvent.press(screen.getByRole('button', { name: 'Use light' }));
    expect(screen.getByTestId('scheme')).toHaveTextContent('light');
    expect(screen.getByTestId('background')).toHaveTextContent(lightColors.background);

    await fireEvent.press(screen.getByRole('button', { name: 'Use dark' }));
    expect(screen.getByTestId('scheme')).toHaveTextContent('dark');
    expect(screen.getByTestId('background')).toHaveTextContent(darkColors.background);
  });

  test('keeps the native color scheme and the root background in step with the theme', async () => {
    await render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );

    expect(Appearance.setColorScheme).toHaveBeenLastCalledWith('dark');
    expect(SystemUI.setBackgroundColorAsync).toHaveBeenLastCalledWith(darkColors.background);

    await fireEvent.press(screen.getByRole('button', { name: 'Use light' }));

    expect(Appearance.setColorScheme).toHaveBeenLastCalledWith('light');
    expect(SystemUI.setBackgroundColorAsync).toHaveBeenLastCalledWith(lightColors.background);
  });

  test('useTheme outside a provider fails loudly', async () => {
    jest.spyOn(console, 'error').mockImplementation(() => undefined);

    await expect(render(<Probe />)).rejects.toThrow('useTheme must be used inside a <ThemeProvider>');
  });
});
