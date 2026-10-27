import { Pressable, View } from 'react-native';

import { layout, radii, spacing, useTheme, type ColorToken } from '../theme';
import { AppIcon, type IconName } from './AppIcon';
import { AppText } from './AppText';
import { ProgressBar } from './ProgressBar';

type SummaryTileProps = {
  icon: IconName;
  // the icon's own color, on a square of the same color at low strength
  iconColor: ColorToken;
  // the color of the tile's faint wash, its edge and the bar
  tint: ColorToken;
  label: string;
  value: string;
  caption: string;
  // 0 to 1, with how it is written beside the bar ("60%", "4 / 7")
  progress: number;
  progressLabel: string;
  onPress: () => void;
  testID?: string;
};

const PADDING = spacing.md;
const ICON_SQUARE = spacing.xxl + spacing.xs;
const ICON_SIZE = spacing.xl - spacing.xs;
const CHEVRON_SIZE = spacing.lg;
// The tile is half the screen wide, so its words are smaller than a card's and a larger font setting
// may grow them only a little.
const TEXT_MAX_FONT_SCALE = 1.2;
// Strengths of a token color laid over another, as the two hex digits added to it.
const WASH = '14';
const WASH_PRESSED = '26';
const EDGE = '40';
const ICON_FILL = '26';

// A half-width tile on a tab screen: one measure, how far along it is, and a way into the screen that
// has the detail. The whole tile is one button; it is read as one sentence, and the bar is only for
// the eye.
export function SummaryTile({
  icon,
  iconColor,
  tint,
  label,
  value,
  caption,
  progress,
  progressLabel,
  onPress,
  testID,
}: SummaryTileProps) {
  const { colors } = useTheme();

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${label}: ${value}, ${caption}, ${progressLabel}`}
      onPress={onPress}
      testID={testID}
      style={({ pressed }) => ({
        flex: 1,
        gap: spacing.md,
        padding: PADDING - layout.borderWidth.thin,
        overflow: 'hidden',
        borderWidth: layout.borderWidth.thin,
        borderRadius: radii.lg,
        borderColor: `${colors[tint]}${EDGE}`,
        backgroundColor: `${colors[tint]}${pressed ? WASH_PRESSED : WASH}`,
      })}
    >
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm }}>
        <View
          style={{
            width: ICON_SQUARE,
            height: ICON_SQUARE,
            alignItems: 'center',
            justifyContent: 'center',
            borderRadius: radii.md - spacing.xs,
            backgroundColor: `${colors[iconColor]}${ICON_FILL}`,
          }}
        >
          <AppIcon name={icon} size={ICON_SIZE} color={iconColor} />
        </View>
        <View style={{ flex: 1 }}>
          {/* the chevron shares the label's row, so the value below keeps the tile's whole width */}
          <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
            <AppText
              variant="label"
              maxFontSizeMultiplier={TEXT_MAX_FONT_SCALE}
              numberOfLines={1}
              style={{ fontSize: 13, lineHeight: 18, fontWeight: '400' }}
            >
              {label}
            </AppText>
            <AppIcon name="chevron-right" size={CHEVRON_SIZE} color="textMuted" />
          </View>
          <AppText
            variant="heading"
            maxFontSizeMultiplier={TEXT_MAX_FONT_SCALE}
            numberOfLines={1}
            adjustsFontSizeToFit
            minimumFontScale={0.8}
            style={{ fontSize: 17, lineHeight: 22, fontWeight: '700' }}
          >
            {value}
          </AppText>
          <AppText
            variant="caption"
            color="textMuted"
            maxFontSizeMultiplier={TEXT_MAX_FONT_SCALE}
            numberOfLines={2}
            style={{ fontSize: 12, lineHeight: 16 }}
          >
            {caption}
          </AppText>
        </View>
      </View>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm }}>
        <View style={{ flex: 1 }}>
          <ProgressBar testID={testID ? `${testID}-bar` : undefined} value={progress} color={tint} />
        </View>
        <AppText
          variant="caption"
          color="textSecondary"
          maxFontSizeMultiplier={TEXT_MAX_FONT_SCALE}
          style={{ fontSize: 12, lineHeight: 16 }}
        >
          {progressLabel}
        </AppText>
      </View>
    </Pressable>
  );
}
