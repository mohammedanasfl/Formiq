import type { ReactNode } from 'react';
import { View } from 'react-native';

import { AppButton, AppScreen, AppText, ProgressSteps } from '../components';
import { spacing } from '../theme';

type Action = {
  label: string;
  onPress: () => void;
  loading?: boolean;
  // an arrow after the label, for the button that moves on
  arrow?: boolean;
};

type StepLayoutProps = {
  // where this screen is among the profile steps; left out for the account screens
  step?: { index: number; total: number };
  title: string;
  subtitle?: string;
  children: ReactNode;
  primary: Action;
  secondary?: Action;
  // A message that must be seen whatever the scroll position, such as why a save failed: it sits in
  // the footer, above the buttons.
  footerMessage?: ReactNode;
};

// The frame every onboarding screen shares: progress, a heading, the form that scrolls, and a footer
// with back and next that stays in reach (above the keyboard too).
export function StepLayout({
  step,
  title,
  subtitle,
  children,
  primary,
  secondary,
  footerMessage,
}: StepLayoutProps) {
  return (
    <AppScreen
      scrollable
      footer={
        <View style={{ gap: spacing.md }}>
          {footerMessage}
          <View style={{ flexDirection: 'row', gap: spacing.md }}>
            {secondary ? (
              <AppButton
                variant="secondary"
                label={secondary.label}
                onPress={secondary.onPress}
                style={{ flex: 1 }}
              />
            ) : null}
            <AppButton
              label={primary.label}
              onPress={primary.onPress}
              loading={primary.loading}
              trailingIcon={primary.arrow ? 'arrow-right' : undefined}
              style={{ flex: 2 }}
            />
          </View>
        </View>
      }
    >
      <View style={{ gap: spacing.xl }}>
        {step ? <ProgressSteps current={step.index} total={step.total} /> : null}
        <View style={{ gap: spacing.sm }}>
          <AppText variant="title" accessibilityRole="header">
            {title}
          </AppText>
          {subtitle ? <AppText color="textSecondary">{subtitle}</AppText> : null}
        </View>
        {children}
      </View>
    </AppScreen>
  );
}
