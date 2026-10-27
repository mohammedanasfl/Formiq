import { useState } from 'react';
import { Pressable, View } from 'react-native';

import { AppIcon, AppText, DUMBBELL_LEVEL, type IconName } from '../components';
import { FixedTheme, layout, radii, spacing, useTheme } from '../theme';
import { ExerciseRow } from './ExerciseRow';
import { sectionSummary, type PlanSection, type PlannedExercise, type SectionGroup } from './planDetails';
import { SECTION_COLORS } from './sectionColors';

// The icon on each section's disc: a running figure for the warm-up, a dumbbell for the main workout (laid
// flat: the set draws it on a diagonal), a snowflake for the cool-down.
const SECTION_ICONS: Record<PlanSection, { name: IconName; rotate?: number }> = {
  WARM_UP: { name: 'run-fast' },
  MAIN_WORKOUT: { name: 'dumbbell', rotate: DUMBBELL_LEVEL },
  COOL_DOWN: { name: 'snowflake' },
};

const DISC_SIZE = 36;
const DISC_ICON = spacing.lg + spacing.xs;

type SectionCardProps = {
  group: SectionGroup;
  // the place in the whole workout of this section's first exercise, 1 up: the numbers run on across sections
  firstNumber: number;
  onOpenExercise: (exercise: PlannedExercise) => void;
};

// One part of the workout as a card: a header with the section's icon, its name, how many exercises it has and
// how long it takes, and a chevron that folds it away; under it, its exercises, one per row. It starts open.
export function SectionCard({ group, firstNumber, onOpenExercise }: SectionCardProps) {
  const { colors, scheme } = useTheme();
  const palette = SECTION_COLORS[group.id][scheme];
  const icon = SECTION_ICONS[group.id];
  const summary = sectionSummary(group);
  const [open, setOpen] = useState(true);

  return (
    <View
      testID={`section-${group.id}`}
      style={{
        overflow: 'hidden',
        borderWidth: layout.borderWidth.thin,
        borderRadius: radii.lg,
        borderColor: palette.border,
        backgroundColor: palette.rows,
      }}
    >
      <Pressable
        testID={`section-${group.id}-header`}
        accessibilityRole="button"
        accessibilityLabel={`${group.title}, ${summary.replace(' • ', ', ')}`}
        accessibilityHint={open ? 'Folds the section away' : 'Opens the section'}
        accessibilityState={{ expanded: open }}
        onPress={() => setOpen((current) => !current)}
        android_ripple={{ color: `${colors.textPrimary}14` }}
        style={{
          minHeight: layout.touchTarget,
          flexDirection: 'row',
          alignItems: 'center',
          gap: spacing.md,
          paddingVertical: spacing.sm,
          paddingLeft: spacing.sm + 2,
          paddingRight: spacing.md + 2,
          backgroundColor: palette.header,
        }}
      >
        <View
          testID={`section-${group.id}-disc`}
          accessibilityElementsHidden
          importantForAccessibility="no-hide-descendants"
          style={{
            width: DISC_SIZE,
            height: DISC_SIZE,
            borderRadius: DISC_SIZE / 2,
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: palette.accent,
          }}
        >
          {/* white on the accent in both themes: the glyph is not the page's text color */}
          <FixedTheme scheme="dark">
            <AppIcon name={icon.name} size={DISC_ICON} color="textPrimary" rotate={icon.rotate} />
          </FixedTheme>
        </View>
        <View style={{ flex: 1 }}>
          <AppText variant="body" accessibilityRole="header" style={{ fontWeight: '600', fontSize: 14.5, lineHeight: 20 }}>
            {group.title}
          </AppText>
          <AppText variant="caption" color="textSecondary" style={{ fontSize: 12, lineHeight: 16 }}>
            {summary}
          </AppText>
        </View>
        <AppIcon name={open ? 'chevron-up' : 'chevron-down'} size={spacing.xl} color="textPrimary" />
      </Pressable>
      {open
        ? group.exercises.map((exercise, index) => (
            <View
              key={exercise.id}
              style={{ borderTopWidth: layout.borderWidth.thin, borderTopColor: palette.divider }}
            >
              <ExerciseRow
                exercise={exercise}
                number={firstNumber + index}
                section={palette}
                onPress={() => onOpenExercise(exercise)}
              />
            </View>
          ))
        : null}
    </View>
  );
}
