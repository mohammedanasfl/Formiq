import { screen } from '@testing-library/react-native';

import { AppCard, AppText } from '../src/components';
import { darkColors, layout, lightColors, radii, spacing } from '../src/theme';
import { renderWithTheme } from '../test-utils/renderWithTheme';

describe('<AppCard />', () => {
  test('renders its children on a bordered, rounded surface', async () => {
    await renderWithTheme(
      <AppCard testID="card">
        <AppText>Today</AppText>
      </AppCard>,
    );

    expect(screen.getByText('Today')).toBeOnTheScreen();
    expect(screen.getByTestId('card')).toHaveStyle({
      backgroundColor: darkColors.surface,
      borderColor: darkColors.border,
      borderWidth: layout.borderWidth.thin,
      borderRadius: radii.lg,
      padding: spacing.lg,
    });
  });

  test('uses the light theme surface', async () => {
    await renderWithTheme(<AppCard testID="card" />, 'light');

    expect(screen.getByTestId('card')).toHaveStyle({
      backgroundColor: lightColors.surface,
      borderColor: lightColors.border,
    });
  });

  test('lets a caller adjust the style and passes view props through', async () => {
    await renderWithTheme(
      <AppCard
        testID="card"
        accessible
        accessibilityLabel="Today's plan"
        style={{ marginBottom: 12 }}
      />,
    );

    const card = screen.getByTestId('card');
    expect(card).toHaveStyle({ marginBottom: 12, backgroundColor: darkColors.surface });
    expect(screen.getByLabelText("Today's plan")).toBe(card);
  });
});
