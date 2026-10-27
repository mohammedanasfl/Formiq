import { Pressable, View, type StyleProp, type ViewStyle } from 'react-native';

import { layout, radii, spacing, useTheme } from '../theme';
import { AppIcon, type IconName } from './AppIcon';
import { AppText } from './AppText';
import { CheckMark } from './CheckMark';

export type OptionCardProps = {
  title: string;
  description?: string;
  selected: boolean;
  onPress: () => void;
  // radio: one choice among several; checkbox: any number
  role?: 'radio' | 'checkbox';
  // a picture before the words: muted, and emerald once the option is selected
  icon?: IconName;
  // row: a wide card with an indicator at its end (a goal, a place); chip: a short, wrapping choice
  // for a long list (equipment), where a check takes the icon's place when selected
  variant?: 'row' | 'chip';
  testID?: string;
  style?: StyleProp<ViewStyle>;
};

const ICON_SIZE = spacing.xxl;
// The icon sits in a column of its own, so the words of every row start at the same place.
const ICON_COLUMN = spacing.xxxl - spacing.sm;
const INDICATOR_SIZE = spacing.xl - spacing.xs;
const RADIO_DOT_SIZE = spacing.sm + 2;
const ROW_MIN_HEIGHT = 78;
const CHIP_ICON_SIZE = spacing.xl;
// The fill of a card, as the two hex digits added to a token color: the photo shows faintly through.
const FILL = 'E6';

// A tappable card for choosing an option, on the dark screens. Selected is an emerald outline, an
// emerald icon and a green tint, with a filled radio or a check, and it is announced as checked:
// color is never the only signal. Unselected is a grey outline on a dark surface.
export function OptionCard({
  title,
  description,
  selected,
  onPress,
  role = 'radio',
  icon,
  variant = 'row',
  testID,
  style,
}: OptionCardProps) {
  const { colors } = useTheme();
  const chip = variant === 'chip';
  const borderWidth = selected ? layout.borderWidth.thick : layout.borderWidth.thin;

  return (
    <Pressable
      accessibilityRole={role}
      // said out loud: the title, then the description. The icon and the indicator are not part of it.
      accessibilityLabel={description ? `${title}. ${description}` : title}
      accessibilityState={{ checked: selected }}
      onPress={onPress}
      testID={testID}
      style={({ pressed }) => [
        {
          minHeight: chip ? layout.touchTarget : ROW_MIN_HEIGHT,
          flexDirection: 'row',
          alignItems: 'center',
          gap: chip ? spacing.sm : spacing.lg,
          // the border grows when selected: the padding shrinks by as much, so the card keeps its size
          padding: (chip ? spacing.md : spacing.lg) - borderWidth,
          borderWidth,
          borderRadius: chip ? radii.md : radii.lg,
          borderColor: selected ? colors.accent : colors.borderStrong,
          backgroundColor: `${selected ? colors.primarySubtle : pressed ? colors.surfaceMuted : colors.surface}${FILL}`,
        },
        chip ? { maxWidth: '100%' } : null,
        style,
      ]}
    >
      {chip ? (
        // the same square for the icon and for the check, so the chip does not change width
        <View style={{ width: CHIP_ICON_SIZE, alignItems: 'center' }}>
          {icon && !selected ? (
            <AppIcon name={icon} size={CHIP_ICON_SIZE} color="textMuted" />
          ) : selected ? (
            <CheckMark size={spacing.lg} color={colors.accent} />
          ) : null}
        </View>
      ) : icon ? (
        <View style={{ width: ICON_COLUMN, alignItems: 'center' }}>
          <AppIcon name={icon} size={ICON_SIZE} color={selected ? 'accent' : 'textMuted'} />
        </View>
      ) : null}
      <View style={{ flexShrink: 1, flex: chip ? undefined : 1, gap: spacing.xs }}>
        <AppText variant={chip ? 'label' : 'button'}>{title}</AppText>
        {description ? (
          <AppText variant="caption" color="textSecondary">
            {description}
          </AppText>
        ) : null}
      </View>
      {chip ? null : <Indicator role={role} selected={selected} />}
    </Pressable>
  );
}

// The radio or the checkbox at the end of a row. Hidden from screen readers, which hear "checked".
function Indicator({ role, selected }: { role: 'radio' | 'checkbox'; selected: boolean }) {
  const { colors } = useTheme();
  const box = role === 'checkbox';

  return (
    <View
      testID="option-indicator"
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      style={{
        width: INDICATOR_SIZE,
        height: INDICATOR_SIZE,
        alignItems: 'center',
        justifyContent: 'center',
        borderRadius: box ? radii.sm - spacing.xs : radii.pill,
        borderWidth: layout.borderWidth.thick,
        borderColor: selected ? colors.accent : colors.borderStrong,
        backgroundColor: box && selected ? colors.accent : 'transparent',
      }}
    >
      {selected && box ? <CheckMark size={spacing.md} color={colors.textOnPrimary} /> : null}
      {selected && !box ? (
        <View
          testID="option-indicator-dot"
          style={{
            width: RADIO_DOT_SIZE,
            height: RADIO_DOT_SIZE,
            borderRadius: radii.pill,
            backgroundColor: colors.accent,
          }}
        />
      ) : null}
    </View>
  );
}
