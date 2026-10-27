import { View } from 'react-native';

import { AppText, Notice, TabScreen } from '../components';
import { spacing } from '../theme';
import { TABS, type TabId } from './tabs';

// The tab that is a placeholder for now: the others (Home, Discover, AI Coach, Profile) have their screens.
export type PlaceholderTab = Extract<TabId, 'progress'>;

type TabPlaceholderScreenProps = {
  tab: PlaceholderTab;
};

// TEMPORARY: stands in for a tab whose screen has not been designed yet, so the bar leads somewhere
// honest. It shows nothing that looks like a conversation, a chart or a progress figure. Each tab replaces
// it in turn.
export function TabPlaceholderScreen({ tab }: TabPlaceholderScreenProps) {
  const label = TABS.find((entry) => entry.id === tab)?.label ?? tab;

  return (
    <TabScreen testID={`${tab}-placeholder`}>
      <View style={{ gap: spacing.lg }}>
        <AppText variant="title" accessibilityRole="header">
          {label}
        </AppText>
        <Notice title="Not designed yet">
          This screen is designed after Home. Nothing here is real yet.
        </Notice>
      </View>
    </TabScreen>
  );
}
