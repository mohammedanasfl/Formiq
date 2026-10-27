import { useState, type ReactNode } from 'react';
import { Image, Pressable, View, type ImageSourcePropType } from 'react-native';

import { AppButton, AppIcon, AppText, DUMBBELL_LEVEL, FadeEdge } from '../components';
import { FixedTheme, layout, radii, spacing, themes, useTheme } from '../theme';
import type { WorkoutCategory } from './categories';
import { workoutCardColors, type CategoryColors } from './categoryColors';
import { framedImageStyle } from './framing';
import type { WorkoutCardData } from './types';
import { resolveWorkoutVisual, WORKOUT_FALLBACK_IMAGE, type WorkoutImageFraming, type WorkoutVisual } from './workoutImages';

// The photo takes the right of the card, full height: the same box for every card, so a row of them lines
// up. The photos are wide strips, so the box shows a part of one: the part around the subject.
const PHOTO_WIDTH = '62%';
// Where the subject of a photo sits in that box, from its left edge: right of centre, clear of the text and
// of the fade.
const SUBJECT_AT = 0.66;
// Where the words stop (a share of the card's content width), so they stay on the solid side of the fade.
export const CARD_TEXT_MAX_WIDTH = '55%';
// The fade into the card's own surface: solid at the photo's left edge (so its edge is never seen) and
// through the words, then clearing quickly so the subject is not veiled. It is the only overlay: the
// photograph is not tinted. These four numbers (with SUBJECT_AT and each photo's focus) were chosen by
// compositing the real photos at the card's size, with every line of text running to CARD_TEXT_MAX_WIDTH, in
// both themes: the worst description is 8.2:1 and the worst detail line 6.3:1 (WCAG AA is 4.5:1), and at
// most 15% of the veil covers a head. A pale veil over a dark photo (the light theme) shows more than a
// dark one, which is why the fade cannot be longer.
const FADE_WIDTH = '66%';
const FADE_HOLD = 0.38;
const CARD_MIN_HEIGHT = 140;
// What lies over the whole card while it is pressed: black at 16%, so a press only ever darkens it. (Fading the
// card instead would blend it with what is behind it, and behind it is the page: on the light page a pressed
// dark card went pale.)
const PRESSED_SCRIM = 'rgba(0, 0, 0, 0.16)';
const PLACEHOLDER_ICON = spacing.xxl + spacing.sm;
const PLACEHOLDER_ICON_OPACITY = 0.35;

// A picture to try, and how to frame it: `framing` is null for one that is simply cropped to cover the box.
type PhotoSource = { source: ImageSourcePropType; framing: WorkoutImageFraming | null };

const NEUTRAL_PHOTO: PhotoSource = { source: WORKOUT_FALLBACK_IMAGE, framing: null };

// The pictures a card tries for a workout's kind, in order: its own photo, then the neutral one (which is the
// only one when the kind has no photo).
export function cardPhotoSources(visual: WorkoutVisual): PhotoSource[] {
  return visual.isFallback ? [NEUTRAL_PHOTO] : [{ source: visual.source, framing: visual.framing }, NEUTRAL_PHOTO];
}

// The cards are dark in both themes. Each sits over a dark photograph, and the design has them as dark cards (a
// charcoal surface with a hint of the workout's kind, white words) on the light page too: a pale card would lay a
// pale fade over a dark photo. So a card takes the dark palette and the dark theme's words and icons
// (`CardFrame` shows its contents in the dark theme) whatever the app's theme is.
export function cardColorsFor(category: WorkoutCategory | null): CategoryColors {
  return workoutCardColors(category, 'dark', themes.dark.colors);
}

type FrameProps = {
  testID: string;
  // the card's surface, outline and heading colors: its category's, or the dark theme's plain ones (cardColorsFor)
  card: CategoryColors;
  // the pictures to try, in order: the workout's own, then the neutral one
  sources: readonly PhotoSource[];
  onPress?: () => void;
  accessibilityLabel?: string;
  accessibilityHint?: string;
  children: ReactNode;
};

