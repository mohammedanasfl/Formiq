import { View } from 'react-native';

import { AppText } from '../components';
import { layout, radii, spacing, useTheme } from '../theme';
import type { CategoryColors } from './categoryColors';
import type { MuscleFocus as MuscleFocusData } from './planDetails';

type MuscleFocusProps = {
  focus: MuscleFocusData;
  // the workout's colors (its category's, or the theme's plain ones): the primary muscles wear them
  card: CategoryColors;
};

// The muscles a workout trains, as one compact row of chips: the primary ones in the workout's own color,
// the secondary ones plain. It is one element for a screen reader, which hears the muscles in words.
export function MuscleFocus({ focus, card }: MuscleFocusProps) {
  const { colors } = useTheme();
  const spoken = [
    focus.primary.length > 0 ? `Muscle focus: ${focus.primary.join(', ')}` : 'Muscle focus',
    focus.secondary.length > 0 ? `also ${focus.secondary.join(', ')}` : null,
  ]
    .filter((part): part is string => Boolean(part))
    .join('. ');

  return (
    <View testID="muscle-focus" accessible accessibilityLabel={spoken} style={{ gap: spacing.sm }}>
      <AppText
        variant="caption"
        color="textMuted"
        style={{ fontSize: 12, lineHeight: 16, letterSpacing: 1.2, textTransform: 'uppercase', fontWeight: '600' }}
      >
        Muscle focus
      </AppText>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm }}>
        {focus.primary.map((name) => (
          <Chip key={`primary-${name}`} name={name} textColor={card.label} borderColor={card.border} backgroundColor={card.blend} />
        ))}
        {focus.secondary.map((name) => (
          <Chip key={`secondary-${name}`} name={name} textColor={colors.textSecondary} borderColor={colors.border} backgroundColor={colors.surface} />
        ))}
      </View>
    </View>
  );
}

type ChipProps = { name: string; textColor: string; borderColor: string; backgroundColor: string };

function Chip({ name, textColor, borderColor, backgroundColor }: ChipProps) {
  return (
    <View
      style={{
        paddingHorizontal: spacing.md,
        paddingVertical: spacing.xs + 1,
        borderRadius: radii.pill,
        borderWidth: layout.borderWidth.thin,
        borderColor,
        backgroundColor,
      }}
    >
      <AppText variant="label" style={{ color: textColor }}>
        {name}
      </AppText>
    </View>
  );
}
