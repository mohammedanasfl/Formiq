import { useState } from 'react';
import { Image, Pressable, View, useWindowDimensions } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { AppIcon, AppText, DUMBBELL_LEVEL } from '../components';
import { fadeGradient } from '../components/FadeEdge';
import { layout, radii, spacing, useTheme, type ThemeScheme } from '../theme';
import type { CategoryColors } from './categoryColors';
import { framedImageStyleInBox } from './framing';
import type { WorkoutVisual } from './workoutImages';

// How tall the photograph is below the status bar, and how far down it the title starts. The photograph is
// drawn at exactly this height and as wide as its own shape makes it, so nothing is cropped from its top or
// bottom (see framing.ts).
const PHOTO_HEIGHT = 136;
// where the athlete of the photograph sits across the screen: the photograph is about as wide as the screen, so
// its athlete (the point its `focus` names) goes to the middle, with the empty gym on the left for the title
const SUBJECT_AT = 0.5;
// the room above the title: the top bar's own row, which the screen draws over the photograph
export const TOP_BAR_HEIGHT = 36;
export const TOP_BAR_MARGIN = 6;
const TITLE_GAP = 30;
// How solid the scrim on the left is at most. The photograph is dark, so on the dark page a light scrim is
// enough for white words; on the pale page the words are dark, so the photograph has to be veiled much more
// to leave them a pale ground.
const LEFT_VEIL: Record<ThemeScheme, number> = { dark: 0.4, light: 0.9 };
const GUTTER = spacing.lg + spacing.xs;

type WorkoutHeroProps = {
  title: string;
  // the photograph for the workout's kind (or the neutral one), and how to frame it
  visual: WorkoutVisual;
  // the workout's colors: its kind's, or the theme's plain ones
  card: CategoryColors;
  // "23 minutes", when the workout has a length
  minutes: string | null;
  // "6 exercises"
  count: string;
  // "Covers core", and the control that opens the muscle focus: both left out when no muscle is known
  covers: string | null;
  focusOpen: boolean;
  onToggleFocus: () => void;
};

// The top of the workout screen: its photograph, fading into the page at the bottom and on the left so the
// title can sit on it, then the title, its length and exercise count, and the "Covers ..." pill with the
// "View muscle focus" one. The back, favourite and more buttons are not here: the screen keeps them over
// everything, so they stay in reach when the page scrolls.
export function WorkoutHero({ title, visual, card, minutes, count, covers, focusOpen, onToggleFocus }: WorkoutHeroProps) {
  const { colors, scheme } = useTheme();
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const [failed, setFailed] = useState(false);
  const photoHeight = insets.top + PHOTO_HEIGHT;

  return (
    <View testID="workout-hero">
      <View
        pointerEvents="none"
        style={{ position: 'absolute', top: 0, left: 0, right: 0, height: photoHeight, overflow: 'hidden' }}
      >
        {failed ? null : (
          // a picture, not content: the title says what the workout is
          <Image
            testID="workout-hero-photo"
            source={visual.source}
            resizeMode="cover"
            accessible={false}
            importantForAccessibility="no"
            onError={() => setFailed(true)}
            style={framedImageStyleInBox(visual.framing, { width, height: photoHeight }, SUBJECT_AT)}
          />
        )}
        <View
          testID="workout-hero-fade-left"
          style={{ position: 'absolute', top: 0, bottom: 0, left: 0, width: '72%', backgroundImage: fadeGradient(colors.background, 0.1, 'to right', LEFT_VEIL[scheme]) }}
        />
        <View
          testID="workout-hero-fade-bottom"
          style={{ position: 'absolute', left: 0, right: 0, bottom: 0, height: photoHeight * 0.72, backgroundImage: fadeGradient(colors.background, 0.1, 'to top') }}
        />
      </View>

      <View
        style={{
          paddingTop: insets.top + TOP_BAR_MARGIN + TOP_BAR_HEIGHT + TITLE_GAP,
          paddingLeft: insets.left + GUTTER,
          paddingRight: insets.right + GUTTER,
          gap: spacing.sm - 2,
        }}
      >
        <AppText variant="title" accessibilityRole="header" numberOfLines={3} style={{ fontSize: 25, lineHeight: 30 }}>
          {title}
        </AppText>
        <View testID="workout-hero-meta" style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.md }}>
          {minutes ? (
            <>
              <MetaItem icon="clock-outline" text={minutes} />
              <View style={{ width: layout.borderWidth.thin, height: spacing.lg, backgroundColor: colors.borderStrong }} />
            </>
          ) : null}
          <MetaItem icon="dumbbell" text={count} rotate={DUMBBELL_LEVEL} />
        </View>
        {covers ? (
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: spacing.sm + 2, marginTop: spacing.xs }}>
            <View
              testID="workout-covers"
              accessible
              accessibilityLabel={covers}
              style={{
                maxWidth: '100%',
                flexShrink: 1,
                flexDirection: 'row',
                alignItems: 'center',
                gap: spacing.sm - 2,
                paddingHorizontal: spacing.md,
                paddingVertical: spacing.xs,
                borderRadius: radii.pill,
                borderWidth: layout.borderWidth.thin,
                borderColor: card.border,
                backgroundColor: card.chip,
              }}
            >
              <AppIcon name="target" size={spacing.lg} tint={card.label} />
              <AppText variant="label" numberOfLines={1} style={{ color: card.label, flexShrink: 1, fontSize: 12.5, lineHeight: 18 }}>
                {covers}
              </AppText>
            </View>
            <Pressable
              testID="workout-focus-toggle"
              accessibilityRole="button"
              accessibilityLabel="View muscle focus"
              accessibilityState={{ expanded: focusOpen }}
              onPress={onToggleFocus}
              hitSlop={spacing.xs}
              style={({ pressed }) => ({
                flexDirection: 'row',
                alignItems: 'center',
                gap: spacing.xs,
                paddingLeft: spacing.md,
                paddingRight: spacing.sm - 2,
                paddingVertical: spacing.xs,
                borderRadius: radii.pill,
                borderWidth: layout.borderWidth.thin,
                borderColor: colors.border,
                backgroundColor: pressed ? colors.surfaceMuted : colors.surface,
              })}
            >
              <AppText variant="label" style={{ fontSize: 12.5, lineHeight: 18 }}>View muscle focus</AppText>
              <AppIcon name={focusOpen ? 'chevron-down' : 'chevron-right'} size={spacing.lg} color="textSecondary" />
            </Pressable>
          </View>
        ) : null}
      </View>
    </View>
  );
}

function MetaItem({ icon, text, rotate }: { icon: 'clock-outline' | 'dumbbell'; text: string; rotate?: number }) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm - 2 }}>
      <AppIcon name={icon} size={spacing.lg} color="textSecondary" rotate={rotate} />
      <AppText variant="label" color="textSecondary" style={{ fontWeight: '400', fontSize: 12.5, lineHeight: 18 }}>
        {text}
      </AppText>
    </View>
  );
}
