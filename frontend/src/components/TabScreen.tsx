import type { ReactNode } from 'react';
import { ScrollView, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { spacing, useTheme } from '../theme';

type TabScreenProps = {
  children: ReactNode;
  testID?: string;
};

// The page under the bottom tab bar: a solid themed background (near-black in dark, pale neutral in light:
// no photograph, no texture; the workout photographs live inside the workout cards), side padding, and a
// scrolling column. The top inset is on a view around the scroll, not inside it, so content slides away
// under the status bar's lower edge instead of passing behind its clock and icons. The bottom inset
// belongs to the tab bar.
export function TabScreen({ children, testID }: TabScreenProps) {
  const { colors, scheme } = useTheme();
  const insets = useSafeAreaInsets();

  return (
    <View testID={testID} style={{ flex: 1, backgroundColor: colors.background }}>
      <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
      <View testID="tab-inset" style={{ flex: 1, paddingTop: insets.top }}>
        <ScrollView
          testID="tab-scroll"
          style={{ flex: 1 }}
          contentContainerStyle={{
            paddingTop: spacing.lg,
            paddingBottom: spacing.xl,
            paddingLeft: insets.left + spacing.lg,
            paddingRight: insets.right + spacing.lg,
          }}
          showsVerticalScrollIndicator={false}
        >
          {children}
        </ScrollView>
      </View>
    </View>
  );
}
