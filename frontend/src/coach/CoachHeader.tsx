import { Pressable, View, type StyleProp, type ViewStyle } from 'react-native';

import { AppIcon, AppText } from '../components';
import { BACK_OVERHANG, BackButton } from '../onboarding/BackButton';
import { layout, radii, spacing, useTheme } from '../theme';

// The header's height, below the status bar: the overflow menu opens just under it.
export const COACH_HEADER_HEIGHT = layout.touchTarget + spacing.lg;
const AVATAR_SIZE = spacing.xxl + spacing.sm;

export const COACH_NAME = 'Formiq Coach';
export const COACH_SUBTITLE = 'Your AI fitness coach';

type CoachHeaderProps = {
  onBack: () => void;
  onOpenMenu: () => void;
  style?: StyleProp<ViewStyle>;
};

// The top of the AI Coach screen: Back, the coach's avatar, its name with a line under it, and the overflow
// menu button. The subtitle says what the coach is and nothing about it being online: it is not reached yet.
export function CoachHeader({ onBack, onOpenMenu, style }: CoachHeaderProps) {
  const { colors } = useTheme();

  return (
    <View
      testID="coach-header"
      style={[
        {
          height: COACH_HEADER_HEIGHT,
          flexDirection: 'row',
          alignItems: 'center',
          gap: spacing.md,
          borderBottomWidth: layout.borderWidth.thin,
          borderBottomColor: colors.divider,
        },
        style,
      ]}
    >
      <BackButton onPress={onBack} />
      <View
        testID="coach-avatar"
        accessibilityElementsHidden
        importantForAccessibility="no-hide-descendants"
        style={{
          width: AVATAR_SIZE,
          height: AVATAR_SIZE,
          // the back button's touch area is wider than its arrow: this closes the gap that leaves
          marginLeft: -spacing.sm,
          alignItems: 'center',
          justifyContent: 'center',
          borderRadius: radii.pill,
          borderWidth: layout.borderWidth.thin,
          borderColor: colors.accent,
          backgroundColor: colors.primarySubtle,
        }}
      >
        <AppIcon name="creation" size={spacing.xl - spacing.xs} color="accent" />
      </View>
      <View style={{ flex: 1 }}>
        <AppText variant="heading" accessibilityRole="header" numberOfLines={1} style={{ fontSize: 17, lineHeight: 22 }}>
          {COACH_NAME}
        </AppText>
        <AppText variant="caption" color="textMuted" numberOfLines={1}>
          {COACH_SUBTITLE}
        </AppText>
      </View>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="More options"
        accessibilityHint="Opens a menu"
        onPress={onOpenMenu}
        style={({ pressed }) => ({
          width: layout.touchTarget,
          height: layout.touchTarget,
          // the same overhang as the back button, on the other side, so both icons line up with the page margin
          marginRight: -BACK_OVERHANG,
          alignItems: 'center',
          justifyContent: 'center',
          borderRadius: radii.pill,
          backgroundColor: pressed ? colors.surfaceMuted : 'transparent',
        })}
      >
        <AppIcon name="dots-vertical" color="textPrimary" />
      </Pressable>
    </View>
  );
}
