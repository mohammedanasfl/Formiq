import { View } from 'react-native';

import { AppButton, AppText } from '../components';
import { layout, radii, spacing, useTheme } from '../theme';

// The coach could not answer a message that was not known to be a request for a workout: its words, and a button to
// ask again (left out when asking again cannot help: an expired session). (A failed request for a workout is the workout card in its own failed state.) The message stays in the
// conversation, and asking again does not send it a second time.
export function FailureBubble({ message, onRetry }: { message: string; onRetry?: () => void }) {
  const { colors } = useTheme();

  return (
    <View
      testID="request-failed"
      style={{
        alignSelf: 'flex-start',
        maxWidth: '82%',
        gap: spacing.md,
        padding: spacing.lg - layout.borderWidth.thin,
        borderWidth: layout.borderWidth.thin,
        borderRadius: radii.lg,
        borderBottomLeftRadius: spacing.xs,
        borderColor: colors.error,
        backgroundColor: colors.surface,
      }}
    >
      <AppText accessibilityRole="alert" accessibilityLiveRegion="polite">
        {message}
      </AppText>
      {onRetry ? <AppButton label="Try Again" leadingIcon="refresh" variant="secondary" compact onPress={onRetry} /> : null}
    </View>
  );
}
