import { View } from 'react-native';

import { AppIcon, AppText, TabScreen } from '../components';
import type { SectionId } from '../shell/tabs';
import { spacing } from '../theme';
import type { WorkoutCategory } from '../workouts/categories';
import { CARD_TEXT_MAX_WIDTH, CardFrame, cardColorsFor, cardPhotoSources } from '../workouts/WorkoutCard';
import { resolveWorkoutVisual } from '../workouts/workoutImages';

type Area = {
  id: string;
  title: string;
  description: string;
  // the kind of workout whose photograph and colours the card wears
  category: WorkoutCategory;
  // the screen it opens
  section: SectionId;
};

// What there is to explore, in the order shown. Recovery leads to the nutrition and recovery screen: what to
// eat and drink, and how to rest, after training. The descriptions say what each area is for; none of them
// opens real content yet (see the note at the foot of the screen).
export const DISCOVER_AREAS: readonly Area[] = [
  {
    id: 'workouts',
    title: 'Workouts',
    description: 'Plans and sessions to train with.',
    category: 'full-body',
    section: 'workouts',
  },
  {
    id: 'exercises',
    title: 'Exercises',
    description: 'Moves, and how to do them well.',
    category: 'upper-body',
    section: 'exercises',
  },
  {
    id: 'mobility',
    title: 'Mobility',
    description: 'Stretch, warm up and move better.',
    category: 'mobility',
    section: 'mobility',
  },
  {
    id: 'recovery',
    title: 'Recovery',
    description: 'Food, hydration and rest after training.',
    category: 'recovery',
    section: 'nutrition',
  },
];

// What the foot of the screen says: the areas open placeholders until each screen is designed.
export const DISCOVER_NOTE = 'Each area opens a placeholder until its own screen is designed.';

type DiscoverScreenProps = {
  // opens the screen an area leads to
  onOpen: (section: SectionId) => void;
};

// The Discover tab: a place to explore workouts, exercises, mobility and recovery. Each area is a photo card
// in the style of Home's workout cards, and one button; it has no content of its own yet, so it opens a
// screen that says it has not been designed. Nothing here is a user's data.
export function DiscoverScreen({ onOpen }: DiscoverScreenProps) {
  return (
    <TabScreen testID="discover-screen">
      <View style={{ gap: spacing.xl }}>
        <View style={{ gap: spacing.xs }}>
          <AppText variant="title" accessibilityRole="header">
            Discover
          </AppText>
          <AppText color="textSecondary">Explore workouts, exercises, mobility and recovery.</AppText>
        </View>
        <View style={{ gap: spacing.md }}>
          {DISCOVER_AREAS.map((area) => (
            <DiscoverCard key={area.id} area={area} onPress={() => onOpen(area.section)} />
          ))}
        </View>
        <AppText variant="caption" color="textMuted" testID="discover-note">
          {DISCOVER_NOTE}
        </AppText>
      </View>
    </TabScreen>
  );
}

function DiscoverCard({ area, onPress }: { area: Area; onPress: () => void }) {
  const visual = resolveWorkoutVisual({ categories: [area.category] });
  const card = cardColorsFor(visual.category);

  return (
    <CardFrame
      testID={`discover-${area.id}`}
      card={card}
      sources={cardPhotoSources(visual)}
      onPress={onPress}
      accessibilityLabel={`${area.title}. ${area.description}`}
    >
      <View style={{ maxWidth: CARD_TEXT_MAX_WIDTH, gap: spacing.xs }}>
        <AppText variant="title" numberOfLines={2} style={{ fontSize: 20, lineHeight: 26 }}>
          {area.title}
        </AppText>
        <AppText variant="label" color="textSecondary" numberOfLines={2} textBreakStrategy="balanced" style={{ fontWeight: '400' }}>
          {area.description}
        </AppText>
      </View>
      {/* the card is the button: the arrow is only the cue, in the category's own color */}
      <AppIcon name="arrow-right" size={spacing.xl} tint={card.label} />
    </CardFrame>
  );
}
