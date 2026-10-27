import { View } from 'react-native';

import { AppText } from '../components';
import { layout, radii, spacing, typography, useTheme } from '../theme';
import type { ChatMessage } from './types';

// How wide a bubble may grow, as a share of the conversation's width: the shorter side stays empty, so the
// two speakers are told apart by where they sit as well as by color.
const MAX_BUBBLE_WIDTH = '82%';
// The corner next to the speaker is nearly square, as in a message app: it points at who is talking.
const POINTED_CORNER = spacing.xs;
const DOT_SIZE = spacing.sm;

const speaker = (role: ChatMessage['role']) => (role === 'user' ? 'You' : 'Formiq Coach');

// One message. The coach's sits on the left on the plain surface; the user's on the right, tinted emerald with
// an emerald outline, as a chosen option is elsewhere in the app. Color is never the only signal: the side,
// and the speaker named for a screen reader, say the same.
export function MessageBubble({ message }: { message: ChatMessage }) {
  const { colors } = useTheme();
  const mine = message.role === 'user';

  return (
    <View
      testID={`message-${message.id}`}
      accessible
      accessibilityLabel={`${speaker(message.role)}: ${message.text}`}
      style={[
        bubbleBase,
        {
          alignSelf: mine ? 'flex-end' : 'flex-start',
          borderBottomRightRadius: mine ? POINTED_CORNER : radii.lg,
          borderBottomLeftRadius: mine ? radii.lg : POINTED_CORNER,
          borderColor: mine ? colors.accent : colors.border,
          backgroundColor: mine ? colors.primarySubtle : colors.surface,
        },
      ]}
    >
      <AppText>{message.text}</AppText>
    </View>
  );
}

// Shown in the coach's place while its reply is on its way: three still dots. They do not move, so there is
// nothing to switch off for a person who asks for less motion; the words are announced politely instead.
export function TypingBubble() {
  const { colors } = useTheme();

  return (
    <View
      testID="typing-indicator"
      accessible
      accessibilityLabel="Formiq Coach is typing"
      accessibilityLiveRegion="polite"
      style={[
        bubbleBase,
        {
          alignSelf: 'flex-start',
          flexDirection: 'row',
          alignItems: 'center',
          gap: spacing.xs + 2,
          // as tall as a line of text, so the reply does not make the list jump
          minHeight: typography.body.lineHeight + 2 * spacing.md,
          borderBottomLeftRadius: POINTED_CORNER,
          borderColor: colors.border,
          backgroundColor: colors.surface,
        },
      ]}
    >
      {[0, 1, 2].map((dot) => (
        <View
          key={dot}
          style={{ width: DOT_SIZE, height: DOT_SIZE, borderRadius: DOT_SIZE / 2, backgroundColor: colors.textMuted }}
        />
      ))}
    </View>
  );
}

const bubbleBase = {
  maxWidth: MAX_BUBBLE_WIDTH,
  paddingVertical: spacing.md - layout.borderWidth.thin,
  paddingHorizontal: spacing.lg - layout.borderWidth.thin,
  borderWidth: layout.borderWidth.thin,
  borderRadius: radii.lg,
} as const;
