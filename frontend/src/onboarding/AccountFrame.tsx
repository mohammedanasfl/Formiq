import type { ReactNode } from 'react';
import { Pressable, View } from 'react-native';

import { AppButton, AppScreen, AppText, PhotoBackdrop } from '../components';
import { FixedTheme, layout, radii, spacing, useTheme } from '../theme';
import { BACK_SLOT, BackButton } from './BackButton';
import { BUTTON_HEIGHT, GYM_PHOTO, GYM_PHOTO_SCRIM } from './photoScreen';

const WORDMARK_SIZE = 26;
const WORDMARK_MAX_FONT_SCALE = 1.15;

type AccountFrameProps = {
  // names the test IDs of the screen: `${testID}-screen`, `${testID}-photo` and `${testID}-content`
  testID: string;
  title: string;
  subtitle: string;
  // the fields
  children: ReactNode;
  // what must be seen whatever the scroll position, such as why the request failed: it sits in the
  // footer, above the button
  message?: ReactNode;
  // the label already says "Creating account…" while `loading`
  primary: { label: string; onPress: () => void; loading: boolean };
  // the way to the other account screen: "Already have an account? Log in"
  prompt: { lead: string; action: string; onPress: () => void };
  onBack: () => void;
};

// The frame the sign-up and log-in screens share, so that they look alike: the gym photo under a
// dark layer, a small "Formiq" wordmark with a back arrow, a heading, the fields, one green button and
// a link to the other screen. Like the welcome screen it is designed once, dark and over a photo, and
// keeps that look in the light theme. While the request is under way the button, Back and the link
// are off, so nobody leaves halfway.
export function AccountFrame(props: AccountFrameProps) {
  return (
    <FixedTheme scheme="dark">
      <Frame {...props} />
    </FixedTheme>
  );
}

function Frame({ testID, title, subtitle, children, message, primary, prompt, onBack }: AccountFrameProps) {
  const { colors } = useTheme();

  return (
    <View testID={`${testID}-screen`} style={{ flex: 1, backgroundColor: colors.background }}>
      <PhotoBackdrop testID={`${testID}-photo`} source={GYM_PHOTO} scrim={GYM_PHOTO_SCRIM} />
      <AppScreen
        testID={`${testID}-content`}
        scrollable
        style={{ backgroundColor: 'transparent' }}
        footer={
          <View style={{ gap: spacing.sm }}>
            {message}
            <AppButton
              label={primary.label}
              onPress={primary.onPress}
              loading={primary.loading}
              style={{ minHeight: BUTTON_HEIGHT, borderRadius: radii.lg }}
            />
            <Prompt {...prompt} disabled={primary.loading} />
          </View>
        }
      >
        <View style={{ gap: spacing.xl }}>
          <View style={{ flexDirection: 'row', alignItems: 'center' }}>
            <BackButton disabled={primary.loading} onPress={onBack} />
            <View style={{ flex: 1, alignItems: 'center' }}>
              <Wordmark />
            </View>
            {/* as wide as the back button is inside the row, so the wordmark sits in the middle */}
            <View style={{ width: BACK_SLOT }} />
          </View>
          <View style={{ gap: spacing.sm }}>
            <AppText variant="title" accessibilityRole="header">
              {title}
            </AppText>
            <AppText color="textSecondary">{subtitle}</AppText>
          </View>
          {children}
        </View>
      </AppScreen>
    </View>
  );
}

// "Form" in white and "iq" in green, as on the welcome screen, but small. It names the app for a
// screen reader as one word.
function Wordmark() {
  const style = {
    fontSize: WORDMARK_SIZE,
    lineHeight: Math.round(WORDMARK_SIZE * 1.25),
    letterSpacing: -0.3,
  };
  return (
    <AppText
      variant="title"
      accessibilityLabel="Formiq"
      maxFontSizeMultiplier={WORDMARK_MAX_FONT_SCALE}
      style={style}
    >
      Form
      <AppText variant="title" color="accent" maxFontSizeMultiplier={WORDMARK_MAX_FONT_SCALE} style={style}>
        iq
      </AppText>
    </AppText>
  );
}

// "Already have an account? Log in": one link, as tall as a button, with the action in green.
function Prompt({
  lead,
  action,
  disabled,
  onPress,
}: {
  lead: string;
  action: string;
  disabled: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="link"
      accessibilityLabel={`${lead} ${action}`}
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      style={{
        minHeight: layout.touchTarget,
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <AppText color="textSecondary" style={{ textAlign: 'center' }}>
        {lead}{' '}
        <AppText variant="button" color="accent">
          {action}
        </AppText>
      </AppText>
    </Pressable>
  );
}
