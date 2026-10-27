import { View } from 'react-native';

import { AppButton, AppScreen, AppText, Notice } from '../../components';
import { spacing } from '../../theme';

// TEMPORARY: there is no home screen yet. This stands in for it so the flow has an honest end, and
// shows nothing that looks like a workout plan.
export function HomePlaceholderScreen({ onSignOut }: { onSignOut: () => void }) {
  return (
    <AppScreen
      scrollable
      footer={<AppButton variant="secondary" label="Log out" onPress={onSignOut} />}
    >
      <View style={{ gap: spacing.lg }}>
        <AppText variant="title" accessibilityRole="header">
          Home
        </AppText>
        <Notice title="Temporary screen">
          The home dashboard hasn&apos;t been built yet, so there is nothing to show here. Your profile
          setup is finished.
        </Notice>
      </View>
    </AppScreen>
  );
}