// The shell every card shares: the rounded card, the photo with its fade on the right, and the room for
// the words on the left. It is dark in both themes (charcoal with a hint of its category: see `cardColorsFor`)
// and is one button when it has something to open, and a plain view when it does not (a card that is not
// pressable must not look pressed, nor be announced as a button).
export function CardFrame({ testID, card, sources, onPress, accessibilityLabel, accessibilityHint, children }: FrameProps) {
  const style = {
    minHeight: CARD_MIN_HEIGHT,
    overflow: 'hidden' as const,
    borderWidth: layout.borderWidth.thin,
    borderRadius: radii.lg,
    borderColor: card.border,
    backgroundColor: card.blend,
  };
  const inside = (
    // the dark theme's words, icons and buttons on the dark card, whatever the app's theme
    <FixedTheme scheme="dark">
      <CardPhoto sources={sources} testID={testID} blend={card.blend} />
      <View style={{ padding: spacing.lg + spacing.xs, gap: spacing.md }}>{children}</View>
    </FixedTheme>
  );

  if (!onPress) {
    return (
      <View testID={testID} style={style}>
        {inside}
      </View>
    );
  }
  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      accessibilityHint={accessibilityHint}
      onPress={onPress}
      // No Android ripple: it is drawn under the card's contents, so the opaque photo box hid it and only the
      // text side lit up, a pale block ending at the photo's edge (and square at the corners) whenever a finger
      // came down to scroll. Nor is the card faded while pressed (see PRESSED_SCRIM). A dark scrim over the whole
      // card, photo and words alike, is the one feedback that is even and never pale; the card's own
      // rounded, clipped box keeps it inside the corners.
      style={style}
    >
      {({ pressed }) => (
        <>
          {inside}
          {pressed ? (
            <View
              testID={`${testID}-pressed`}
              pointerEvents="none"
              style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: PRESSED_SCRIM }}
            />
          ) : null}
        </>
      )}
    </Pressable>
  );
}

// The photo, its fade, and a placeholder under it. The placeholder is what shows before the picture
// has loaded and if it never does: a picture that fails is dropped for the next one, and when none is
// left the placeholder stays, so there is never a broken-image area.
function CardPhoto({ sources, testID, blend }: { sources: readonly PhotoSource[]; testID: string; blend: string }) {
  const { colors } = useTheme();
  const [failed, setFailed] = useState(0);
  const photo = sources[failed];

  return (
    <View
      pointerEvents="none"
      // clipped: a framed photo is wider than the box and must not show on the text side of it
      style={{ position: 'absolute', top: 0, right: 0, bottom: 0, width: PHOTO_WIDTH, overflow: 'hidden' }}
    >
      <View
        testID={`${testID}-placeholder`}
        accessibilityElementsHidden
        importantForAccessibility="no-hide-descendants"
        style={{
          position: 'absolute',
          top: 0,
          right: 0,
          bottom: 0,
          left: 0,
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: blend,
        }}
      >
        <View style={{ opacity: PLACEHOLDER_ICON_OPACITY }}>
          <AppIcon name="dumbbell" size={PLACEHOLDER_ICON} color="textMuted" rotate={DUMBBELL_LEVEL} />
        </View>
      </View>
      {photo ? (
        // a picture, not content: it has no name and is hidden from screen readers
        <Image
          testID={`${testID}-photo`}
          source={photo.source}
          resizeMode="cover"
          accessible={false}
          importantForAccessibility="no"
          onError={() => setFailed((count) => count + 1)}
          style={framedImageStyle(photo.framing, SUBJECT_AT)}
        />
      ) : null}
      <FadeEdge color={blend} width={FADE_WIDTH} hold={FADE_HOLD} />
    </View>
  );
}

// "23 min" and "5 exercises", each only when the workout has it: a plan stores neither a length nor a
// count, so an absent value is left out, never filled in. A value that is not a positive whole number is
// treated as absent too.
export function workoutMeta(workout: Pick<WorkoutCardData, 'durationMinutes' | 'exerciseCount'>) {
  const items: { key: 'duration' | 'exercises'; text: string }[] = [];
  const minutes = workout.durationMinutes;
  if (typeof minutes === 'number' && Number.isFinite(minutes) && Math.round(minutes) >= 1) {
    items.push({ key: 'duration', text: `${Math.round(minutes)} min` });
  }
  const count = workout.exerciseCount;
  if (typeof count === 'number' && Number.isInteger(count) && count >= 1) {
    items.push({ key: 'exercises', text: `${count} ${count === 1 ? 'exercise' : 'exercises'}` });
  }
  return items;
}

type WorkoutCardProps = {
  workout: WorkoutCardData;
  // what opens when the card is pressed; without it the card is not pressable
  onPress?: () => void;
  // the words of the call to action drawn on the card ("Start Workout"); shown only with `onPress`,
  // since a call to action that does nothing would be a lie
  actionLabel?: string;
  testID?: string;
};

