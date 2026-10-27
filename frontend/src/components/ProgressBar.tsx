import { View } from 'react-native';

import { radii, spacing, useTheme, type ColorToken } from '../theme';

type ProgressBarProps = {
  // 0 to 1; anything outside is held to the ends
  value: number;
  color?: ColorToken;
  testID?: string;
};

const HEIGHT = spacing.sm - 2;

// A thin bar showing how far along something is. It is decoration: the words next to it say the same
// ("60%", "4 / 7"), so it is hidden from screen readers, like an icon.
export function ProgressBar({ value, color = 'primary', testID }: ProgressBarProps) {
  const { colors } = useTheme();
  const share = Math.min(1, Math.max(0, value));

  return (
    <View
      testID={testID}
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      style={{ height: HEIGHT, borderRadius: radii.pill, overflow: 'hidden', backgroundColor: colors.border }}
    >
      <View
        testID={testID ? `${testID}-fill` : undefined}
        style={{
          width: `${share * 100}%`,
          height: '100%',
          borderRadius: radii.pill,
          backgroundColor: colors[color],
        }}
      />
    </View>
  );
}
