import { Pressable, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { AppIcon, AppText } from '../components';
import { layout, spacing, useTheme } from '../theme';
import { TABS, type TabId } from './tabs';

// The bar is as tall as a comfortable thumb target plus the label under the icon.
const BAR_HEIGHT = layout.touchTarget + spacing.lg;
// Tab names are short and the bar is five equal columns wide ("AI Coach" is the longest): a larger font setting
// may grow them only a little.
const LABEL_MAX_FONT_SCALE = 1.2;

type BottomTabBarProps = {
  current: TabId;
  onSelect: (tab: TabId) => void;
};

// The five tabs along the bottom. The current one is emerald, with a filled icon; each is announced as
// a tab and as selected or not, so color is never the only signal. The bottom inset (the gesture bar)
// is part of the bar.
export function BottomTabBar({ current, onSelect }: BottomTabBarProps) {
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();

  return (
    <View
      testID="bottom-tab-bar"
      accessibilityRole="tablist"
      style={{
        flexDirection: 'row',
        paddingBottom: insets.bottom,
        paddingLeft: insets.left,
        paddingRight: insets.right,
        borderTopWidth: layout.borderWidth.thin,
        borderTopColor: colors.border,
        backgroundColor: colors.surface,
      }}
    >
      {TABS.map((tab) => {
        const selected = tab.id === current;
        return (
          <Pressable
            key={tab.id}
            accessibilityRole="tab"
            accessibilityLabel={tab.label}
            accessibilityState={{ selected }}
            onPress={() => onSelect(tab.id)}
            style={{
              flex: 1,
              minHeight: BAR_HEIGHT,
              alignItems: 'center',
              justifyContent: 'center',
              gap: spacing.xs,
            }}
          >
            <AppIcon
              name={selected ? tab.activeIcon : tab.icon}
              size={spacing.xl}
              color={selected ? 'accent' : 'textMuted'}
            />
            <AppText
              variant="caption"
              color={selected ? 'accent' : 'textMuted'}
              maxFontSizeMultiplier={LABEL_MAX_FONT_SCALE}
              numberOfLines={1}
              style={{ fontSize: 12, lineHeight: 16, fontWeight: selected ? '600' : '400' }}
            >
              {tab.label}
            </AppText>
          </Pressable>
        );
      })}
    </View>
  );
}
