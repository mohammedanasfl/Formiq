import { Pressable, View } from 'react-native';

import { layout, spacing, useTheme } from '../theme';
import { AppText } from './AppText';

export type UnderlineTab<Id extends string> = { id: Id; label: string };

type UnderlineTabsProps<Id extends string> = {
  tabs: readonly UnderlineTab<Id>[];
  selected: Id;
  onSelect: (id: Id) => void;
  // names the group for a screen reader ("Exercise details")
  accessibilityLabel: string;
  testID?: string;
};

// A row of text tabs on one line, the selected one in bold white with an emerald line under it, the others
// muted. Each is a tab of a tablist with its selected state told, as tall as a button. It only says which tab
// is chosen: the screen shows what goes with it.
export function UnderlineTabs<Id extends string>({ tabs, selected, onSelect, accessibilityLabel, testID }: UnderlineTabsProps<Id>) {
  const { colors } = useTheme();

  return (
    <View
      testID={testID}
      accessibilityRole="tablist"
      accessibilityLabel={accessibilityLabel}
      style={{ flexDirection: 'row', borderBottomWidth: layout.borderWidth.thin, borderBottomColor: colors.divider }}
    >
      {tabs.map((tab) => {
        const isSelected = tab.id === selected;
        return (
          <Pressable
            key={tab.id}
            testID={testID ? `${testID}-${tab.id}` : undefined}
            accessibilityRole="tab"
            accessibilityLabel={tab.label}
            accessibilityState={{ selected: isSelected }}
            onPress={() => onSelect(tab.id)}
            style={({ pressed }) => ({
              flex: 1,
              minHeight: layout.touchTarget,
              alignItems: 'center',
              justifyContent: 'center',
              paddingHorizontal: spacing.xs,
              backgroundColor: pressed ? colors.surfaceMuted : 'transparent',
            })}
          >
            <AppText
              variant="label"
              color={isSelected ? 'textPrimary' : 'textMuted'}
              numberOfLines={1}
              maxFontSizeMultiplier={1.3}
              // the tabs share the row equally, so a long word at a large font size is made smaller, never cut
              adjustsFontSizeToFit
              minimumFontScale={0.75}
              style={{ fontSize: 15, fontWeight: isSelected ? '700' : '600' }}
            >
              {tab.label}
            </AppText>
            {/* the line sits on the divider: the layout does not move when the choice changes */}
            <View
              testID={isSelected && testID ? `${testID}-underline` : undefined}
              style={{
                position: 'absolute',
                left: spacing.sm,
                right: spacing.sm,
                bottom: -layout.borderWidth.thin,
                height: layout.borderWidth.thick,
                backgroundColor: isSelected ? colors.primary : 'transparent',
              }}
            />
          </Pressable>
        );
      })}
    </View>
  );
}
