import { View, type ViewProps } from 'react-native';

import { layout, radii, spacing, useTheme } from '../theme';

export function AppCard({ style, ...rest }: ViewProps) {
  const { colors } = useTheme();

  return (
    <View
      style={[
        {
          backgroundColor: colors.surface,
          borderColor: colors.border,
          borderWidth: layout.borderWidth.thin,
          borderRadius: radii.lg,
          padding: spacing.lg,
        },
        style,
      ]}
      {...rest}
    />
  );
}
