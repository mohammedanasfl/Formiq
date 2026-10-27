import { StatusBar } from 'expo-status-bar';
import { render, screen } from '@testing-library/react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { AppScreen, AppText } from '../src/components';
import { darkColors, layout, lightColors, ThemeProvider, type ThemeScheme } from '../src/theme';
import { renderWithTheme } from '../test-utils/renderWithTheme';

// The status bar draws nothing: replace it to see which icon style the screen asks for.
jest.mock('expo-status-bar', () => ({ StatusBar: jest.fn(() => null) }));

const metrics = {
  frame: { x: 0, y: 0, width: 360, height: 800 },
  insets: { top: 40, bottom: 20, left: 8, right: 4 },
};

function renderWithInsets(scheme: ThemeScheme = 'dark') {
  return render(
    <SafeAreaProvider initialMetrics={metrics}>
      <ThemeProvider initialScheme={scheme}>
        <AppScreen testID="screen">
          <AppText>Content</AppText>
        </AppScreen>
      </ThemeProvider>
    </SafeAreaProvider>,
  );
}

describe('<AppScreen />', () => {
  test('renders its children on the page background, filling the screen', async () => {
    await renderWithTheme(
      <AppScreen testID="screen">
        <AppText>Content</AppText>
      </AppScreen>,
    );

    expect(screen.getByText('Content')).toBeOnTheScreen();
    expect(screen.getByTestId('screen')).toHaveStyle({
      flex: 1,
      backgroundColor: darkColors.background,
    });
  });

  test('uses the light page background', async () => {
    await renderWithTheme(<AppScreen testID="screen" />, 'light');

    expect(screen.getByTestId('screen')).toHaveStyle({ backgroundColor: lightColors.background });
  });

  test('keeps clear of the system bars and adds the screen padding at the sides', async () => {
    await renderWithInsets();

    expect(screen.getByTestId('screen')).toHaveStyle({
      paddingTop: metrics.insets.top,
      paddingBottom: metrics.insets.bottom,
      paddingLeft: metrics.insets.left + layout.screenPadding,
      paddingRight: metrics.insets.right + layout.screenPadding,
    });
  });

  test('lets a caller adjust the style and passes view props through', async () => {
    await renderWithTheme(
      <AppScreen testID="screen" style={{ justifyContent: 'center' }} accessibilityLabel="Home" />,
    );

    expect(screen.getByTestId('screen')).toHaveStyle({
      justifyContent: 'center',
      backgroundColor: darkColors.background,
    });
    expect(screen.getByTestId('screen')).toHaveProp('accessibilityLabel', 'Home');
  });

  test.each([
    ['dark', 'light'],
    ['light', 'dark'],
  ] as const)('on the %s theme the status bar icons are %s', async (scheme, style) => {
    await renderWithTheme(<AppScreen />, scheme);

    expect(StatusBar).toHaveBeenLastCalledWith(expect.objectContaining({ style }), undefined);
  });
});
