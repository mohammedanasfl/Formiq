import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import type { ComponentProps } from 'react';
import { View } from 'react-native';

import { useTheme, type ColorToken } from '../theme';

export type IconName = ComponentProps<typeof MaterialCommunityIcons>['name'];

// The set draws its dumbbell on a diagonal; turned this far (see `rotate`) it lies flat, as a gym sign does.
export const DUMBBELL_LEVEL = -45;

type AppIconProps = {
  name: IconName;
  // in dp; icons do not follow the font size setting, so a card never outgrows its layout
  size?: number;
  color?: ColorToken;
  // A color that is not a theme token, for an icon that wears a workout's own color. It wins over `color`.
  tint?: string;
  // degrees clockwise, for a glyph the set draws at an angle (its `dumbbell` is diagonal)
  rotate?: number;
};

// A decorative icon from the Material Community set (only that font is bundled), colored by a theme token. It is hidden from
// screen readers: whatever it sits in (a card, a button, a field) carries the words.
export function AppIcon({ name, size = 24, color = 'accent', tint, rotate }: AppIconProps) {
  const { colors } = useTheme();

  return (
    <View
      testID={`icon-${name}`}
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      style={rotate ? { transform: [{ rotate: `${rotate}deg` }] } : undefined}
    >
      <MaterialCommunityIcons name={name} size={size} color={tint ?? colors[color]} allowFontScaling={false} />
    </View>
  );
}
