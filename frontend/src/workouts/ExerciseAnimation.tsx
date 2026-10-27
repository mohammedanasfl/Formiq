import { useState } from 'react';
import { Image, View } from 'react-native';
import { Image as AnimatedImage } from 'expo-image';

import { AppIcon, AppText, DUMBBELL_LEVEL } from '../components';
import { layout, radii, spacing, useTheme } from '../theme';
import { EXERCISE_GIF_SIZE } from './exerciseGifs';
import { framedImageStyleInBox } from './framing';
import type { PlannedExercise } from './planDetails';

type ExerciseAnimationProps = {
  exercise: Pick<PlannedExercise, 'name' | 'animation' | 'image'>;
  // the width the area is drawn at, in dp; its height follows from the animation's own 16 : 9 shape
  width: number;
};

// Where the subject of a still picture is held in the area (its middle), as the row thumbnails hold theirs
const SUBJECT_AT = 0.5;

// The area under the title where the exercise is shown moving: a looping GIF, played by expo-image's image view
// (no video player and no controls). React Native's own Image is not used for it: measured on the Android
// emulator in Expo Go 58 it shows only the first frame of any GIF (even a two-frame test one), where expo-image
// plays it. The still picture below stays a plain Image. What the area shows depends on what the exercise has,
// and says so:
//   - an animation that loads: it plays (a development placeholder says it is one);
//   - none, or one that fails to load: the exercise's still picture, labelled as a still, since a still must
//     not pass for an animation; and with no picture either, a plain panel.
// Every state is drawn at the same size, so nothing on the screen moves when one gives way to another.
export function ExerciseAnimation({ exercise, width }: ExerciseAnimationProps) {
  const { colors } = useTheme();
  const [gifFailed, setGifFailed] = useState(false);
  const [stillFailed, setStillFailed] = useState(false);
  const height = Math.round((width * EXERCISE_GIF_SIZE.height) / EXERCISE_GIF_SIZE.width);
  const box = { width, height };

  const gif = exercise.animation ?? null;
  const showGif = gif !== null && !gifFailed;
  const still = exercise.image ?? null;
  const showStill = !showGif && still !== null && !stillFailed;

  // what the small label over the area says, if anything
  const caption = showGif
    ? gif.placeholder
      ? 'Placeholder animation'
      : null
    : gifFailed
      ? showStill
        ? "Animation couldn't load · still picture"
        : "Animation couldn't load"
      : showStill
        ? 'Still picture · no animation yet'
        : 'No animation yet';

  return (
    <View
      testID="exercise-animation-area"
      style={{
        ...box,
        borderRadius: radii.lg,
        // clipped: the corners are the area's, and a framed still is wider than it
        overflow: 'hidden',
        backgroundColor: colors.surfaceMuted,
        borderWidth: layout.borderWidth.thin,
        borderColor: colors.border,
      }}
    >
      {showGif ? (
        // content, not decoration: it shows how the exercise is done, so it is named
        <AnimatedImage
          testID="exercise-animation"
          source={gif.source}
          contentFit="cover"
          accessible
          accessibilityLabel={`${exercise.name}, looping animation`}
          onError={() => setGifFailed(true)}
          style={box}
        />
      ) : showStill ? (
        <Image
          testID="exercise-still"
          source={still.source}
          resizeMode="cover"
          accessible
          accessibilityLabel={`${exercise.name}, still picture`}
          onError={() => setStillFailed(true)}
          style={framedImageStyleInBox(still.framing, box, SUBJECT_AT)}
        />
      ) : (
        <View
          testID="exercise-animation-empty"
          style={{ ...box, alignItems: 'center', justifyContent: 'center' }}
        >
          <View style={{ opacity: 0.45 }}>
            <AppIcon name="dumbbell" size={40} color="textMuted" rotate={DUMBBELL_LEVEL} />
          </View>
        </View>
      )}
      {caption ? (
        <View
          testID="exercise-animation-caption"
          pointerEvents="none"
          style={{
            position: 'absolute',
            // the top left is bare in every animation: nothing of the exercise is covered
            left: spacing.sm,
            top: spacing.sm,
            paddingHorizontal: spacing.sm + 2,
            paddingVertical: spacing.xs,
            // never wider than the area, whatever the font size: a long label wraps instead of running off it
            maxWidth: width - 2 * spacing.sm,
            borderRadius: radii.pill,
            // dark and see-through over the picture, with white text, in either theme
            backgroundColor: 'rgba(8, 10, 12, 0.72)',
          }}
        >
          <AppText variant="caption" maxFontSizeMultiplier={1.2} style={{ fontSize: 12, lineHeight: 16, fontWeight: '600', color: '#FFFFFF' }}>
            {caption}
          </AppText>
        </View>
      ) : null}
    </View>
  );
}
