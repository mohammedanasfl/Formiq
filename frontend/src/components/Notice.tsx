import type { ReactNode } from 'react';
import { View, type ViewProps } from 'react-native';

import { layout, radii, spacing, useTheme } from '../theme';
import { AppText } from './AppText';

type NoticeProps = ViewProps & {
  // error: something failed (announced to screen readers); info: something to know
  tone?: 'info' | 'error';
  title?: string;
  children: ReactNode;
};

// A boxed message. An error is announced when it appears; an info note is just read in order.
export function Notice({ tone = 'info', title, children, style, ...rest }: NoticeProps) {
  const { colors } = useTheme();
  const isError = tone === 'error';

  return (
    <View
      // one element for the screen reader: the title and the text are read together
      accessible
      accessibilityRole={isError ? 'alert' : undefined}
      accessibilityLiveRegion={isError ? 'polite' : undefined}
      style={[
        {
          gap: spacing.xs,
          padding: spacing.lg - layout.borderWidth.thin,
          borderWidth: layout.borderWidth.thin,
          borderRadius: radii.md,
          borderColor: isError ? colors.error : colors.border,
          backgroundColor: colors.surface,
        },
        style,
      ]}
      {...rest}
    >
      {title ? (
        <AppText variant="label" color={isError ? 'error' : 'textPrimary'}>
          {title}
        </AppText>
      ) : null}
      <AppText variant="caption" color={isError ? 'error' : 'textSecondary'}>
        {children}
      </AppText>
    </View>
  );
}
