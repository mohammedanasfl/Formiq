import { Pressable } from 'react-native';

import { AppIcon } from '../components';
import { layout, spacing } from '../theme';

// The back arrow is centered in a 48 dp touch target; moving the target left by this much lines the
// arrow's edge up with the heading and the content below.
export const BACK_OVERHANG = spacing.md;

// How wide the arrow takes in a top bar, to leave the same room on the other side.
export const BACK_SLOT = layout.touchTarget - BACK_OVERHANG;

const DISABLED_OPACITY = 0.4;

type BackButtonProps = {
  disabled?: boolean;
  onPress: () => void;
};

// The arrow at the top left of the dark screens over the gym photo.
export function BackButton({ disabled = false, onPress }: BackButtonProps) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="Back"
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      style={{
        width: layout.touchTarget,
        height: layout.touchTarget,
        marginLeft: -BACK_OVERHANG,
        alignItems: 'center',
        justifyContent: 'center',
        // dimmed while it does nothing, such as during a save
        opacity: disabled ? DISABLED_OPACITY : 1,
      }}
    >
      <AppIcon name="arrow-left" color="textPrimary" />
    </Pressable>
  );
}
