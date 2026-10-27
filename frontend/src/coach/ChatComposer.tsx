import { useEffect, useRef, useState } from 'react';
import { Keyboard, Pressable, TextInput, View, type StyleProp, type TextInputInstance, type ViewStyle } from 'react-native';

import { AppIcon } from '../components';
import { layout, radii, spacing, typography, useTheme } from '../theme';
import { canSend, cleanDraft, MAX_MESSAGE_LENGTH } from './conversation';

// A message that grows past this many lines scrolls inside the field instead of pushing the conversation off
// the screen.
const MAX_LINES = 5;
const MAX_INPUT_HEIGHT = typography.body.lineHeight * MAX_LINES + 2 * spacing.md;

type ChatComposerProps = {
  // Sends the message; says whether it was sent. The draft is cleared only when it was.
  onSend: (text: string) => boolean;
  // something is going on that a new message would cross (the coach answering the last one, a workout being
  // applied): the field stays open for the next message, sending waits
  busy: boolean;
  // What the field says while it is empty.
  placeholder?: string;
  // Raised by one each time the screen wants the field focused (the keyboard up, ready for the user's words).
  focusSignal?: number;
  style?: StyleProp<ViewStyle>;
};

// The message field and the round send button at the foot of the screen. The field grows with what is typed,
// up to a few lines; Enter starts a new line, and the button sends. The button is dimmed and does nothing
// while there is nothing to send (blank, or only spaces) or the coach is still answering.
//
// It is a TextInput of its own, not AppInput: AppInput is a labelled single-line form field, and a message
// field is a multi-line one with a button beside it.
export function ChatComposer({ onSend, busy, placeholder = 'Message Formiq Coach', focusSignal = 0, style }: ChatComposerProps) {
  const { colors } = useTheme();
  const [draft, setDraft] = useState('');
  const [focused, setFocused] = useState(false);
  const field = useRef<TextInputInstance>(null);
  const sendable = canSend(draft, busy);
  const borderWidth = focused ? layout.borderWidth.thick : layout.borderWidth.thin;

  // Android keeps a field focused when its keyboard is put away (the back button), which leaves the focus
  // outline on a field nothing is typing into: the field lets go when the keyboard goes.
  useEffect(() => {
    const subscription = Keyboard.addListener('keyboardDidHide', () => field.current?.blur());
    return () => subscription.remove();
  }, []);

  useEffect(() => {
    if (focusSignal > 0) field.current?.focus();
  }, [focusSignal]);

  const submit = () => {
    if (!canSend(draft, busy)) return;
    if (onSend(cleanDraft(draft))) setDraft('');
  };

  return (
    <View
      testID="chat-composer"
      style={[
        {
          flexDirection: 'row',
          alignItems: 'flex-end',
          gap: spacing.sm,
          paddingTop: spacing.sm,
          paddingBottom: spacing.md,
          borderTopWidth: layout.borderWidth.thin,
          borderTopColor: colors.divider,
          backgroundColor: colors.background,
        },
        style,
      ]}
    >
      <TextInput
        ref={field}
        testID="chat-input"
        accessibilityLabel="Message"
        accessibilityHint="Write a message to Formiq Coach"
        placeholder={placeholder}
        placeholderTextColor={colors.textMuted}
        selectionColor={colors.accent}
        cursorColor={colors.accent}
        maxFontSizeMultiplier={layout.maxFontScale}
        multiline
        maxLength={MAX_MESSAGE_LENGTH}
        value={draft}
        onChangeText={setDraft}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        style={[
          typography.body,
          {
            flex: 1,
            minHeight: layout.touchTarget,
            maxHeight: MAX_INPUT_HEIGHT,
            // the border grows on focus; the padding shrinks by as much so the text stays put
            paddingHorizontal: spacing.lg - borderWidth,
            paddingVertical: spacing.md - borderWidth,
            textAlignVertical: 'center',
            borderWidth,
            borderColor: focused ? colors.accent : colors.borderStrong,
            borderRadius: layout.touchTarget / 2,
            color: colors.textPrimary,
            backgroundColor: colors.surface,
          },
        ]}
      />
      <Pressable
        testID="send-button"
        accessibilityRole="button"
        accessibilityLabel="Send message"
        accessibilityState={{ disabled: !sendable }}
        disabled={!sendable}
        onPress={submit}
        style={({ pressed }) => ({
          width: layout.touchTarget,
          height: layout.touchTarget,
          alignItems: 'center',
          justifyContent: 'center',
          borderRadius: radii.pill,
          backgroundColor: !sendable ? colors.disabledBackground : pressed ? colors.primaryPressed : colors.primary,
        })}
      >
        <AppIcon name="arrow-up" size={spacing.xl} color={sendable ? 'textOnPrimary' : 'disabledText'} />
      </Pressable>
    </View>
  );
}
