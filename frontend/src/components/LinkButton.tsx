import { Pressable } from 'react-native';

import { layout, spacing } from '../theme';
import { AppText } from './AppText';

type LinkButtonProps = {
  label: string;
  onPress: () => void;
  // for when the visible text alone is not enough, such as several "Edit" links on one page
  accessibilityLabel?: string;
};

// Text that acts like a link: switching to another screen, or editing something. It is as tall as a
// button, so it is easy to hit.
export function LinkButton({ label, onPress, accessibilityLabel }: LinkButtonProps) {
  return (
    <Pressable
      accessibilityRole="link"
      accessibilityLabel={accessibilityLabel}
      onPress={onPress}
      style={{
        minHeight: layout.touchTarget,
        paddingHorizontal: spacing.sm,
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <AppText variant="button" color="accent">
        {label}
      </AppText>
    </Pressable>
  );
}
