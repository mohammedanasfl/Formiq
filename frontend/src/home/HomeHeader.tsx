import { View } from 'react-native';

import { AppText, ThemeToggle } from '../components';
import { spacing } from '../theme';

type HomeHeaderProps = {
  // already written out: "Good morning, Anas", or "Good morning" when there is no name (see greetingText)
  greeting: string;
  // already written out ("Tue, 20 Oct 2026")
  dateLabel: string;
};

// The top of Home: a short greeting for the time of day with the date under it in smaller, muted text, and
// the dark and light theme toggle at the end of the row. No avatar or initials (Profile is a tab), no bell
// (the app has no notifications), no emoji.
export function HomeHeader({ greeting, dateLabel }: HomeHeaderProps) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.md }}>
      <View style={{ flex: 1 }}>
        {/* two lines at most: a long name wraps instead of being cut off */}
        <AppText variant="title" accessibilityRole="header" numberOfLines={2} style={{ fontSize: 24, lineHeight: 30 }}>
          {greeting}
        </AppText>
        <AppText variant="caption" color="textMuted">
          {dateLabel}
        </AppText>
      </View>
      <ThemeToggle testID="theme-toggle" />
    </View>
  );
}
