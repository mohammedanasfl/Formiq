import type { TextStyle } from 'react-native';

// The system font is used on purpose: no font package until the storyboards call for one.
export const fontSizes = {
  caption: 13,
  label: 14,
  body: 16,
  heading: 20,
  title: 28,
  display: 44,
} as const;

export const fontWeights = {
  regular: '400',
  semibold: '600',
  bold: '700',
} as const;

export const typography = {
  display: {
    fontSize: fontSizes.display,
    lineHeight: 52,
    fontWeight: fontWeights.bold,
    letterSpacing: 1,
  },
  title: { fontSize: fontSizes.title, lineHeight: 34, fontWeight: fontWeights.bold },
  heading: { fontSize: fontSizes.heading, lineHeight: 26, fontWeight: fontWeights.semibold },
  body: { fontSize: fontSizes.body, lineHeight: 24, fontWeight: fontWeights.regular },
  button: { fontSize: fontSizes.body, lineHeight: 24, fontWeight: fontWeights.semibold },
  label: { fontSize: fontSizes.label, lineHeight: 20, fontWeight: fontWeights.semibold },
  caption: { fontSize: fontSizes.caption, lineHeight: 18, fontWeight: fontWeights.regular },
} as const satisfies Record<string, TextStyle>;

export type TextVariant = keyof typeof typography;
