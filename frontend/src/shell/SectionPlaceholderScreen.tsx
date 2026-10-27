import { ScrollView, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { AppText, Notice } from '../components';
import { BackButton } from '../onboarding/BackButton';
import { spacing, useTheme } from '../theme';
import { SECTION_TITLES, type SectionId } from './tabs';

type SectionPlaceholderScreenProps = {
  section: SectionId;
  onBack: () => void;
};

// TEMPORARY: stands in for a screen that opens over the tabs and has not been designed yet (Workouts,
// Nutrition & recovery, Exercises, Mobility), so every control that leads to one lands somewhere honest.
// Workouts and Nutrition were tabs before the bar changed: this is the same screen, now reached from Home
// and Discover, with a Back arrow instead of a bar under it. It shows nothing that looks like a workout, a
// meal or an exercise.
export function SectionPlaceholderScreen({ section, onBack }: SectionPlaceholderScreenProps) {
  const { colors, scheme } = useTheme();
  const insets = useSafeAreaInsets();
  const sidePadding = { paddingLeft: insets.left + spacing.lg, paddingRight: insets.right + spacing.lg };

  return (
    <View testID={`${section}-placeholder`} style={{ flex: 1, backgroundColor: colors.background }}>
      <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
      <View style={{ flex: 1, paddingTop: insets.top, paddingBottom: insets.bottom }}>
        <View style={sidePadding}>
          <BackButton onPress={onBack} />
        </View>
        <ScrollView contentContainerStyle={{ paddingTop: spacing.sm, paddingBottom: spacing.xl, ...sidePadding }}>
          <View style={{ gap: spacing.lg }}>
            <AppText variant="title" accessibilityRole="header">
              {SECTION_TITLES[section]}
            </AppText>
            <Notice title="Not designed yet">
              This screen is designed after Home. Nothing here is real yet.
            </Notice>
          </View>
        </ScrollView>
      </View>
    </View>
  );
}
