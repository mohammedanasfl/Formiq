import { useState } from 'react';
import { ScrollView, useWindowDimensions, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { AppButton, AppText, LinkButton, NumberStepper, Toast, UnderlineTabs, useToast } from '../components';
import { fadeGradient } from '../components/FadeEdge';
import { BackButton } from '../onboarding/BackButton';
import { layout, radii, spacing, useTheme } from '../theme';
import { ExerciseAnimation } from './ExerciseAnimation';
import {
  detailLabels,
  EXERCISE_TABS,
  exerciseMuscles,
  instructionsContent,
  setDoneNotice,
  setProgressLabel,
  setTarget,
  stepTarget,
  targetLabel,
  tipItems,
  totalSets,
  UNAVAILABLE,
  type ExerciseTab,
} from './exerciseDetails';
import type { PlannedExercise } from './planDetails';

// How long the "marked done" notice stays: it is a sentence
const NOTICE_MS = 4000;
// The side space, the same as the workout screen's
const GUTTER = spacing.lg + spacing.xs;
// the page's color fading in over the last of the scroll, so text goes under the set controls instead of being cut
const BOTTOM_FADE_HEIGHT = spacing.xl + spacing.xs;
// and the same over the first of it, so text scrolling up under the Back arrow fades out instead of being cut
const TOP_FADE_HEIGHT = spacing.md;
// the sets shown as dots up to this many; more than that is left to the words
const MAX_SET_DOTS = 12;
const STEP_BADGE = 36;

type ExerciseDetailsScreenProps = {
  // Everything shown comes from here: the exercise the person pressed in the workout's list, as the plan and the
  // catalog describe it. A field it does not carry is shown as not available, never filled in.
  exercise: PlannedExercise;
  // back to the workout screen, which is left exactly as it was
  onBack: () => void;
  // How many of the exercise's sets are marked done. The caller keeps the count, so it is still there when the
  // person comes back to the exercise; the screen only asks for it to change.
  completedSets: number;
  onCompletedSetsChange: (count: number) => void;
};

// One exercise in full, laid out for doing it: its name and its muscle and equipment labels, an animation of the
// movement, three tabs (Instructions, Muscles, Tips), and at the foot the set being done: which set it is, how
// many reps or seconds (adjustable within limits) and "Complete Set". The page scrolls above the foot, so the
// action stays in reach however small the screen is.
//
// MOCK-ONLY BEHAVIOUR: the app has no workout session yet, so "Complete Set" counts the set on this screen only
// (the caller keeps the count while the app runs) and says so; it records nothing, and finishing every set does
// not complete the workout.
export function ExerciseDetailsScreen({ exercise, onBack, completedSets, onCompletedSetsChange }: ExerciseDetailsScreenProps) {
  const { colors, scheme } = useTheme();
  const insets = useSafeAreaInsets();
  const { width: windowWidth } = useWindowDimensions();
  const { message, show } = useToast(NOTICE_MS);
  const [tab, setTab] = useState<ExerciseTab>('instructions');

  const target = setTarget(exercise);
  const [value, setValue] = useState<number | null>(target?.initial ?? null);
  const total = totalSets(exercise);
  const done = total === null ? Math.max(0, completedSets) : Math.min(Math.max(0, completedSets), total);
  const finished = total !== null && done >= total;
  const labels = detailLabels(exercise);

  const side = { paddingLeft: insets.left + GUTTER, paddingRight: insets.right + GUTTER };
  const animationWidth = Math.max(0, windowWidth - side.paddingLeft - side.paddingRight);

  const completeSet = () => {
    const next = done + 1;
    onCompletedSetsChange(next);
    show(setDoneNotice(next, total));
  };

  return (
    <View testID="exercise-details" style={{ flex: 1, backgroundColor: colors.background }}>
      <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
      <View testID="exercise-details-body" style={{ flex: 1, paddingTop: insets.top }}>
        <View style={side}>
          <BackButton onPress={onBack} />
        </View>
        <View style={{ flex: 1 }}>
          <ScrollView
            testID="exercise-details-scroll"
            style={{ flex: 1 }}
            contentContainerStyle={{ paddingTop: spacing.sm, paddingBottom: spacing.xl, gap: spacing.lg, ...side }}
            showsVerticalScrollIndicator={false}
          >
            <View style={{ gap: spacing.md }}>
              <AppText variant="title" accessibilityRole="header">
                {exercise.name}
              </AppText>
              {labels.length > 0 ? (
                <View testID="exercise-labels" style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm }}>
                  {labels.map((label) => (
                    <Label key={label} text={label} />
                  ))}
                </View>
              ) : null}
            </View>
            <ExerciseAnimation exercise={exercise} width={animationWidth} />
            <UnderlineTabs tabs={EXERCISE_TABS} selected={tab} onSelect={setTab} accessibilityLabel="Exercise details" testID="exercise-tabs" />
            <View testID={`exercise-panel-${tab}`}>
              {tab === 'instructions' ? <Instructions exercise={exercise} /> : tab === 'muscles' ? <Muscles exercise={exercise} /> : <Tips exercise={exercise} />}
            </View>
          </ScrollView>
          <View
            testID="exercise-details-top-fade"
            pointerEvents="none"
            style={{ position: 'absolute', left: 0, right: 0, top: 0, height: TOP_FADE_HEIGHT, backgroundImage: fadeGradient(colors.background, 0, 'to bottom') }}
          />
          <View
            testID="exercise-details-bottom-fade"
            pointerEvents="none"
            style={{ position: 'absolute', left: 0, right: 0, bottom: 0, height: BOTTOM_FADE_HEIGHT, backgroundImage: fadeGradient(colors.background, 0, 'to top') }}
          />
          {/* sits at the bottom of this view, so above the set controls and never over them */}
          <Toast message={message} />
        </View>
      </View>

      <View
        testID="exercise-details-footer"
        style={{
          gap: spacing.md,
          paddingTop: spacing.md,
          paddingBottom: insets.bottom + spacing.md,
          backgroundColor: colors.background,
          ...side,
        }}
      >
        <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.md }}>
          <AppText variant="label" color="textSecondary" testID="exercise-set-label" accessibilityLiveRegion="polite" style={{ flexShrink: 1 }}>
            {finished ? `All ${total} ${total === 1 ? 'set' : 'sets'} done` : setProgressLabel(done + 1, total)}
          </AppText>
          {total !== null && total <= MAX_SET_DOTS ? <SetDots total={total} done={done} /> : null}
        </View>

        {finished ? (
          <View style={{ alignItems: 'center' }}>
            <LinkButton label="Do the sets again" onPress={() => onCompletedSetsChange(0)} />
          </View>
        ) : target && value !== null ? (
          <NumberStepper
            testID="exercise-stepper"
            label={target.unit === 'reps' ? 'Reps' : 'Duration'}
            valueLabel={targetLabel(target.unit, value)}
            canDecrease={value > target.min}
            canIncrease={value < target.max}
            decreaseLabel={target.unit === 'reps' ? 'Decrease reps' : 'Decrease duration'}
            increaseLabel={target.unit === 'reps' ? 'Increase reps' : 'Increase duration'}
            onDecrease={() => setValue(stepTarget(target, value, -1))}
            onIncrease={() => setValue(stepTarget(target, value, 1))}
          />
        ) : (
          <AppText testID="exercise-no-target" variant="label" color="textMuted" style={{ textAlign: 'center' }}>
            This plan gives no reps or time for each set.
          </AppText>
        )}

        <AppButton
          testID="exercise-primary-action"
          label={finished ? 'Back to workout' : 'Complete Set'}
          leadingIcon={finished ? 'arrow-left' : 'check'}
          onPress={finished ? onBack : completeSet}
          accessibilityHint={finished ? undefined : 'Marks this set done on this screen only. Nothing is saved yet.'}
        />
      </View>
    </View>
  );
}

