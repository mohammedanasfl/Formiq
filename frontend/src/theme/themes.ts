import { darkColors, lightColors, type ColorTokens } from './colors';

export type ThemeScheme = 'dark' | 'light';

// A theme holds only what differs between schemes. Spacing, radii, typography and layout are the
// same in both, so components import them directly.
export type Theme = {
  scheme: ThemeScheme;
  colors: ColorTokens;
};

export const darkTheme: Theme = { scheme: 'dark', colors: darkColors };
export const lightTheme: Theme = { scheme: 'light', colors: lightColors };

export const themes: Record<ThemeScheme, Theme> = {
  dark: darkTheme,
  light: lightTheme,
};
