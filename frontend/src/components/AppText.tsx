import { Text, type TextProps } from 'react-native';

import { layout, typography, useTheme, type TextColorToken, type TextVariant } from '../theme';

export type AppTextProps = TextProps & {
  variant?: TextVariant;
  color?: TextColorToken;
};

export function AppText({
  variant = 'body',
  color = 'textPrimary',
  maxFontSizeMultiplier = layout.maxFontScale,
  style,
  ...rest
}: AppTextProps) {
  const { colors } = useTheme();

  return (
    <Text
      maxFontSizeMultiplier={maxFontSizeMultiplier}
      style={[typography[variant], { color: colors[color] }, style]}
      {...rest}
    />
  );
}
