import { Image, StyleSheet, View, useWindowDimensions, type TextStyle } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { AppButton, AppText } from '../../components';
import { FixedTheme, layout, radii, spacing, useTheme } from '../../theme';

// The photo behind the whole screen: an athlete seen from behind in a dark gym, centered, with the
// lower third close to black so the buttons stay readable without a scrim.
const HERO = require('../../../assets/images/welcome-hero.png');

// The wordmark is about a sixth of the screen's width per letter, within sensible limits.
const WORDMARK_SHARE = 0.17;
const WORDMARK_MAX = 76;
// It is the brand, drawn large already: a user's font size setting may grow it only a little.
const WORDMARK_MAX_FONT_SCALE = 1.15;
const TAGLINE_MAX_FONT_SCALE = 1.3;
const BUTTON_HEIGHT = 56;
// The free space above the wordmark against the free space below it: the wordmark sits over the
// athlete's back, a little above the middle, on any screen height.
const SPACE_ABOVE = 4;
const SPACE_BELOW = 6;

// Text on a photo gets a soft shadow, which keeps it readable over the lit shoulders.
const textShadow: TextStyle = {
  textShadowColor: 'rgba(0, 0, 0, 0.55)',
  textShadowOffset: { width: 0, height: 1 },
  textShadowRadius: 8,
};

type WelcomeScreenProps = {
  onGetStarted: () => void;
  onHaveAccount: () => void;
};

// The welcome screen is designed once, dark and over a photo: it keeps that look when the app is in
// the light theme. Every other screen follows the app's theme.
export function WelcomeScreen(props: WelcomeScreenProps) {
  return (
    <FixedTheme scheme="dark">
      <Welcome {...props} />
    </FixedTheme>
  );
}

function Welcome({ onGetStarted, onHaveAccount }: WelcomeScreenProps) {
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();

  const wordmarkSize = Math.round(Math.min(Math.max(width * WORDMARK_SHARE, spacing.xxxl), WORDMARK_MAX));
  const wordmarkStyle: TextStyle = {
    fontSize: wordmarkSize,
    lineHeight: Math.round(wordmarkSize * 1.1),
    letterSpacing: -0.5,
    ...textShadow,
  };
  const buttonStyle = { minHeight: BUTTON_HEIGHT, borderRadius: radii.lg };

  return (
    <View testID="welcome-screen" style={{ flex: 1, backgroundColor: colors.background }}>
      <StatusBar style="light" />
      {/* a picture, not content: it has no name and is hidden from screen readers */}
      <Image
        testID="welcome-photo"
        source={HERO}
        resizeMode="cover"
        accessible={false}
        importantForAccessibility="no"
        // an explicit size: on Android an image otherwise keeps the asset's own width and height,
        // which win over the four edges of absoluteFill and leave a huge, top-left picture
        style={[StyleSheet.absoluteFill, { width: '100%', height: '100%' }]}
      />
      <View
        testID="welcome-content"
        style={{
          flex: 1,
          paddingTop: insets.top,
          paddingBottom: insets.bottom + spacing.xl,
          paddingLeft: insets.left + layout.screenPadding,
          paddingRight: insets.right + layout.screenPadding,
        }}
      >
        <View style={{ flex: SPACE_ABOVE }} />
        <View style={{ alignItems: 'center', gap: spacing.sm }}>
          {/* one word for a screen reader: the green "iq" is only for the eye */}
          <AppText
            variant="display"
            accessibilityRole="header"
            accessibilityLabel="Formiq"
            numberOfLines={1}
            adjustsFontSizeToFit
            maxFontSizeMultiplier={WORDMARK_MAX_FONT_SCALE}
            style={wordmarkStyle}
          >
            Form
            <AppText
              variant="display"
              color="accent"
              maxFontSizeMultiplier={WORDMARK_MAX_FONT_SCALE}
              style={wordmarkStyle}
            >
              iq
            </AppText>
          </AppText>
          <AppText
            variant="heading"
            color="textSecondary"
            maxFontSizeMultiplier={TAGLINE_MAX_FONT_SCALE}
            style={{ fontSize: 22, lineHeight: 28, fontWeight: '500', textAlign: 'center', ...textShadow }}
          >
            {'Your Personal\nFitness Assistant'}
          </AppText>
        </View>
        <View style={{ flex: SPACE_BELOW }} />
        <View style={{ gap: spacing.md }}>
          <AppButton
            label="Get Started"
            trailingIcon="arrow-right"
            onPress={onGetStarted}
            style={buttonStyle}
          />
          <AppButton
            variant="overlay"
            label="I already have an account"
            onPress={onHaveAccount}
            style={buttonStyle}
          />
        </View>
      </View>
    </View>
  );
}
