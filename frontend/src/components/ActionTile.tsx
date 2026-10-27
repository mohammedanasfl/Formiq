import { Pressable, View } from 'react-native';

import { layout, radii, spacing, useTheme } from '../theme';
import { AppIcon, type IconName } from './AppIcon';
import { AppText } from './AppText';

type ActionTileProps = {
  icon: IconName;
  title: string;
  description: string;
  onPress: () => void;
  testID?: string;
};

const ICON_SIZE = spacing.xl;
// The tile is half the screen wide, so its words are smaller than a card's and a larger font setting
// may grow them only a little.
const TEXT_MAX_FONT_SCALE = 1.2;

// A half-width shortcut: an icon, what it does, and what it opens. One button, named by its title and
// description; the icon is only for the eye. It has no chevron: the icon and the card already say it
// can be tapped, and the words need the room.
export function ActionTile({ icon, title, description, onPress, testID }: ActionTileProps) {
  const { colors } = useTheme();

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${title}. ${description}`}
      onPress={onPress}
      testID={testID}
      style={({ pressed }) => ({
        flex: 1,
        minHeight: layout.touchTarget + spacing.md,
        flexDirection: 'row',
        alignItems: 'center',
        gap: spacing.md,
        padding: spacing.md - layout.borderWidth.thin,
        paddingLeft: spacing.lg - layout.borderWidth.thin,
        borderWidth: layout.borderWidth.thin,
        borderRadius: radii.lg,
        borderColor: colors.border,
        backgroundColor: pressed ? colors.surfaceMuted : colors.surface,
      })}
    >
      <AppIcon name={icon} size={ICON_SIZE} color="textPrimary" />
      <View style={{ flex: 1 }}>
        <AppText variant="label" maxFontSizeMultiplier={TEXT_MAX_FONT_SCALE} numberOfLines={2}>
          {title}
        </AppText>
        <AppText
          variant="caption"
          color="textMuted"
          maxFontSizeMultiplier={TEXT_MAX_FONT_SCALE}
          numberOfLines={2}
          style={{ fontSize: 12, lineHeight: 16 }}
        >
          {description}
        </AppText>
      </View>
    </Pressable>
  );
}
