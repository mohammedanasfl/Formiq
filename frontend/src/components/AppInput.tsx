import { useState, type ComponentProps, type ReactNode } from 'react';
import { TextInput, View, type TextInputProps } from 'react-native';

import { layout, radii, spacing, typography, useTheme } from '../theme';
import { AppIcon, type IconName } from './AppIcon';
import { AppText } from './AppText';

export type AppInputProps = Omit<
  TextInputProps,
  'style' | 'placeholderTextColor' | 'accessibilityLabel' | 'editable'
> & {
  label: string;
  // An error replaces the helper text and is announced when it appears.
  error?: string;
  helperText?: string;
  disabled?: boolean;
  // Something shown inside the field at its end: a unit, or a button such as show/hide password.
  trailing?: ReactNode;
  // A picture at the start of the field (an envelope for email). Decorative: the label names the field.
  leadingIcon?: IconName;
  // The label is shown by the screen instead (a row that also holds a unit switch). It still names
  // the field for screen readers.
  hideLabel?: boolean;
  ref?: ComponentProps<typeof TextInput>['ref'];
};

// Room kept free of text at the end of the field for `trailing`.
const TRAILING_WIDTH = layout.touchTarget + spacing.lg;
const LEADING_ICON_SIZE = spacing.xl - spacing.xs;
// Room kept free at the start for `leadingIcon`: the gap, the icon and the gap before the text.
const LEADING_WIDTH = spacing.lg + LEADING_ICON_SIZE + spacing.md;

// A single-line labelled text field. The visible label is hidden from screen readers because the
// field itself carries it as its accessibility label.
export function AppInput({
  label,
  error,
  helperText,
  disabled = false,
  trailing,
  leadingIcon,
  hideLabel = false,
  onFocus,
  onBlur,
  ref,
  ...rest
}: AppInputProps) {
  const { colors } = useTheme();
  const [focused, setFocused] = useState(false);

  const hasError = Boolean(error) && !disabled;
  const highlighted = (focused || hasError) && !disabled;
  const borderWidth = highlighted ? layout.borderWidth.thick : layout.borderWidth.thin;
  const borderColor = disabled
    ? colors.border
    : hasError
      ? colors.error
      : focused
        ? colors.accent
        : colors.borderStrong;
  const message = hasError ? error : helperText;

  return (
    <View style={{ gap: spacing.sm }}>
      {hideLabel ? null : (
        <AppText
          variant="label"
          color={disabled ? 'disabledText' : 'textSecondary'}
          accessibilityElementsHidden
          importantForAccessibility="no"
        >
          {label}
        </AppText>
      )}
      <View>
        <TextInput
          ref={ref}
          accessibilityLabel={label}
          accessibilityHint={message}
          accessibilityState={{ disabled }}
          editable={!disabled}
          placeholderTextColor={colors.textMuted}
          selectionColor={colors.accent}
          cursorColor={colors.accent}
          maxFontSizeMultiplier={layout.maxFontScale}
          onFocus={(event) => {
            setFocused(true);
            onFocus?.(event);
          }}
          onBlur={(event) => {
            setFocused(false);
            onBlur?.(event);
          }}
          style={[
            typography.body,
            {
              minHeight: layout.touchTarget,
              // The border grows on focus; padding shrinks by the same amount so the text stays put.
              paddingLeft: (leadingIcon ? LEADING_WIDTH : spacing.lg) - borderWidth,
              paddingRight: (trailing ? TRAILING_WIDTH : spacing.lg) - borderWidth,
              paddingVertical: spacing.md - borderWidth,
              borderWidth,
              borderColor,
              borderRadius: radii.md,
              color: disabled ? colors.disabledText : colors.textPrimary,
              backgroundColor: disabled ? colors.disabledBackground : colors.surface,
            },
          ]}
          {...rest}
        />
        {leadingIcon ? (
          <View
            // taps go through to the field
            pointerEvents="none"
            style={{
              position: 'absolute',
              top: 0,
              bottom: 0,
              left: spacing.lg,
              justifyContent: 'center',
            }}
          >
            <AppIcon
              name={leadingIcon}
              size={LEADING_ICON_SIZE}
              color={disabled ? 'disabledText' : focused ? 'accent' : 'textMuted'}
            />
          </View>
        ) : null}
        {trailing ? (
          <View
            style={{
              position: 'absolute',
              top: 0,
              right: 0,
              bottom: 0,
              minWidth: layout.touchTarget,
              paddingRight: spacing.sm,
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            {trailing}
          </View>
        ) : null}
      </View>
      {message ? (
        <AppText
          variant="caption"
          color={hasError ? 'error' : 'textMuted'}
          accessibilityRole={hasError ? 'alert' : undefined}
          accessibilityLiveRegion={hasError ? 'polite' : undefined}
        >
          {message}
        </AppText>
      ) : null}
    </View>
  );
}
