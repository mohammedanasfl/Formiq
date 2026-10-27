import { WORKOUT_CATEGORIES, type WorkoutCategory } from '../src/workouts/categories';
import { CATEGORY_COLORS, workoutCardColors, type CategoryColors } from '../src/workouts/categoryColors';
import { themes, type ThemeScheme } from '../src/theme';

const SCHEMES: ThemeScheme[] = ['dark', 'light'];
const HEX = /^#[0-9A-F]{6}$/;

// WCAG 2.x relative luminance and contrast ratio for #RRGGBB colors (the same as the theme's own test).
function luminance(hex: string) {
  const [r, g, b] = [1, 3, 5].map((at) => {
    const channel = parseInt(hex.slice(at, at + 2), 16) / 255;
    return channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function contrast(a: string, b: string) {
  const [lighter, darker] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (lighter + 0.05) / (darker + 0.05);
}
const spread = (hex: string) => {
  const channels = [1, 3, 5].map((at) => parseInt(hex.slice(at, at + 2), 16));
  return Math.max(...channels) - Math.min(...channels);
};
const all = WORKOUT_CATEGORIES.flatMap((category) =>
  SCHEMES.map((scheme) => [category, scheme, CATEGORY_COLORS[category][scheme]] as const),
);

describe('the category colors', () => {
  test('cover every category, in both themes, with the three tokens', () => {
    expect(Object.keys(CATEGORY_COLORS).sort()).toEqual([...WORKOUT_CATEGORIES].sort());
    for (const category of WORKOUT_CATEGORIES) {
      expect(Object.keys(CATEGORY_COLORS[category]).sort()).toEqual(['dark', 'light']);
      for (const scheme of SCHEMES) {
        expect(Object.keys(CATEGORY_COLORS[category][scheme]).sort()).toEqual(['blend', 'border', 'chip', 'label']);
      }
    }
  });

  test.each(all)('%s, %s theme: four plain #RRGGBB colors (no alpha, nothing left to the platform)', (_c, _s, colors) => {
    expect(colors.label).toMatch(HEX);
    expect(colors.border).toMatch(HEX);
    expect(colors.blend).toMatch(HEX);
    expect(colors.chip).toMatch(HEX);
  });

  describe.each(SCHEMES)('%s theme contrast (WCAG AA)', (scheme) => {
    const theme = themes[scheme].colors;

    test.each(WORKOUT_CATEGORIES.map((category) => [category]))('%s: heading, title and description read on the surface', (category) => {
      const { label, blend } = CATEGORY_COLORS[category][scheme];

      expect(contrast(label, blend)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(theme.textPrimary, blend)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(theme.textSecondary, blend)).toBeGreaterThanOrEqual(4.5);
    });

    test('the heading color reads on the pill that wears it ("Covers core"), which is a hint stronger than the card', () => {
      for (const category of WORKOUT_CATEGORIES) {
        const { label, chip, blend } = CATEGORY_COLORS[category][scheme];
        expect(contrast(label, chip)).toBeGreaterThanOrEqual(4.5);
        expect(chip).not.toBe(blend);
        // still a hint of the color, not a wash of it
        expect(spread(chip)).toBeLessThanOrEqual(40);
      }
    });

    test('the heading color is also readable on the page behind the card', () => {
      for (const category of WORKOUT_CATEGORIES) {
        expect(contrast(CATEGORY_COLORS[category][scheme].label, theme.background)).toBeGreaterThanOrEqual(3);
      }
    });

    test('the outline is a quiet line: seen against the page, not a frame around the card', () => {
      for (const category of WORKOUT_CATEGORIES) {
        const { border, blend } = CATEGORY_COLORS[category][scheme];
        expect(border).not.toBe(blend);
        expect(contrast(border, blend)).toBeLessThan(3.5);
        expect(contrast(border, blend)).toBeGreaterThan(1.2);
      }
    });
  });

  test('each category has its own color: no two share a heading, an outline or a surface in a theme', () => {
    for (const scheme of SCHEMES) {
      for (const token of ['label', 'border', 'blend', 'chip'] as const) {
        const values = WORKOUT_CATEGORIES.map((category) => CATEGORY_COLORS[category][scheme][token]);
        expect(new Set(values).size).toBe(WORKOUT_CATEGORIES.length);
      }
    }
  });

  test.each(all)('%s, %s theme: the surface is a hint of the color, not a wash of it', (_c, _s, colors) => {
    // a charcoal or white card that leans toward its category, nothing a bright panel
    expect(spread(colors.blend)).toBeLessThanOrEqual(24);
  });

  test('the dark surfaces are dark and the light ones light', () => {
    for (const category of WORKOUT_CATEGORIES) {
      expect(luminance(CATEGORY_COLORS[category].dark.blend)).toBeLessThan(0.05);
      expect(luminance(CATEGORY_COLORS[category].light.blend)).toBeGreaterThan(0.75);
    }
  });

  test('none of it is Formiq emerald: that is kept for actions and selection', () => {
    for (const scheme of SCHEMES) {
      const brand = themes[scheme].colors;
      const emerald = [brand.primary, brand.primaryPressed, brand.primarySubtle, brand.accent, brand.success];
      for (const category of WORKOUT_CATEGORIES) {
        for (const token of ['label', 'border', 'blend', 'chip'] as const) {
          expect(emerald).not.toContain(CATEGORY_COLORS[category][scheme][token]);
        }
      }
    }
  });

  test('the colors match the design: core teal, upper blue, lower orange, full violet, cardio red, mobility cyan, recovery gold, beginner plum', () => {
    // the hue of each category's dark heading, in degrees, within the family the design names
    const hue = (hex: string) => {
      const [r, g, b] = [1, 3, 5].map((at) => parseInt(hex.slice(at, at + 2), 16) / 255);
      const max = Math.max(r, g, b);
      const delta = max - Math.min(r, g, b);
      const h = max === r ? ((g - b) / delta) % 6 : max === g ? (b - r) / delta + 2 : (r - g) / delta + 4;
      return (h * 60 + 360) % 360;
    };
    const family: Record<WorkoutCategory, [number, number]> = {
      core: [160, 185], // teal
      'upper-body': [205, 235], // blue
      'lower-body': [20, 40], // orange
      'full-body': [245, 275], // violet
      cardio: [345, 10], // red (the range wraps past 0 degrees)
      mobility: [185, 200], // cyan
      recovery: [40, 50], // gold
      beginner: [295, 325], // plum
    };
    for (const category of WORKOUT_CATEGORIES) {
      const [from, to] = family[category];
      for (const scheme of SCHEMES) {
        const h = hue(CATEGORY_COLORS[category][scheme].label);
        const inside = from <= to ? h >= from - 3 && h <= to + 3 : h >= from - 3 || h <= to + 3;
        expect({ category, scheme, hue: Math.round(h), inside }).toMatchObject({ inside: true });
      }
    }
  });
});

describe('workoutCardColors', () => {
  test.each(all)("%s, %s theme: the category's own colors", (category, scheme, colors) => {
    expect(workoutCardColors(category, scheme, themes[scheme].colors)).toBe(colors);
  });

  test.each(SCHEMES)('no category: the plain surface and outline of the %s theme, and a muted heading color', (scheme) => {
    const theme = themes[scheme].colors;

    const colors: CategoryColors = workoutCardColors(null, scheme, theme);

    expect(colors).toEqual({ label: theme.textSecondary, border: theme.border, blend: theme.surface, chip: theme.surfaceMuted });
  });
});
