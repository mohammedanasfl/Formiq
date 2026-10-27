import type { ReactElement } from 'react';
import { render } from '@testing-library/react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { ThemeProvider, type ThemeScheme } from '../src/theme';

// Renders a component the way the app does: inside the safe-area and theme providers.
export function renderWithTheme(ui: ReactElement, scheme: ThemeScheme = 'dark') {
  return render(
    <SafeAreaProvider>
      <ThemeProvider initialScheme={scheme}>{ui}</ThemeProvider>
    </SafeAreaProvider>,
  );
}
