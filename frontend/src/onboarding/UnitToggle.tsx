import { Pressable, View } from 'react-native';

import { AppText } from '../components';
import { layout, radii, spacing, useTheme } from '../theme';

type UnitToggleProps<Value extends string> = {
  // what the group is called for a screen reader, such as "Height unit"
  label: string;
  options: readonly { value: Value; label: string }[];
  value: Value;
  onChange: (value: Value) => void;
};

// The switch is a touch target tall. The segments sit inside its border and padding, and take the
// taps that land there too, so each reaches the full 48 dp (a touch never reaches past the switch).
const INSET = layout.borderWidth.thin + layout.borderWidth.thick;
const SEGMENT_HEIGHT = layout.touchTarget - 2 * INSET;

// A small switch between two or three units, for the row above a measurement field. The chosen unit
// is filled in emerald, like every other selected option, and announced as checked.
export function UnitToggle<Value extends string>({ label, options, value, onChange }: UnitToggleProps<Value>) {
  const { colors } = useTheme();

  return (
    <View
      accessibilityRole="radiogroup"
      accessibilityLabel={label}
      style={{
        flexDirection: 'row',
        padding: layout.borderWidth.thick,
        borderWidth: layout.borderWidth.thin,
        borderRadius: radii.md,
        borderColor: colors.borderStrong,
        backgroundColor: colors.surface,
      }}
    >
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <Pressable
            key={option.value}
            accessibilityRole="radio"
            accessibilityLabel={option.label}
            accessibilityState={{ checked: selected }}
            onPress={() => onChange(option.value)}
            hitSlop={{ top: INSET, bottom: INSET }}
            style={({ pressed }) => ({
              minHeight: SEGMENT_HEIGHT,
              minWidth: layout.touchTarget,
              paddingHorizontal: spacing.md,
              alignItems: 'center',
              justifyContent: 'center',
              borderRadius: radii.sm,
              backgroundColor: selected
                ? pressed
                  ? colors.primaryPressed
                  : colors.primary
                : pressed
                  ? colors.surfaceMuted
                  : 'transparent',
            })}
          >
            <AppText variant="label" color={selected ? 'textOnPrimary' : 'textSecondary'}>
              {option.label}
            </AppText>
          </Pressable>
        );
      })}
    </View>
  );
}
