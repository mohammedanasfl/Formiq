import type { ThemeScheme } from '../theme';
import type { PlanSection } from './planDetails';

// The color of each part of a workout, on the workout screen: purple for the warm-up, green for the main
// workout, blue for the cool-down. They belong to the part, not to the kind of workout (that is
// categoryColors.ts), so a core workout and a leg workout have the same three. Each section is a card with a
// tinted header band and a tinted body, an outline, and small tags that wear its accent.
//
// Per section and theme (a dark tint is the accent over the dark page, a light one the accent over white):
//
//   accent       the disc behind the section's icon, and the outline of an exercise's number badge; a white
//                glyph is read on it
//   header       the card's header band
//   rows         the card's body, behind the exercises
//   border       the card's outline
//   divider      the lines between the header and the rows, and between rows
//   tagBackground / tagText   the section's own tag on an exercise ("Core", "Warm-up")
//   badge        the fill of an exercise's number badge
//
// Checked in __tests__/workout-section-colors-test.ts: the white glyph is at least 3:1 on the accent, the tag
// text at least 4.5:1 on its tag, and the theme's title and secondary text at least 4.5:1 on the header and
// the body (WCAG AA).

export type SectionColors = {
  accent: string;
  header: string;
  rows: string;
  border: string;
  divider: string;
  tagBackground: string;
  tagText: string;
  badge: string;
};

// A Record over every section: a section added without colors is a type error.
export const SECTION_COLORS: Record<PlanSection, Record<ThemeScheme, SectionColors>> = {
  // purple
  WARM_UP: {
    dark: {
      accent: '#7C3AED',
      header: '#201638',
      rows: '#151122',
      border: '#381F67',
      divider: '#1D1432',
      tagBackground: '#311C5A',
      tagText: '#DCCBFF',
      badge: '#1D1432',
    },
    light: {
      accent: '#6D28D9',
      header: '#F0EAFB',
      rows: '#FBF9FE',
      border: '#D3BEF4',
      divider: '#EBE1FA',
      tagBackground: '#ECE3FA',
      tagText: '#5B21B6',
      badge: '#FFFFFF',
    },
  },
  // green
  MAIN_WORKOUT: {
    dark: {
      accent: '#0AA96B',
      header: '#0B2B20',
      rows: '#0B1B16',
      border: '#0B4B33',
      divider: '#0B261D',
      tagBackground: '#0B3C2A',
      tagText: '#6EF0C8',
      badge: '#0B261D',
    },
    light: {
      accent: '#068A57',
      header: '#E6F3EE',
      rows: '#F8FBFA',
      border: '#B4DCCD',
      divider: '#DCEFE7',
      tagBackground: '#DFF0E9',
      tagText: '#046C44',
      badge: '#FFFFFF',
    },
  },
  // blue
  COOL_DOWN: {
    dark: {
      accent: '#0A72E8',
      header: '#0B2037',
      rows: '#0B1622',
      border: '#0B3565',
      divider: '#0B1D31',
      tagBackground: '#0A407B',
      tagText: '#E6F1FF',
      badge: '#0B1D31',
    },
    light: {
      accent: '#0A63CF',
      header: '#E6EFFA',
      rows: '#F8FAFE',
      border: '#B6D0F1',
      divider: '#DDE9F8',
      tagBackground: '#DFEBF9',
      tagText: '#0B4DA8',
      badge: '#FFFFFF',
    },
  },
};
