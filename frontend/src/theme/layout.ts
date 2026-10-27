import { spacing } from './spacing';

export const layout = {
  // Minimum height of anything tappable (Material's 48 dp; Apple asks for 44 pt).
  touchTarget: 48,
  screenPadding: spacing.xl,
  borderWidth: { thin: 1, thick: 2 },
  // Text follows the user's font size setting up to this factor, so layouts do not break.
  maxFontScale: 1.5,
} as const;
