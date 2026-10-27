import { View } from 'react-native';

import { radii, spacing, useTheme } from '../theme';
import { AppText } from './AppText';

type ProgressStepsProps = {
  // 1-based
  current: number;
  total: number;
  // For a top bar: short segments in a centered row and no printed "Step 3 of 6". Screen readers
  // still get the label.
  compact?: boolean;
};

const COMPACT_SEGMENT_WIDTH = spacing.xl - spacing.xs;
const COMPACT_SEGMENT_HEIGHT = spacing.xs;

// "Step 3 of 6", with a segment per step. Screen readers get one progress value, not the pieces.
export function ProgressSteps({ current, total, compact = false }: ProgressStepsProps) {
  const { colors } = useTheme();
  const label = `Step ${current} of ${total}`;

  return (
    <View
      accessible
      accessibilityRole="progressbar"
      accessibilityLabel={label}
      accessibilityValue={{ min: 1, max: total, now: current }}
      style={{ gap: spacing.sm, alignSelf: compact ? 'center' : undefined }}
    >
      <View style={{ flexDirection: 'row', gap: compact ? spacing.sm : spacing.xs }}>
        {Array.from({ length: total }, (_, index) => (
          <View
            key={index}
            testID={`progress-segment-${index + 1}`}
            style={{
              ...(compact
                ? { width: COMPACT_SEGMENT_WIDTH, height: COMPACT_SEGMENT_HEIGHT }
                : { flex: 1, height: spacing.xs }),
              borderRadius: radii.pill,
              backgroundColor: index < current ? colors.primary : compact ? colors.borderStrong : colors.border,
            }}
          />
        ))}
      </View>
      {compact ? null : (
        <AppText variant="caption" color="textMuted">
          {label}
        </AppText>
      )}
    </View>
  );
}