// A compact muscle or equipment label under the title
function Label({ text }: { text: string }) {
  const { colors } = useTheme();

  return (
    <View
      style={{
        paddingHorizontal: spacing.md + 2,
        paddingVertical: spacing.xs + 2,
        borderRadius: radii.pill,
        borderWidth: layout.borderWidth.thin,
        borderColor: colors.border,
        backgroundColor: colors.surfaceMuted,
      }}
    >
      <AppText variant="label" numberOfLines={1} maxFontSizeMultiplier={1.3}>
        {text}
      </AppText>
    </View>
  );
}

// One dot per set: emerald for those done, the next one outlined in emerald, the rest outlined plain. The words
// beside it say all of it, so a screen reader skips the dots.
function SetDots({ total, done }: { total: number; done: number }) {
  const { colors } = useTheme();

  return (
    <View
      testID="exercise-set-dots"
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm }}
    >
      {Array.from({ length: total }, (_, index) => (
        <View
          key={index}
          testID={`exercise-set-dot-${index + 1}`}
          style={{
            width: 10,
            height: 10,
            borderRadius: 5,
            borderWidth: layout.borderWidth.thick - 0.5,
            borderColor: index <= done ? colors.primary : colors.borderStrong,
            backgroundColor: index < done ? colors.primary : 'transparent',
          }}
        />
      ))}
    </View>
  );
}

