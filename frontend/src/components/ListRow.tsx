import { Image, Pressable, View, type ImageSourcePropType } from 'react-native';

import { layout, radii, spacing, useTheme } from '../theme';
import { AppIcon } from './AppIcon';
import { AppText } from './AppText';

type ListRowProps = {
  title: string;
  subtitle: string;
  // a small picture before the words; it is decoration, so it has no name
  thumbnail?: ImageSourcePropType;
  onPress: () => void;
  testID?: string;
};

const THUMB_WIDTH = spacing.xxxl + spacing.sm;
const THUMB_HEIGHT = spacing.xxl + spacing.sm;
const CHEVRON_SIZE = spacing.xl - spacing.xs;

// One row of a list on a tab screen: a picture, a title, a line under it, and a chevron. One button,
// named by the title and the line under it.
export function ListRow({ title, subtitle, thumbnail, onPress, testID }: ListRowProps) {
  const { colors } = useTheme();

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${title}. ${subtitle}`}
      onPress={onPress}
      testID={testID}
      style={({ pressed }) => ({
        minHeight: layout.touchTarget + spacing.md,
        flexDirection: 'row',
        alignItems: 'center',
        gap: spacing.md,
        padding: spacing.sm + spacing.xs - layout.borderWidth.thin,
        borderWidth: layout.borderWidth.thin,
        borderRadius: radii.lg,
        borderColor: colors.border,
        backgroundColor: pressed ? colors.surfaceMuted : colors.surface,
      })}
    >
      {thumbnail ? (
        <Image
          testID={testID ? `${testID}-thumbnail` : undefined}
          source={thumbnail}
          resizeMode="cover"
          accessible={false}
          importantForAccessibility="no"
          // an explicit size: on Android an image otherwise keeps the asset's own size
          style={{ width: THUMB_WIDTH, height: THUMB_HEIGHT, borderRadius: radii.sm }}
        />
      ) : null}
      <View style={{ flex: 1 }}>
        <AppText variant="label" numberOfLines={1}>
          {title}
        </AppText>
        <AppText variant="caption" color="textMuted" numberOfLines={1}>
          {subtitle}
        </AppText>
      </View>
      <AppIcon name="chevron-right" size={CHEVRON_SIZE} color="textMuted" />
    </Pressable>
  );
}
