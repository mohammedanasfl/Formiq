import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Appearance } from 'react-native';
import * as SystemUI from 'expo-system-ui';

import { themes, type Theme, type ThemeScheme } from './themes';

type ThemeContextValue = Theme & {
  setScheme: (scheme: ThemeScheme) => void;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

type ThemeProviderProps = {
  initialScheme?: ThemeScheme;
  children: ReactNode;
};

export function ThemeProvider({ initialScheme = 'dark', children }: ThemeProviderProps) {
  const [scheme, setScheme] = useState<ThemeScheme>(initialScheme);
  const value = useMemo(() => ({ ...themes[scheme], setScheme }), [scheme]);

  useEffect(() => {
    // Asks the platform to draw its own parts (dialogs, pickers) in the chosen scheme. The Android
    // keyboard belongs to the keyboard app and keeps following the phone's setting.
    Appearance.setColorScheme(scheme);
    // The root view sits behind every screen. A failure here is cosmetic, so it is ignored.
    SystemUI.setBackgroundColorAsync(themes[scheme].colors.background).catch(() => undefined);
  }, [scheme]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

type FixedThemeProps = {
  scheme: ThemeScheme;
  children: ReactNode;
};

// Shows its children in one scheme whatever the app's scheme is, for a screen designed in that
// scheme only (the welcome photo). Unlike ThemeProvider it asks the platform for nothing, so every
// other screen keeps following the app's own scheme.
export function FixedTheme({ scheme, children }: FixedThemeProps) {
  const { setScheme } = useTheme();
  const value = useMemo(() => ({ ...themes[scheme], setScheme }), [scheme, setScheme]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const value = useContext(ThemeContext);
  if (!value) {
    throw new Error('useTheme must be used inside a <ThemeProvider>.');
  }
  return value;
}
