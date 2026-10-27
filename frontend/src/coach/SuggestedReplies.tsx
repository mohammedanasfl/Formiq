import { Pressable, ScrollView, type StyleProp, type ViewStyle } from 'react-native';

import { AppText } from '../components';
import { layout, radii, spacing, useTheme } from '../theme';
import type { SuggestedReply } from './types';

// The chips are slimmer than a button; their touch area is still `layout.touchTarget`.
const CHIP_HEIGHT = 40;

type SuggestedRepliesProps = {
  replies: readonly SuggestedReply[];
  onSelect: (reply: SuggestedReply) => void;
  // the row's side padding, so the first chip lines up with the page's margin while the row scrolls to the edge
  style?: StyleProp<ViewStyle>;
};

// The things the coach's last message suggests saying, as pill buttons in one row that scrolls sideways: a long
// list takes one line, on any screen and at any text size, and a chip cut off at the edge shows there is more.
// Pressing one is the same as typing and sending its words.
export function SuggestedReplies({ replies, onSelect, style }: SuggestedRepliesProps) {
  const { colors } = useTheme();

  return (
    <ScrollView
      testID="suggested-replies"
      accessibilityLabel="Suggested replies"
      horizontal
      keyboardShouldPersistTaps="handled"
      showsHorizontalScrollIndicator={false}
      style={{ flexGrow: 0 }}
      contentContainerStyle={[{ gap: spacing.sm, alignItems: 'center' }, style]}
    >
      {replies.map((reply) => (
        <Pressable
          key={reply.id}
          accessibilityRole="button"
          accessibilityLabel={reply.label}
          hitSlop={(layout.touchTarget - CHIP_HEIGHT) / 2}
          onPress={() => onSelect(reply)}
          style={({ pressed }) => ({
            minHeight: CHIP_HEIGHT,
            paddingHorizontal: spacing.lg - layout.borderWidth.thin,
            alignItems: 'center',
            justifyContent: 'center',
            borderRadius: radii.pill,
            borderWidth: layout.borderWidth.thin,
            borderColor: colors.accent,
            backgroundColor: pressed ? colors.primarySubtle : colors.surface,
          })}
        >
          <AppText variant="label">{reply.label}</AppText>
        </Pressable>
      ))}
    </ScrollView>
  );
}