function Instructions({ exercise }: { exercise: PlannedExercise }) {
  const { colors } = useTheme();
  const content = instructionsContent(exercise);

  if (content.kind === 'none') return <Unavailable tab="instructions" />;
  if (content.kind === 'description') {
    return (
      <AppText testID="exercise-description" color="textSecondary" style={{ fontSize: 15, lineHeight: 23 }}>
        {content.text}
      </AppText>
    );
  }
  return (
    <View testID="exercise-steps" style={{ gap: spacing.lg }}>
      {content.steps.map((step, index) => (
        <View
          key={index}
          testID={`exercise-step-${index + 1}`}
          accessible
          accessibilityLabel={`Step ${index + 1}. ${step}`}
          style={{ flexDirection: 'row', alignItems: 'flex-start', gap: spacing.md + 2 }}
        >
          <View
            style={{
              width: STEP_BADGE,
              height: STEP_BADGE,
              borderRadius: STEP_BADGE / 2,
              alignItems: 'center',
              justifyContent: 'center',
              backgroundColor: colors.surfaceMuted,
              borderWidth: layout.borderWidth.thin,
              borderColor: colors.border,
            }}
          >
            <AppText variant="label" style={{ fontSize: 15, fontWeight: '700' }}>
              {index + 1}
            </AppText>
          </View>
          {/* the text is lined up with the badge's middle */}
          <AppText color="textSecondary" style={{ flex: 1, fontSize: 15, lineHeight: 22, paddingTop: (STEP_BADGE - 22) / 2 }}>
            {step}
          </AppText>
        </View>
      ))}
    </View>
  );
}

function Muscles({ exercise }: { exercise: PlannedExercise }) {
  const muscles = exerciseMuscles(exercise);
  if (!muscles) return <Unavailable tab="muscles" />;

  return (
    <View testID="exercise-muscles" style={{ gap: spacing.lg }}>
      {muscles.primary.length > 0 ? <MuscleGroup title="Primary" names={muscles.primary} main /> : null}
      {muscles.secondary.length > 0 ? <MuscleGroup title="Secondary" names={muscles.secondary} main={false} /> : null}
    </View>
  );
}

function MuscleGroup({ title, names, main }: { title: string; names: string[]; main: boolean }) {
  const { colors } = useTheme();

  return (
    <View
      testID={`exercise-muscles-${title.toLowerCase()}`}
      accessible
      accessibilityLabel={`${title} muscles: ${names.join(', ')}`}
      style={{ gap: spacing.sm }}
    >
      <Heading text={title} />
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm }}>
        {names.map((name) => (
          <View
            key={name}
            style={{
              paddingHorizontal: spacing.md + 2,
              paddingVertical: spacing.xs + 2,
              borderRadius: radii.pill,
              borderWidth: layout.borderWidth.thin,
              borderColor: main ? colors.primary : colors.border,
              backgroundColor: main ? colors.primarySubtle : colors.surface,
            }}
          >
            <AppText variant="label" style={{ color: main ? colors.accent : colors.textSecondary }}>
              {name}
            </AppText>
          </View>
        ))}
      </View>
    </View>
  );
}

function Tips({ exercise }: { exercise: PlannedExercise }) {
  const items = tipItems(exercise);
  if (items.length === 0) return <Unavailable tab="tips" />;

  return (
    <View testID="exercise-tips" style={{ gap: spacing.lg }}>
      {items.map((item) => (
        <View key={item.id} testID={`exercise-tip-${item.id}`} accessible accessibilityLabel={`${item.label}. ${item.text}`} style={{ gap: spacing.xs }}>
          <Heading text={item.label} />
          <AppText color="textSecondary" style={{ fontSize: 15, lineHeight: 22 }}>
            {item.text}
          </AppText>
        </View>
      ))}
    </View>
  );
}

// The small capital heading of a group in a tab
function Heading({ text }: { text: string }) {
  return (
    <AppText
      variant="caption"
      color="textMuted"
      style={{ fontSize: 12, lineHeight: 16, letterSpacing: 1.2, textTransform: 'uppercase', fontWeight: '600' }}
    >
      {text}
    </AppText>
  );
}

// What a tab says when the exercise has nothing for it: one short line, not a made-up one
function Unavailable({ tab }: { tab: ExerciseTab }) {
  return (
    <AppText testID="exercise-unavailable" color="textMuted" style={{ fontSize: 15, lineHeight: 22 }}>
      {UNAVAILABLE[tab]}
    </AppText>
  );
}
