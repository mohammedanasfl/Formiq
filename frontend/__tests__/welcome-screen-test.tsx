import { Dimensions, StyleSheet } from 'react-native';
import { fireEvent, render, screen } from '@testing-library/react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { AppText } from '../src/components';
import { WelcomeScreen } from '../src/onboarding/screens/WelcomeScreen';
import { layout, spacing, themes, ThemeProvider, useTheme } from '../src/theme';
import { renderWithTheme } from '../test-utils/renderWithTheme';

const dark = themes.dark.colors;

async function renderWelcome(scheme: 'dark' | 'light' = 'dark') {
  const onGetStarted = jest.fn();
  const onHaveAccount = jest.fn();
  const view = await renderWithTheme(
    <WelcomeScreen onGetStarted={onGetStarted} onHaveAccount={onHaveAccount} />,
    scheme,
  );
  return { ...view, onGetStarted, onHaveAccount };
}

describe('<WelcomeScreen />', () => {
  test('fills the screen with the hero photo, cropped to cover', async () => {
    await renderWelcome();

    const photo = screen.getByTestId('welcome-photo');
    expect(photo).toHaveProp('source', require('../assets/images/welcome-hero.png'));
    expect(photo).toHaveProp('resizeMode', 'cover');
    // a picture, not content: it has no name, so a screen reader passes over it
    expect(photo).not.toHaveProp('accessibilityLabel');
    expect(photo).not.toHaveProp('alt');
    expect(photo).toHaveProp('importantForAccessibility', 'no');
    expect(photo).toHaveStyle({ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, width: '100%', height: '100%' });
  });

  test('draws the wordmark as text: "Form" bold white, "iq" bold green, read as one word', async () => {
    await renderWelcome();

    const wordmark = screen.getByRole('header');
    expect(wordmark).toHaveAccessibleName('Formiq');
    expect(wordmark).toHaveTextContent('Formiq');
    expect(wordmark).toHaveStyle({ color: dark.textPrimary, fontWeight: '700' });
    expect(screen.getByText('iq')).toHaveStyle({ color: dark.accent, fontWeight: '700' });
    expect(screen.getByText('iq')).toHaveStyle({ fontSize: StyleSheet.flatten(wordmark.props.style).fontSize });
  });

  test('puts the tagline on two lines under the wordmark', async () => {
    await renderWelcome();

    const tagline = screen.getByText('Your Personal Fitness Assistant');
    expect(tagline).toHaveTextContent('Your Personal\nFitness Assistant');
    expect(tagline).toHaveStyle({ textAlign: 'center', color: dark.textSecondary });
  });

  test('has two actions and nothing else to read: no card, paragraph or extra link', async () => {
    await renderWelcome();

    expect(screen.getAllByRole('button').map((button) => button.props.accessibilityLabel)).toEqual([
      'Get Started',
      'I already have an account',
    ]);
    expect(screen.getAllByRole('header')).toHaveLength(1);
    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.queryByTestId('welcome-hero')).toBeNull();
  });

  test('"Get Started" and "I already have an account" call their handlers once', async () => {
    const { onGetStarted, onHaveAccount } = await renderWelcome();

    await fireEvent.press(screen.getByRole('button', { name: 'Get Started' }));
    expect(onGetStarted).toHaveBeenCalledTimes(1);
    expect(onHaveAccount).not.toHaveBeenCalled();

    await fireEvent.press(screen.getByRole('button', { name: 'I already have an account' }));
    expect(onHaveAccount).toHaveBeenCalledTimes(1);
    expect(onGetStarted).toHaveBeenCalledTimes(1);
  });

  test('shows "Get Started" with an arrow that screen readers do not read', async () => {
    await renderWelcome();

    expect(screen.getByRole('button', { name: 'Get Started' })).toHaveAccessibleName('Get Started');
    expect(screen.getByTestId('icon-arrow-right', { includeHiddenElements: true })).toHaveProp('importantForAccessibility', 'no-hide-descendants');
  });

  test('styles the buttons: a green primary, and a see-through dark one with a grey outline', async () => {
    await renderWelcome();

    expect(screen.getByRole('button', { name: 'Get Started' })).toHaveStyle({
      backgroundColor: dark.primary,
      borderColor: dark.primary,
      minHeight: 56,
    });
    expect(screen.getByText('Get Started')).toHaveStyle({ color: dark.textOnPrimary });

    const secondary = screen.getByRole('button', { name: 'I already have an account' });
    expect(secondary).toHaveStyle({ backgroundColor: `${dark.background}99`, borderColor: dark.borderStrong, minHeight: 56 });
    expect(screen.getByText('I already have an account')).toHaveStyle({ color: dark.textPrimary });
  });

  test('keeps the dark look in the light theme, without changing the theme for others', async () => {
    function Probe() {
      return <AppText testID="probe">{useTheme().scheme}</AppText>;
    }
    await render(
      <SafeAreaProvider>
        <ThemeProvider initialScheme="light">
          <Probe />
          <WelcomeScreen onGetStarted={jest.fn()} onHaveAccount={jest.fn()} />
        </ThemeProvider>
      </SafeAreaProvider>,
    );

    expect(screen.getByTestId('probe')).toHaveTextContent('light');
    expect(screen.getByTestId('welcome-screen')).toHaveStyle({ backgroundColor: dark.background });
    expect(screen.getByRole('header')).toHaveStyle({ color: dark.textPrimary });
    expect(screen.getByRole('button', { name: 'Get Started' })).toHaveStyle({ backgroundColor: dark.primary });
  });

  test('keeps clear of the system bars and holds the screen margins', async () => {
    const insets = { top: 47, bottom: 34, left: 0, right: 0 };
    await render(
      <SafeAreaProvider initialMetrics={{ frame: { x: 0, y: 0, width: 390, height: 844 }, insets }}>
        <ThemeProvider>
          <WelcomeScreen onGetStarted={jest.fn()} onHaveAccount={jest.fn()} />
        </ThemeProvider>
      </SafeAreaProvider>,
    );

    expect(screen.getByTestId('welcome-content')).toHaveStyle({
      paddingTop: insets.top,
      paddingBottom: insets.bottom + spacing.xl,
      paddingLeft: layout.screenPadding,
      paddingRight: layout.screenPadding,
    });
  });

  test.each([
    { width: 320, expected: 54 },
    { width: 411, expected: 70 },
    { width: 1000, expected: 76 },
  ])('sizes the wordmark from the screen width ($width dp wide: $expected)', async ({ width, expected }) => {
    jest.spyOn(Dimensions, 'get').mockReturnValue({ width, height: width * 2, scale: 2, fontScale: 1 });
    await renderWelcome();

    expect(screen.getByRole('header')).toHaveStyle({ fontSize: expected });
    expect(screen.getByRole('header')).toHaveProp('numberOfLines', 1);
  });
});