// One workout: its kind, its name, a line about it, how long it is and how many exercises it has, over
// the picture for its kind. Every field but the name is optional and is left out when missing. The
// whole card is one button, named by what it says; the call to action is part of it, not a second
// button, so a screen reader meets one control per workout.
export function WorkoutCard({ workout, onPress, actionLabel, testID }: WorkoutCardProps) {
  const visual = resolveWorkoutVisual(workout);
  const card = cardColorsFor(visual.category);
  const meta = workoutMeta(workout);
  const description = workout.description?.trim() ? workout.description.trim() : null;
  const showAction = Boolean(onPress && actionLabel);
  // read as sentences, each ended once: a description that already ends in a full stop is not given a second
  const sentence = (text: string) => (/[.!?]$/.test(text) ? text : `${text}.`);
  const spoken = [
    visual.label ? `${workout.title}, ${visual.label}` : workout.title,
    description,
    meta.map((item) => item.text).join(', ') || null,
  ]
    .filter((part): part is string => Boolean(part))
    .map(sentence)
    .join(' ');

  return (
    <CardFrame
      testID={testID ?? `workout-card-${workout.id}`}
      card={card}
      sources={cardPhotoSources(visual)}
      onPress={onPress}
      accessibilityLabel={spoken}
      accessibilityHint={showAction ? actionLabel : undefined}
    >
      <View style={{ maxWidth: CARD_TEXT_MAX_WIDTH, gap: spacing.xs }}>
        {visual.label ? (
          // the category's own color, and the only place it appears as text
          <AppText
            variant="caption"
            style={{
              color: card.label,
              letterSpacing: 1.2,
              textTransform: 'uppercase',
              fontWeight: '600',
              fontSize: 12,
              lineHeight: 16,
            }}
          >
            {visual.label}
          </AppText>
        ) : null}
        <AppText variant="title" numberOfLines={2} textBreakStrategy="balanced" style={{ fontSize: 20, lineHeight: 26 }}>
          {workout.title}
        </AppText>
        {description ? (
          <AppText
            variant="label"
            color="textSecondary"
            numberOfLines={2}
            textBreakStrategy="balanced"
            style={{ fontWeight: '400' }}
          >
            {description}
          </AppText>
        ) : null}
      </View>
      {showAction ? <ActionPill label={actionLabel!} /> : null}
      {meta.length > 0 ? <WorkoutMeta items={meta} /> : null}
    </CardFrame>
  );
}

// The look of a primary button, on a card that is itself the button.
function ActionPill({ label }: { label: string }) {
  const { colors } = useTheme();
  return (
    <View
      testID="workout-card-action"
      style={{
        alignSelf: 'flex-start',
        minHeight: layout.touchTarget,
        flexDirection: 'row',
        alignItems: 'center',
        gap: spacing.sm,
        paddingHorizontal: spacing.lg,
        borderRadius: radii.md,
        backgroundColor: colors.primary,
      }}
    >
      <AppText variant="button" color="textOnPrimary">
        {label}
      </AppText>
      <AppIcon name="arrow-right" size={spacing.xl} color="textOnPrimary" />
    </View>
  );
}

// The compact row of a workout's length and exercise count; the workout's own screen draws the same row.
export function WorkoutMeta({ items }: { items: ReturnType<typeof workoutMeta> }) {
  const { colors } = useTheme();
  return (
    <View testID="workout-card-meta" style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.md }}>
      {items.map((item, index) => (
        <View key={item.key} style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.md }}>
          {index > 0 ? (
            <View style={{ width: layout.borderWidth.thin, height: spacing.lg, backgroundColor: colors.borderStrong }} />
          ) : null}
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm - spacing.xs }}>
            {item.key === 'duration' ? (
              <AppIcon name="clock-outline" size={spacing.lg + 2} color="textSecondary" />
            ) : (
              <AppIcon name="dumbbell" size={spacing.lg + 2} color="textSecondary" rotate={DUMBBELL_LEVEL} />
            )}
            <AppText variant="label" color="textSecondary" style={{ fontWeight: '400' }}>
              {item.text}
            </AppText>
          </View>
        </View>
      ))}
    </View>
  );
}

type EmptyWorkoutCardProps = {
  title: string;
  message: string;
  // the next step, when there is one; the card is not pressable itself, so this is a real button. A card with
  // neither shows only what it says: it is not offered as something to press.
  actionLabel?: string;
  onAction?: () => void;
  // the picture after the action's label: an arrow to go somewhere, `refresh` to try again
  actionIcon?: 'arrow-right' | 'refresh';
  testID?: string;
};

// What stands where a workout would be when there is none, or when there is only something to say about it
// (it is being read, it could not be, it is running, it is done): it says so, and offers the next step when
// there is one. It has the same shell as a workout card, in the plain dark colors (it is no kind of workout)
// over the neutral picture.
export function EmptyWorkoutCard({
  title,
  message,
  actionLabel,
  onAction,
  actionIcon = 'arrow-right',
  testID = 'workout-card-empty',
}: EmptyWorkoutCardProps) {
  return (
    <CardFrame testID={testID} card={cardColorsFor(null)} sources={[NEUTRAL_PHOTO]}>
      <View style={{ maxWidth: CARD_TEXT_MAX_WIDTH, gap: spacing.xs }}>
        <AppText variant="title" numberOfLines={2} textBreakStrategy="balanced" style={{ fontSize: 20, lineHeight: 26 }}>
          {title}
        </AppText>
        <AppText variant="label" color="textSecondary" textBreakStrategy="balanced" style={{ fontWeight: '400' }}>
          {message}
        </AppText>
      </View>
      {actionLabel && onAction ? (
        <AppButton label={actionLabel} onPress={onAction} trailingIcon={actionIcon} style={{ alignSelf: 'flex-start' }} />
      ) : null}
    </CardFrame>
  );
}
