import { useState } from 'react';
import { Pressable, ScrollView, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { AppButton, AppIcon, AppText, Notice, Toast, useToast, type IconName } from '../components';
import { fadeGradient } from '../components/FadeEdge';
import { FixedTheme, spacing, useTheme } from '../theme';
import { workoutCardColors } from './categoryColors';
import { MuscleFocus } from './MuscleFocus';
import {
  coversPhrase,
  exerciseCountLabel,
  formatMinutes,
  groupBySection,
  muscleFocus,
  type PlannedExercise,
  type WorkoutDetailsData,
} from './planDetails';
import { SectionCard } from './SectionCard';
import { TOP_BAR_HEIGHT, TOP_BAR_MARGIN, WorkoutHero } from './WorkoutHero';
import { resolveWorkoutVisual } from './workoutImages';

// What "Start Workout" says while the app cannot start a session. Nothing is started, and nothing is made to
// look started.
export const START_UNAVAILABLE_NOTICE = "Starting a workout isn't available yet. Nothing was started.";
// How long a notice stays: longer than a one-line one, since the first is a sentence
const NOTICE_MS = 4000;
// The side space of the title block and the buttons, a little wider than the cards' (the design's)
const GUTTER = spacing.lg + spacing.xs;
const BUTTON_SIZE = TOP_BAR_HEIGHT;
// the page's color fading in over the last of the scroll, so rows go under the button instead of being cut
const BOTTOM_FADE_HEIGHT = spacing.xl + spacing.xs;
// How solid the page-colored veil behind the status bar is at most while the photograph is under it. The
// photograph is dark, so on the dark page a faint one is enough for white icons; on the pale page the icons
// are dark, so the photograph needs more.
const VEIL_STRENGTH = { dark: 0.35, light: 0.8 } as const;
// Once the page has scrolled this far the photograph is gone and rows pass under the status bar: the veil is
// then nearly solid, so a row never shows through the clock and the icons.
const SCROLLED_AT = 40;
const SCROLLED_VEIL = 0.96;

type WorkoutDetailsScreenProps = {
  // Everything shown comes from here. The app passes a made-up fixture for now (src/mock/workoutDetailsMock.ts);
  // a connected screen will pass what the backend's plan says, and this screen will not change.
  workout: WorkoutDetailsData;
  onBack: () => void;
  // opens one exercise's details
  onOpenExercise: (exercise: PlannedExercise) => void;
  // opens the coach with this workout as its context. Nothing is edited or saved by pressing it: the workout
  // stays as it is until a revised proposal is approved there.
  onEditWithAI: () => void;
  // Starts the workout. Left out while the app has no workout session flow: the button then says it is not
  // available yet and starts nothing.
  onStart?: () => void;
};

// One workout in full: a photograph of its kind behind its title, its length and exercise count, what muscles
// it covers, the "Workout Plan" with an Edit with AI button, and the exercises in three ordered cards (warm-up,
// main workout, cool-down) that fold away. "Start Workout" stays at the bottom, below the scrolling page and
// above the system bar. The page itself is a solid themed color: the photograph is only the top.
export function WorkoutDetailsScreen({ workout, onBack, onOpenExercise, onEditWithAI, onStart }: WorkoutDetailsScreenProps) {
  const { colors, scheme } = useTheme();
  const insets = useSafeAreaInsets();
  const { message, show } = useToast(NOTICE_MS);
  const [focusOpen, setFocusOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  const visual = resolveWorkoutVisual(workout);
  const card = workoutCardColors(visual.category, scheme, colors);
  const sections = groupBySection(workout.exercises, workout.sectionMinutes);
  const focus = muscleFocus(workout.exercises);
  const covers = coversPhrase(focus);
  const empty = workout.exercises.length === 0;
  const sidePadding = { paddingLeft: insets.left + GUTTER, paddingRight: insets.right + GUTTER };
  const cardPadding = { paddingLeft: insets.left + spacing.lg, paddingRight: insets.right + spacing.lg };
  // the numbers on the pictures run on from one section into the next
  let next = 1;
  const numbered = sections.map((section) => {
    const firstNumber = next;
    next += section.exercises.length;
    return { section, firstNumber };
  });

  return (
    <View testID="workout-details" style={{ flex: 1, backgroundColor: colors.background }}>
      <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
      <View style={{ flex: 1 }}>
        <ScrollView
          testID="workout-details-scroll"
          style={{ flex: 1 }}
          contentContainerStyle={{ paddingBottom: spacing.xl }}
          showsVerticalScrollIndicator={false}
          scrollEventThrottle={32}
          onScroll={(event) => setScrolled(event.nativeEvent.contentOffset.y > SCROLLED_AT)}
        >
          <WorkoutHero
            title={workout.title}
            visual={visual}
            card={card}
            minutes={formatMinutes(workout.durationMinutes)}
            count={exerciseCountLabel(workout.exercises.length)}
            covers={covers}
            focusOpen={focusOpen}
            onToggleFocus={() => setFocusOpen((open) => !open)}
          />
          <View style={{ gap: spacing.sm + 2, paddingTop: spacing.sm }}>
            {focus && focusOpen ? (
              <View style={sidePadding}>
                <MuscleFocus focus={focus} card={card} />
              </View>
            ) : null}
            <View
              style={{
                flexDirection: 'row',
                flexWrap: 'wrap',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: spacing.md,
                ...sidePadding,
              }}
            >
              <AppText variant="heading" accessibilityRole="header" style={{ fontSize: 16.5, lineHeight: 22 }}>
                {`Workout Plan (${workout.exercises.length})`}
              </AppText>
              <AppButton label="Edit with AI" leadingIcon="creation" compact onPress={onEditWithAI} accessibilityHint="Opens the coach with this workout. The workout stays as it is until you approve a change." />
            </View>
            <View style={{ gap: spacing.md, ...cardPadding }}>
              {empty ? (
                <Notice title="No exercises">This workout has no exercises yet.</Notice>
              ) : (
                numbered.map(({ section, firstNumber }) => (
                  <SectionCard key={section.id} group={section} firstNumber={firstNumber} onOpenExercise={onOpenExercise} />
                ))
              )}
            </View>
          </View>
        </ScrollView>

        <View
          testID="workout-details-bottom-fade"
          pointerEvents="none"
          style={{ position: 'absolute', left: 0, right: 0, bottom: 0, height: BOTTOM_FADE_HEIGHT, backgroundImage: fadeGradient(colors.background, 0, 'to top') }}
        />
        <TopBar onBack={onBack} background={colors.background} scrolled={scrolled} />
        {/* sits at the bottom of this view, so above the button and never over it */}
        <Toast message={message} />
      </View>

      <View
        testID="workout-details-footer"
        style={{
          paddingTop: spacing.md,
          paddingBottom: insets.bottom + spacing.md,
          backgroundColor: colors.background,
          ...cardPadding,
        }}
      >
        <AppButton
          label="Start Workout"
          leadingIcon="play"
          disabled={empty}
          onPress={() => (onStart ? onStart() : show(START_UNAVAILABLE_NOTICE))}
        />
      </View>
    </View>
  );
}

// The back button, over everything and in reach at any scroll: round, dark and see-through, with a white icon,
// so it reads on the photograph and on the cards in either theme. Behind the status bar a veil of the page's
// color keeps its clock and icons readable over whatever scrolls under it.
function TopBar({ onBack, background, scrolled }: { onBack: () => void; background: string; scrolled: boolean }) {
  const insets = useSafeAreaInsets();
  const { scheme } = useTheme();

  return (
    <View pointerEvents="box-none" style={{ position: 'absolute', top: 0, left: 0, right: 0 }}>
      <View
        testID="workout-details-top-veil"
        pointerEvents="none"
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          height: insets.top + spacing.xl,
          backgroundImage: fadeGradient(background, scrolled ? 0.7 : 0, 'to bottom', scrolled ? SCROLLED_VEIL : VEIL_STRENGTH[scheme]),
        }}
      />
      <View
        testID="workout-details-top-bar"
        pointerEvents="box-none"
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          paddingTop: insets.top + TOP_BAR_MARGIN,
          paddingLeft: insets.left + GUTTER - spacing.xs,
          paddingRight: insets.right + GUTTER - spacing.xs,
        }}
      >
        <RoundButton icon="arrow-left" label="Back" onPress={onBack} />
      </View>
    </View>
  );
}

function RoundButton({ icon, label, onPress }: { icon: IconName; label: string; onPress: () => void }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={onPress}
      // the circle is smaller than a thumb: the touch area reaches out to the full target
      hitSlop={(48 - BUTTON_SIZE) / 2}
      style={({ pressed }) => ({
        width: BUTTON_SIZE,
        height: BUTTON_SIZE,
        borderRadius: BUTTON_SIZE / 2,
        alignItems: 'center',
        justifyContent: 'center',
        borderWidth: 1,
        borderColor: 'rgba(255, 255, 255, 0.32)',
        backgroundColor: pressed ? 'rgba(8, 10, 12, 0.78)' : 'rgba(8, 10, 12, 0.58)',
      })}
    >
      {/* white whatever the theme: the circle is dark in both */}
      <FixedTheme scheme="dark">
        <AppIcon name={icon} size={20} color="textPrimary" />
      </FixedTheme>
    </Pressable>
  );
}
