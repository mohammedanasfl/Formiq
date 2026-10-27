import type { ReactNode } from 'react';

import { AppText } from './AppText';

// The message under a group of choices that was left unanswered. Announced when it appears.
export function FieldError({ children }: { children: ReactNode }) {
  return (
    <AppText
      variant="caption"
      color="error"
      accessibilityRole="alert"
      accessibilityLiveRegion="polite"
    >
      {children}
    </AppText>
  );
}
