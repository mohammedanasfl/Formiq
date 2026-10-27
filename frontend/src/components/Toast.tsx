import { useCallback, useEffect, useRef, useState } from 'react';
import { View } from 'react-native';

import { layout, radii, spacing, useTheme } from '../theme';
import { AppText } from './AppText';

const TOAST_MS = 3000;

// A short message that appears and goes by itself. `show` replaces any message still showing and
// restarts the clock; the timer is cleared when the screen goes away.
export function useToast(durationMs: number = TOAST_MS) {
  const [message, setMessage] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const show = useCallback(
    (text: string) => {
      if (timer.current) clearTimeout(timer.current);
      setMessage(text);
      timer.current = setTimeout(() => setMessage(null), durationMs);
    },
    [durationMs],
  );

  return { message, show };
}

type ToastProps = {
  message: string | null;
};

// Sits at the bottom of the nearest positioned parent and never takes a tap. It is announced politely
// when it appears.
export function Toast({ message }: ToastProps) {
  const { colors } = useTheme();
  if (!message) return null;

  return (
    <View
      testID="toast-layer"
      pointerEvents="none"
      style={{ position: 'absolute', left: spacing.lg, right: spacing.lg, bottom: spacing.lg, alignItems: 'center' }}
    >
      <View
        testID="toast"
        accessible
        accessibilityLiveRegion="polite"
        style={{
          paddingVertical: spacing.md,
          paddingHorizontal: spacing.lg,
          borderWidth: layout.borderWidth.thin,
          borderRadius: radii.md,
          borderColor: colors.borderStrong,
          backgroundColor: colors.surfaceMuted,
        }}
      >
        <AppText variant="label" style={{ textAlign: 'center' }}>
          {message}
        </AppText>
      </View>
    </View>
  );
}
