import type { ReactNode } from 'react';
import { View } from 'react-native';

import { AppButton, AppScreen, AppText, PhotoBackdrop, ProgressSteps } from '../components';
import { FixedTheme, layout, radii, spacing, useTheme } from '../theme';
import { BACK_SLOT, BackButton } from './BackButton';
import { BUTTON_HEIGHT, GYM_PHOTO } from './photoScreen';

// The room between the heading and the content under it.
const CONTENT_GAP = spacing.xl + spacing.xs;
// A lighter layer than the account screens use: the teal glow of the photo shows more behind the heading.
const STEP_PHOTO_SCRIM = 0.15;

type Action = {
  label: string;
  onPress: () => void;
  // an arrow after the label, for the button that moves on
  arrow?: boolean;
  // work is under way: a spinner, and presses are ignored (the label says so too: "Saving…")
  loading?: boolean;
};

type StepFrameProps = {
  // where this screen is among the profile steps; left out after the last one, which has no top bar
  step?: { index: number; total: number };
  // something above the heading, such as the mark of a result
  lead?: ReactNode;
  title: string;
  subtitle?: string;
  children?: ReactNode;
  primary: Action;
  // A message that must be seen whatever the scroll position, such as a missing answer: it sits in
  // the footer, above the button.
  footerMessage?: ReactNode;
  // left out where there is nothing before this step: no arrow is drawn, so none leads nowhere
  onBack?: () => void;
  // the arrow is shown but does nothing, while a save is under way
  backDisabled?: boolean;
  // the heading and the content sit in the middle of the screen, centered, for a result (saved)
  centered?: boolean;
};

// The frame of the profile steps that have the dark design: the gym photo under a dark layer, a back
// arrow and a compact progress bar on top, a heading, the content that scrolls, and one wide button in
// the footer, which stays in reach (above the keyboard too). Like the welcome screen it is designed
// once, dark and over a photo, and keeps that look in the light theme.
export function StepFrame(props: StepFrameProps) {
  return (
    <FixedTheme scheme="dark">
      <Frame {...props} />
    </FixedTheme>
  );
}

function Frame({
  step,
  lead,
  title,
  subtitle,
  children,
  primary,
  footerMessage,
  onBack,
  backDisabled,
  centered = false,
}: StepFrameProps) {
  const { colors } = useTheme();

  return (
    <View testID="step-frame" style={{ flex: 1, backgroundColor: colors.background }}>
      <PhotoBackdrop testID="step-photo" source={GYM_PHOTO} scrim={STEP_PHOTO_SCRIM} />
      <AppScreen
        testID="step-screen"
        scrollable
        style={{ backgroundColor: 'transparent' }}
        footer={
          <View style={{ gap: spacing.sm }}>
            {footerMessage}
            <AppButton
              label={primary.label}
              onPress={primary.onPress}
              loading={primary.loading}
              trailingIcon={primary.arrow ? 'arrow-right' : undefined}
              style={{ minHeight: BUTTON_HEIGHT, borderRadius: radii.lg }}
            />
          </View>
        }
      >
        <View style={{ flex: centered ? 1 : undefined }}>
          {step ? (
            // as tall as the back button even when there is none, so the progress stays where it is from one step to the next
            <View testID="step-top-bar" style={{ flexDirection: 'row', alignItems: 'flex-start', minHeight: layout.touchTarget }}>
              {onBack ? <BackButton disabled={backDisabled} onPress={onBack} /> : <View style={{ width: BACK_SLOT }} />}
              {/* the dashes sit a little above the middle of the arrow */}
              <View style={{ flex: 1, paddingTop: spacing.sm }}>
                <ProgressSteps current={step.index} total={step.total} compact />
              </View>
              {/* as wide as the back button is inside the row, so the progress sits in the middle */}
              <View style={{ width: BACK_SLOT }} />
            </View>
          ) : null}
          <View
            style={{
              flex: centered ? 1 : undefined,
              justifyContent: centered ? 'center' : undefined,
              alignItems: centered ? 'center' : undefined,
            }}
          >
            <View style={{ marginTop: step ? spacing.lg : 0, gap: spacing.xs, alignItems: centered ? 'center' : undefined }}>
              {lead ? <View style={{ marginBottom: spacing.md }}>{lead}</View> : null}
              <AppText variant="title" accessibilityRole="header" style={centered ? { textAlign: 'center' } : undefined}>
                {title}
              </AppText>
              {subtitle ? (
                <AppText color="textSecondary" style={centered ? { textAlign: 'center' } : undefined}>
                  {subtitle}
                </AppText>
              ) : null}
            </View>
            {children ? <View style={{ marginTop: CONTENT_GAP }}>{children}</View> : null}
          </View>
        </View>
      </AppScreen>
    </View>
  );
}
