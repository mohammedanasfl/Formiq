import { Modal, Pressable, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { AppIcon, AppText, type IconName } from '../components';
import { layout, radii, spacing, useTheme } from '../theme';
import { COACH_HEADER_HEIGHT } from './CoachHeader';

export type CoachMenuItem = {
  id: string;
  label: string;
  icon: IconName;
  onPress: () => void;
  // a switch: shows a tick when it is on
  checked?: boolean;
  disabled?: boolean;
  hint?: string;
};

type CoachMenuProps = {
  visible: boolean;
  items: readonly CoachMenuItem[];
  onClose: () => void;
};

// The overflow menu: a small card just under the header's menu button, over a see-through layer that closes it
// when pressed. Choosing an item runs it and closes the menu. (The back button of Android closes the menu first:
// that is the Modal's own.)
export function CoachMenu({ visible, items, onClose }: CoachMenuProps) {
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();

  return (
    <Modal transparent visible={visible} animationType="fade" statusBarTranslucent onRequestClose={onClose}>
      <Pressable testID="coach-menu-backdrop" accessibilityRole="button" accessibilityLabel="Close menu" style={StyleSheet.absoluteFill} onPress={onClose} />
      <View
        testID="coach-menu"
        accessibilityRole="menu"
        style={{
          position: 'absolute',
          top: insets.top + COACH_HEADER_HEIGHT - spacing.sm,
          right: insets.right + spacing.lg,
          minWidth: 220,
          maxWidth: '86%',
          paddingVertical: spacing.xs,
          borderWidth: layout.borderWidth.thin,
          borderRadius: radii.md,
          borderColor: colors.borderStrong,
          backgroundColor: colors.surface,
        }}
      >
        {items.map((item) => (
          <Pressable
            key={item.id}
            accessibilityRole="menuitem"
            accessibilityLabel={item.label}
            accessibilityHint={item.hint}
            accessibilityState={{ disabled: item.disabled ?? false, checked: item.checked }}
            disabled={item.disabled}
            onPress={() => {
              item.onPress();
              onClose();
            }}
            style={({ pressed }) => ({
              minHeight: layout.touchTarget,
              flexDirection: 'row',
              alignItems: 'center',
              gap: spacing.md,
              paddingHorizontal: spacing.lg,
              backgroundColor: pressed ? colors.surfaceMuted : 'transparent',
              opacity: item.disabled ? 0.45 : 1,
            })}
          >
            <AppIcon name={item.icon} size={spacing.xl - spacing.xs} color="textSecondary" />
            <AppText style={{ flex: 1 }}>{item.label}</AppText>
            {item.checked ? <AppIcon name="check" size={spacing.xl - spacing.xs} color="accent" /> : null}
          </Pressable>
        ))}
      </View>
    </Modal>
  );
}
