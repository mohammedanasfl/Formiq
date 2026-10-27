import type { ReactNode } from 'react';
import { KeyboardAvoidingView, ScrollView, View, type ViewProps } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { layout, spacing, useTheme } from '../theme';

export type AppScreenProps = ViewProps & {
  // For forms and long pages: the content scrolls, taps reach buttons while the keyboard is up, and
  // the keyboard never covers the focused field or the footer.
  scrollable?: boolean;
  // Fixed below the content, always in reach (back and next buttons). Used with `scrollable`.
  footer?: ReactNode;
};

// A full-screen page: themed background, system bars kept clear, and the horizontal screen padding.
export function AppScreen({ scrollable = false, footer, style, children, ...rest }: AppScreenProps) {
  const { colors, scheme } = useTheme();
  const insets = useSafeAreaInsets();

  return (
    <>
      <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
      <View
        style={[
          {
            flex: 1,
            backgroundColor: colors.background,
            paddingTop: insets.top,
            paddingBottom: insets.bottom,
            paddingLeft: insets.left + layout.screenPadding,
            paddingRight: insets.right + layout.screenPadding,
          },
          style,
        ]}
        {...rest}
      >
        {scrollable ? (
          <KeyboardAvoidingView testID="screen-keyboard-avoider" style={{ flex: 1 }} behavior="padding">
            <ScrollView
              testID="screen-scroll"
              style={{ flex: 1 }}
              contentContainerStyle={{ flexGrow: 1, paddingVertical: spacing.lg }}
              keyboardShouldPersistTaps="handled"
              keyboardDismissMode="on-drag"
              showsVerticalScrollIndicator={false}
            >
              {children}
            </ScrollView>
            {footer ? (
              <View testID="screen-footer" style={{ paddingVertical: spacing.lg }}>
                {footer}
              </View>
            ) : null}
          </KeyboardAvoidingView>
        ) : (
          children
        )}
      </View>
    </>
  );
}
