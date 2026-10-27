import type { ColorTokens, ThemeScheme } from '../theme';
import type { WorkoutCategory } from './categories';

// The one place that says what color a workout category has. A card's photograph and this color tell its
// kind apart; Formiq's own emerald is kept for actions (the call-to-action pill, selected navigation), so
// no category uses it: the teal of core is a blue-green, well apart from `colors.primary`.
//
// Per category and theme, three tokens (the dark tints are about 10% of the accent over charcoal, the
// light ones about 10% over white, so a card stays a charcoal or white card with a hint of its kind):
//
//   label   the heading above the title ("STRENGTH"), read on `blend`
//   border  the card's outline: the accent, held back
//   blend   the card's surface, on the text side: the photograph fades into this color, so there is no wash
//           over the photograph itself
//   chip    the fill of a small pill that wears the label color (the workout screen's "Covers core"), a little
//           stronger than `blend`
//
// Checked in __tests__/workout-category-colors-test.tsx: the label is at least 4.5:1 on `blend` (WCAG AA),
// and so are the theme's title and description colors on it. The light labels are the accent darkened to
// get there; the dark ones are the accent lightened a little.

export type CategoryColors = {
  label: string;
  border: string;
  blend: string;
  chip: string;
};

// A Record over every category: a category added without colors is a type error.
export const CATEGORY_COLORS: Record<WorkoutCategory, Record<ThemeScheme, CategoryColors>> = {
  // teal
  core: {
    dark: { label: '#3FC2AE', border: '#2A6A61', blend: '#1A2A2A', chip: '#142C29' },
    light: { label: '#0F766E', border: '#A6CCC9', blend: '#E7F1F0', chip: '#E5F0EF' },
  },
  // blue
  'upper-body': {
    dark: { label: '#6AA2F7', border: '#3E5B84', blend: '#1E2731', chip: '#1B2636' },
    light: { label: '#1D4ED8', border: '#ABBDF0', blend: '#E8EDFB', chip: '#E6ECFB' },
  },
  // warm orange
  'lower-body': {
    dark: { label: '#F29A45', border: '#7F572F', blend: '#2C261F', chip: '#322517' },
    light: { label: '#B4470A', border: '#E4BBA4', blend: '#F8EDE6', chip: '#F7EBE4' },
  },
  // violet
  'full-body': {
    dark: { label: '#A98BF3', border: '#5C4F82', blend: '#252431', chip: '#262235' },
    light: { label: '#6D28D9', border: '#C9B0F1', blend: '#F0EAFB', chip: '#EFE7FB' },
  },
  // red
  cardio: {
    dark: { label: '#F07474', border: '#7E4446', blend: '#2C2224', chip: '#321F1F' },
    light: { label: '#B42323', border: '#E4AEAE', blend: '#F8E9E9', chip: '#F7E7E7' },
  },
  // cyan
  mobility: {
    dark: { label: '#35C8E6', border: '#256C7C', blend: '#192A2F', chip: '#122D33' },
    light: { label: '#0B6F86', border: '#A5CAD2', blend: '#E7F1F3', chip: '#E4EFF2' },
  },
  // golden amber
  recovery: {
    dark: { label: '#E6B93F', border: '#7A652C', blend: '#2B291F', chip: '#302A16' },
    light: { label: '#8A5E00', border: '#D4C3A1', blend: '#F3EFE6', chip: '#F2EDE3' },
  },
  // muted plum
  beginner: {
    dark: { label: '#CF86C4', border: '#6E4D6C', blend: '#28242C', chip: '#2C222D' },
    light: { label: '#8E2F82', border: '#D5B2D0', blend: '#F4EAF2', chip: '#F3E8F1' },
  },
};

// The colors a card is drawn in. A workout with no known category has no heading and no accent, so it gets
// the plain surface and outline of the theme: nothing is made up for it.
export function workoutCardColors(
  category: WorkoutCategory | null,
  scheme: ThemeScheme,
  colors: ColorTokens,
): CategoryColors {
  if (!category) return { label: colors.textSecondary, border: colors.border, blend: colors.surface, chip: colors.surfaceMuted };
  return CATEGORY_COLORS[category][scheme];
}
