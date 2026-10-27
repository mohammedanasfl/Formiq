import { Pressable, View } from 'react-native';

import { spacing } from '../theme';
import { AppText } from './AppText';

type SectionHeaderProps = {
  title: string;
  // an optional link at the end of the row ("See all")
  actionLabel?: string;
  // for when the visible words alone do not say where it leads ("See all recent activity")
  actionAccessibilityLabel?: string;
  onAction?: () => void;
};

// The title of a block on a tab screen, with an optional link at its end.
export function SectionHeader({
  title,
  actionLabel,
  actionAccessibilityLabel,
  onAction,
}: SectionHeaderProps) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
      <AppText variant="heading" accessibilityRole="header">
        {title}
      </AppText>
      {actionLabel && onAction ? (
        <Pressable
          accessibilityRole="link"
          accessibilityLabel={actionAccessibilityLabel ?? actionLabel}
          onPress={onAction}
          // the link is short, so its touch area reaches past it to be as easy to hit as a button
          hitSlop={spacing.sm}
          style={{ paddingVertical: spacing.sm, paddingLeft: spacing.md }}
        >
          <AppText variant="label" color="accent">
            {actionLabel}
          </AppText>
        </Pressable>
      ) : null}
    </View>
  );
}
