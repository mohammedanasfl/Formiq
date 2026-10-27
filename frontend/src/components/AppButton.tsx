import { ActivityIndicator, Pressable, type StyleProp, type ViewStyle } from 'react-native';

import {
  layout,
  radii,
  spacing,
  useTheme,
  type ColorTokens,
  type TextColorToken,
} from '../theme';
import { AppIcon, type IconName } from './AppIcon';
import { AppText } from './AppText';

export type ButtonVariant = 'primary' | 'secondary' | 'overlay';

export type AppButtonProps = {
  label: string;
  onPress: () => void;
  // `overlay` is the secondary button for sitting on a photo: the same outline, with a see-through
  // dark fill so the picture stays visible behind it.
  variant?: ButtonVariant;
  disabled?: boolean;
  // Work is under way: shows a spinner and ignores presses, while keeping the normal colors. The
  // caller says so in the label too ("Saving…"): that is what a screen reader reads.
  loading?: boolean;
  // A picture after the label, such as an arrow for "Next". Decorative: the label says it all.
  trailingIcon?: IconName;
  // A picture before the label, such as a play triangle. Decorative as well.
  leadingIcon?: IconName;
  // A slimmer button, for beside a heading. It is still a full touch target: its hit area is widened to
  // `layout.touchTarget`.
  compact?: boolean;
  accessibilityHint?: string;
  testID?: string;
  style?: StyleProp<ViewStyle>;
};

export function AppButton({
  label,
  onPress,
  variant = 'primary',
  disabled = false,
  loading = false,
  trailingIcon,
  leadingIcon,
  compact = false,
  accessibilityHint,
  testID,
  style,
}: AppButtonProps) {
  const { colors } = useTheme();

  const labelColor: TextColorToken = disabled
    ? 'disabledText'
    : variant === 'primary'
      ? 'textOnPrimary'
      : 'textPrimary';

  return (
    <Pressable
      accessibilityRole="button"
      // Said explicitly: on Android the name would otherwise be built from the state, and a `busy`
      // state was seen replacing it ("busy" instead of "Log in"). Loading is told by the label the
      // caller gives ("Saving…") and by disabled.
      accessibilityLabel={label}
      accessibilityState={{ disabled: disabled || loading }}
      accessibilityHint={accessibilityHint}
      disabled={disabled || loading}
      onPress={onPress}
      testID={testID}
      hitSlop={compact ? (layout.touchTarget - COMPACT_HEIGHT) / 2 : undefined}
      style={({ pressed }) => [
        {
          minHeight: compact ? COMPACT_HEIGHT : layout.touchTarget,
          paddingHorizontal: compact ? spacing.lg : spacing.xl,
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'center',
          gap: spacing.sm,
          borderRadius: radii.md,
          borderWidth: layout.borderWidth.thin,
          ...buttonColors(colors, variant, disabled, pressed && !loading),
        },
        style,
      ]}
    >
      {loading ? <ActivityIndicator color={colors[labelColor]} /> : null}
      {leadingIcon && !loading ? <AppIcon name={leadingIcon} size={compact ? spacing.lg : spacing.xl} color={labelColor} /> : null}
      <AppText variant="button" color={labelColor} style={compact ? { fontSize: 13.5, lineHeight: 20 } : undefined}>
        {label}
      </AppText>
      {trailingIcon && !loading ? <AppIcon name={trailingIcon} size={spacing.xl} color={labelColor} /> : null}
    </Pressable>
  );
}

// How tall a compact button is; its touch area is still `layout.touchTarget`.
const COMPACT_HEIGHT = 34;

// Opacity of the overlay button's fill, as the two hex digits added to a token color.
const OVERLAY_FILL = '99';
const OVERLAY_FILL_PRESSED = 'CC';

function buttonColors(
  colors: ColorTokens,
  variant: ButtonVariant,
  disabled: boolean,
  pressed: boolean,
) {
  if (disabled) {
    return { backgroundColor: colors.disabledBackground, borderColor: colors.disabledBackground };
  }
  if (variant === 'primary') {
    const backgroundColor = pressed ? colors.primaryPressed : colors.primary;
    return { backgroundColor, borderColor: backgroundColor };
  }
  if (variant === 'overlay') {
    // Token colors are 6-digit hex, so appending two digits sets the opacity.
    return {
      backgroundColor: pressed ? `${colors.surfaceMuted}${OVERLAY_FILL_PRESSED}` : `${colors.background}${OVERLAY_FILL}`,
      borderColor: colors.borderStrong,
    };
  }
  return {
    backgroundColor: pressed ? colors.surfaceMuted : colors.surface,
    borderColor: colors.borderStrong,
  };
}
