// Semantic color tokens. Components use these names, never hex values.
// The values follow the approved direction (near-black and charcoal, emerald, white) but are not
// taken from the UX storyboards yet: align them here, in one place.
//
// Contrast is checked in __tests__/theme-test.tsx (WCAG AA): text 4.5:1, outlines 3:1.
// Known exception: the brand green as a filled button on the light page background is 2.4:1;
// the button's own label on it is 7.7:1, so its text identifies it.

const brandGreen = '#10B981';
const ink = '#0B0D0E';

export type ColorTokens = {
  // Page and card surfaces.
  background: string;
  surface: string;
  surfaceMuted: string;
  // Lines: `border` is decorative (cards), `borderStrong` outlines controls (inputs, secondary buttons).
  border: string;
  borderStrong: string;
  divider: string;
  // Text.
  textPrimary: string;
  textSecondary: string;
  textMuted: string;
  textOnPrimary: string;
  // Brand and interactive states. `accent` is the brand green for text, icons and focus outlines.
  primary: string;
  primaryPressed: string;
  primarySubtle: string;
  accent: string;
  // A warm companion to the green for icons only (the flame and the heart): never text, never a state.
  warm: string;
  // The blue of progress data (the Progress tile's icon and bar): graphics only, never text or a state.
  progress: string;
  disabledBackground: string;
  disabledText: string;
  // Status.
  success: string;
  warning: string;
  error: string;
};

export type ColorToken = keyof ColorTokens;

// The tokens AppText accepts as a text color.
export type TextColorToken =
  | 'textPrimary'
  | 'textSecondary'
  | 'textMuted'
  | 'textOnPrimary'
  | 'accent'
  | 'disabledText'
  | 'success'
  | 'warning'
  | 'error';

export const darkColors: ColorTokens = {
  background: ink,
  surface: '#16191B',
  surfaceMuted: '#1F2326',
  border: '#2A2F32',
  borderStrong: '#5E6965',
  divider: '#22272A',
  textPrimary: '#FFFFFF',
  textSecondary: '#C4CBC8',
  textMuted: '#9AA3A0',
  textOnPrimary: ink,
  primary: brandGreen,
  primaryPressed: '#34D399',
  primarySubtle: '#0F2A22',
  accent: brandGreen,
  warm: '#FF7A59',
  progress: '#3B82F6',
  disabledBackground: '#1F2326',
  disabledText: '#5F6965',
  success: '#4ADE80',
  warning: '#FBBF24',
  error: '#F87171',
};

export const lightColors: ColorTokens = {
  background: '#F6F8F7',
  surface: '#FFFFFF',
  surfaceMuted: '#EDF1EF',
  border: '#DCE3E0',
  borderStrong: '#7A8581',
  divider: '#E4E9E7',
  textPrimary: ink,
  textSecondary: '#3D4743',
  textMuted: '#5A6560',
  textOnPrimary: ink,
  primary: brandGreen,
  primaryPressed: '#0EA371',
  primarySubtle: '#D9F5EA',
  accent: '#047857',
  warm: '#C2410C',
  progress: '#2563EB',
  disabledBackground: '#E3E8E6',
  disabledText: '#8A9490',
  success: '#15803D',
  warning: '#B45309',
  error: '#B91C1C',
};
