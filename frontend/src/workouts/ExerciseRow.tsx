import { useState } from 'react';
import { Image, Pressable, View } from 'react-native';

import { AppIcon, AppText, DUMBBELL_LEVEL } from '../components';
import { layout, radii, spacing, useTheme } from '../theme';
import type { ExerciseImage } from './exerciseImages';
import { framedImageStyleInBox } from './framing';
import { exerciseTags, formatPrescription, type ExerciseTag, type PlannedExercise } from './planDetails';
import type { SectionColors } from './sectionColors';

// The picture's box: a wide one, close to the shape of the pictures, so most of an athlete shows. The athlete's
// point of the picture (its `focus`) sits in the middle of it. The size is fixed, so the picture is placed in
// dp, not in percent (see framing.ts for why).
const THUMB_WIDTH = 132;
const THUMB_HEIGHT = 58;
const SUBJECT_AT = 0.5;
const BADGE_SIZE = 21;
const BADGE_INSET = 3;
const CHEVRON_SIZE = spacing.xl - spacing.xs;
const PLACEHOLDER_ICON = spacing.xl;
const PLACEHOLDER_ICON_OPACITY = 0.45;

type ExerciseRowProps = {
  exercise: PlannedExercise;
  // the exercise's place in the whole workout, 1 up, shown on its picture
  number: number;
  // the colors of the section it belongs to: its number badge and its section tag
  section: SectionColors;
  // opens the exercise's details; the whole row is the button
  onPress: () => void;
  testID?: string;
};

// One exercise of a workout, inside its section's card: its picture with its number, its name, what it asks
// for ("2 sets • 30 seconds"), its two tags and a chevron. The whole row is one button, named by what it
// says. Every line but the name is left out when the exercise does not carry it: nothing is filled in.
export function ExerciseRow({ exercise, number, section, onPress, testID = `exercise-${exercise.id}` }: ExerciseRowProps) {
  const { colors } = useTheme();
  const prescription = formatPrescription(exercise);
  const tags = exerciseTags(exercise);
  // the bullet is for the eye: it is read as a pause
  const spoken = [exercise.name, prescription?.replace(' • ', ', ') ?? null, tags.length > 0 ? tags.map((tag) => tag.text).join(', ') : null]
    .filter((part): part is string => Boolean(part))
    .join('. ');

  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      accessibilityLabel={spoken}
      accessibilityHint="Opens the exercise details"
      onPress={onPress}
      android_ripple={{ color: `${colors.textPrimary}14` }}
      style={({ pressed }) => ({
        flexDirection: 'row',
        alignItems: 'center',
        gap: spacing.md,
        paddingVertical: spacing.xs + 1,
        paddingLeft: spacing.sm + 2,
        paddingRight: spacing.md + 2,
        opacity: pressed ? 0.85 : 1,
      })}
    >
      <ExerciseThumbnail image={exercise.image ?? null} number={number} section={section} testID={`${testID}-thumbnail`} />
      <View style={{ flex: 1, gap: spacing.xs }}>
        <AppText variant="body" numberOfLines={2} style={{ fontWeight: '600', fontSize: 14.5, lineHeight: 20 }}>
          {exercise.name}
        </AppText>
        {prescription ? (
          <AppText variant="caption" color="textSecondary" style={{ fontSize: 12, lineHeight: 16 }}>
            {prescription}
          </AppText>
        ) : null}
        {tags.length > 0 ? <Tags tags={tags} section={section} /> : null}
      </View>
      <AppIcon name="chevron-right" size={CHEVRON_SIZE} color="textMuted" />
    </Pressable>
  );
}

// The picture, over a placeholder, with the number badge on its corner. The placeholder is what shows when
// there is no picture, before it has loaded, and if it never does: a picture that fails is dropped, so there
// is never a broken-image box. The badge is always there: it numbers the exercise, not the picture.
function ExerciseThumbnail({
  image,
  number,
  section,
  testID,
}: {
  image: ExerciseImage | null;
  number: number;
  section: SectionColors;
  testID: string;
}) {
  const { colors } = useTheme();
  const [failed, setFailed] = useState(false);

  return (
    <View
      style={{
        width: THUMB_WIDTH,
        height: THUMB_HEIGHT,
        borderRadius: radii.sm,
        // clipped: a framed picture is wider than the box, and the corners are the box's
        overflow: 'hidden',
        backgroundColor: colors.surfaceMuted,
      }}
    >
      <View
        testID={`${testID}-placeholder`}
        accessibilityElementsHidden
        importantForAccessibility="no-hide-descendants"
        style={{ position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, alignItems: 'center', justifyContent: 'center' }}
      >
        <View style={{ opacity: PLACEHOLDER_ICON_OPACITY }}>
          <AppIcon name="dumbbell" size={PLACEHOLDER_ICON} color="textMuted" rotate={DUMBBELL_LEVEL} />
        </View>
      </View>
      {image && !failed ? (
        // a picture, not content: the row's name says what the exercise is
        <Image
          testID={testID}
          source={image.source}
          resizeMode="cover"
          accessible={false}
          importantForAccessibility="no"
          onError={() => setFailed(true)}
          style={framedImageStyleInBox(image.framing, { width: THUMB_WIDTH, height: THUMB_HEIGHT }, SUBJECT_AT)}
        />
      ) : null}
      <View
        testID={`${testID}-badge`}
        accessibilityElementsHidden
        importantForAccessibility="no-hide-descendants"
        style={{
          position: 'absolute',
          top: BADGE_INSET,
          left: BADGE_INSET,
          width: BADGE_SIZE,
          height: BADGE_SIZE,
          borderRadius: BADGE_SIZE / 2,
          alignItems: 'center',
          justifyContent: 'center',
          borderWidth: layout.borderWidth.thin + 0.5,
          borderColor: section.accent,
          backgroundColor: section.badge,
        }}
      >
        <AppText variant="caption" style={{ fontSize: 11.5, lineHeight: 14, fontWeight: '700' }}>
          {number}
        </AppText>
      </View>
    </View>
  );
}

// The two tags: the first in the section's color, the second plain.
function Tags({ tags, section }: { tags: ExerciseTag[]; section: SectionColors }) {
  const { colors } = useTheme();

  return (
    <View testID="exercise-tags" style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs + 2 }}>
      {tags.map((tag) => {
        const wearsSection = tag.tone === 'section';
        return (
          <View
            key={tag.text}
            style={{
              paddingHorizontal: spacing.sm + 1,
              paddingVertical: 2,
              borderRadius: radii.pill,
              backgroundColor: wearsSection ? section.tagBackground : colors.surfaceMuted,
            }}
          >
            <AppText
              variant="caption"
              style={{
                fontSize: 11,
                lineHeight: 15,
                fontWeight: '600',
                color: wearsSection ? section.tagText : colors.textSecondary,
              }}
            >
              {tag.text}
            </AppText>
          </View>
        );
      })}
    </View>
  );
}
