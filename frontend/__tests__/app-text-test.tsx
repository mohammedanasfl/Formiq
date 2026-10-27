import { screen } from '@testing-library/react-native';

import { AppText } from '../src/components';
import { darkColors, layout, lightColors, typography } from '../src/theme';
import { renderWithTheme } from '../test-utils/renderWithTheme';

describe('<AppText />', () => {
  test('defaults to the body variant in the primary text color', async () => {
    await renderWithTheme(<AppText>Hello</AppText>);

    expect(screen.getByText('Hello')).toHaveStyle({
      fontSize: typography.body.fontSize,
      lineHeight: typography.body.lineHeight,
      fontWeight: typography.body.fontWeight,
      color: darkColors.textPrimary,
    });
  });

  test.each(Object.keys(typography) as (keyof typeof typography)[])(
    'the %s variant uses its typography tokens',
    async (variant) => {
      await renderWithTheme(<AppText variant={variant}>Text</AppText>);

      expect(screen.getByText('Text')).toHaveStyle({
        fontSize: typography[variant].fontSize,
        fontWeight: typography[variant].fontWeight,
      });
    },
  );

  test('takes its color from a semantic token, not a raw value', async () => {
    await renderWithTheme(<AppText color="textMuted">Quiet</AppText>);

    expect(screen.getByText('Quiet')).toHaveStyle({ color: darkColors.textMuted });
  });

  test('follows the light theme', async () => {
    await renderWithTheme(<AppText color="textMuted">Quiet</AppText>, 'light');

    expect(screen.getByText('Quiet')).toHaveStyle({ color: lightColors.textMuted });
  });

  test('lets a caller adjust the style and keeps text props', async () => {
    await renderWithTheme(
      <AppText style={{ marginTop: 8 }} accessibilityRole="header">
        Heading
      </AppText>,
    );

    const text = screen.getByText('Heading');
    expect(text).toHaveStyle({ marginTop: 8, color: darkColors.textPrimary });
    expect(screen.getByRole('header')).toBe(text);
  });

  test('scales with the user font size, up to the cap', async () => {
    await renderWithTheme(<AppText>Scales</AppText>);

    expect(screen.getByText('Scales').props.maxFontSizeMultiplier).toBe(layout.maxFontScale);
  });
});
