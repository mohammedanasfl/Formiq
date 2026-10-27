import { Pressable, View } from 'react-native';

import { layout, radii, spacing, useTheme } from '../theme';
import { AppText } from './AppText';

type ChoiceChipsProps<Value extends string | number> = {
  label: string;
  options: readonly { value: Value; label: string }[];
  value: Value | null;
  onChange: (value: Value) => void;
  // shown below the chips and announced when it appears
  error?: string;
  helperText?: string;
  // Equal chips in rows of this many, for a set that would otherwise leave one chip alone on a row
  // (days of the week). Left out, the chips take the width of their words and wrap.
  columns?: number;
};

// A short row of exclusive choices (gender, days a week) that wraps on narrow screens. Selected is
// the same emerald outline and tint as the cards, so a choice looks the same wherever it is made.
export function ChoiceChips<Value extends string | number>({
  label,
  options,
  value,
  onChange,
  error,
  helperText,
  columns,
}: ChoiceChipsProps<Value>) {
  const { colors } = useTheme();
  const message = error ?? helperText;

  const chip = (option: (typeof options)[number]) => {
    const selected = option.value === value;
    const borderWidth = selected ? layout.borderWidth.thick : layout.borderWidth.thin;
    return (
      <Pressable
        key={String(option.value)}
        accessibilityRole="radio"
        accessibilityState={{ checked: selected }}
        onPress={() => onChange(option.value)}
        style={({ pressed }) => ({
          minHeight: layout.touchTarget,
          minWidth: layout.touchTarget,
          flex: columns ? 1 : undefined,
          // the border grows when it is selected: the padding shrinks by as much, so the chip keeps its
          // size. In a grid the chips share the row, so they have no padding that the spare cell lacks.
          paddingHorizontal: columns ? 0 : spacing.lg - borderWidth,
          alignItems: 'center',
          justifyContent: 'center',
          borderRadius: radii.md,
          borderWidth,
          borderColor: selected ? colors.accent : colors.borderStrong,
          backgroundColor: selected
            ? colors.primarySubtle
            : pressed
              ? colors.surfaceMuted
              : colors.surface,
        })}
      >
        <AppText variant="button">{option.label}</AppText>
      </Pressable>
    );
  };

  const rows = columns
    ? Array.from({ length: Math.ceil(options.length / columns) }, (_, row) =>
        options.slice(row * columns, (row + 1) * columns),
      )
    : [options];

  return (
    <View accessibilityRole="radiogroup" accessibilityLabel={label} style={{ gap: spacing.sm }}>
      <AppText variant="label" color="textSecondary">
        {label}
      </AppText>
      <View style={{ gap: spacing.sm }}>
        {rows.map((row, index) => (
          <View
            key={index}
            style={{ flexDirection: 'row', flexWrap: columns ? 'nowrap' : 'wrap', gap: spacing.sm }}
          >
            {row.map(chip)}
            {/* the last row keeps the width of the others: a spare cell as wide as a chip, minimum and all */}
            {columns
              ? Array.from({ length: columns - row.length }, (_, spare) => (
                  <View key={`spare-${spare}`} style={{ flex: 1, minWidth: layout.touchTarget }} />
                ))
              : null}
          </View>
        ))}
      </View>
      {message ? (
        <AppText
          variant="caption"
          color={error ? 'error' : 'textMuted'}
          accessibilityRole={error ? 'alert' : undefined}
          accessibilityLiveRegion={error ? 'polite' : undefined}
        >
          {message}
        </AppText>
      ) : null}
    </View>
  );
}
