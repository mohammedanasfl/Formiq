import { themes, type ThemeScheme } from '../src/theme';
import { PLAN_SECTIONS, type PlanSection } from '../src/workouts/planDetails';
import { SECTION_COLORS } from '../src/workouts/sectionColors';

const SCHEMES: ThemeScheme[] = ['dark', 'light'];
const SECTIONS = PLAN_SECTIONS.map((section) => section.id);
const HEX = /^#[0-9A-F]{6}$/;
const KEYS = ['accent', 'badge', 'border', 'divider', 'header', 'rows', 'tagBackground', 'tagText'];

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
const hue = (hex: string) => {
  const [r, g, b] = [1, 3, 5].map((at) => parseInt(hex.slice(at, at + 2), 16) / 255);
  const max = Math.max(r, g, b);
  const delta = max - Math.min(r, g, b);
  const h = max === r ? ((g - b) / delta) % 6 : max === g ? (b - r) / delta + 2 : (r - g) / delta + 4;
  return (h * 60 + 360) % 360;
};
const all = SECTIONS.flatMap((section) => SCHEMES.map((scheme) => [section, scheme, SECTION_COLORS[section][scheme]] as const));

describe('the section colors', () => {
  test('cover the three sections, in both themes, with the same tokens', () => {
    expect(Object.keys(SECTION_COLORS).sort()).toEqual([...SECTIONS].sort());
    for (const section of SECTIONS) {
      expect(Object.keys(SECTION_COLORS[section]).sort()).toEqual(['dark', 'light']);
      for (const scheme of SCHEMES) expect(Object.keys(SECTION_COLORS[section][scheme]).sort()).toEqual(KEYS);
    }
  });

  test.each(all)('%s, %s theme: every token is a plain #RRGGBB color (no alpha, nothing left to the platform)', (_s, _t, colors) => {
    for (const key of KEYS) expect(colors[key as keyof typeof colors]).toMatch(HEX);
  });

  describe.each(SCHEMES)('%s theme contrast (WCAG AA)', (scheme) => {
    const theme = themes[scheme].colors;

    test.each(SECTIONS.map((section) => [section]))('%s: the white icon reads on its disc', (section) => {
      // large graphic: 3:1
      expect(contrast('#FFFFFF', SECTION_COLORS[section][scheme].accent)).toBeGreaterThanOrEqual(3);
    });

    test.each(SECTIONS.map((section) => [section]))('%s: the tag text reads on its tag', (section) => {
      const { tagText, tagBackground } = SECTION_COLORS[section][scheme];

      expect(contrast(tagText, tagBackground)).toBeGreaterThanOrEqual(4.5);
    });

    test.each(SECTIONS.map((section) => [section]))('%s: the theme\'s title and secondary text read on the header and the rows', (section) => {
      const { header, rows } = SECTION_COLORS[section][scheme];

      for (const surface of [header, rows]) {
        expect(contrast(theme.textPrimary, surface)).toBeGreaterThanOrEqual(4.5);
        expect(contrast(theme.textSecondary, surface)).toBeGreaterThanOrEqual(4.5);
      }
    });

    test.each(SECTIONS.map((section) => [section]))('%s: the number reads on its badge, and the plain tag text on a plain tag', (section) => {
      expect(contrast(theme.textPrimary, SECTION_COLORS[section][scheme].badge)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(theme.textSecondary, theme.surfaceMuted)).toBeGreaterThanOrEqual(4.5);
    });

    test('the plain tag stands apart from the rows it sits on', () => {
      for (const section of SECTIONS) {
        expect(SECTION_COLORS[section][scheme].rows).not.toBe(theme.surfaceMuted);
      }
    });
  });

  test('each section has its own color: no two share a token in a theme', () => {
    for (const scheme of SCHEMES) {
      for (const key of KEYS) {
        // the light badge is white for all three: a white disc with the section's outline (the accent)
        if (scheme === 'light' && key === 'badge') continue;
        const values = SECTIONS.map((section) => SECTION_COLORS[section][scheme][key as keyof (typeof SECTION_COLORS)[PlanSection]['dark']]);
        expect(new Set(values).size).toBe(SECTIONS.length);
      }
    }
  });

  test('the dark cards are dark and the light ones light, with the header a step stronger than the rows', () => {
    for (const section of SECTIONS) {
      const dark = SECTION_COLORS[section].dark;
      const light = SECTION_COLORS[section].light;

      expect(luminance(dark.header)).toBeLessThan(0.05);
      expect(luminance(dark.rows)).toBeLessThan(0.05);
      expect(luminance(light.header)).toBeGreaterThan(0.75);
      expect(luminance(light.rows)).toBeGreaterThan(0.9);
      // the header band is the stronger tint of the accent: lighter than the rows in dark, darker in light
      expect(luminance(dark.header)).toBeGreaterThan(luminance(dark.rows));
      expect(luminance(light.header)).toBeLessThan(luminance(light.rows));
    }
  });

  test('the colors are purple for the warm-up, green for the main workout and blue for the cool-down', () => {
    const family: Record<PlanSection, [number, number]> = {
      WARM_UP: [255, 285], // purple
      MAIN_WORKOUT: [140, 165], // green
      COOL_DOWN: [205, 225], // blue
    };
    for (const section of SECTIONS) {
      const [from, to] = family[section];
      for (const scheme of SCHEMES) {
        for (const key of ['accent', 'border', 'header'] as const) {
          const h = hue(SECTION_COLORS[section][scheme][key]);
          expect({ section, scheme, key, hue: Math.round(h), inside: h >= from - 8 && h <= to + 8 }).toMatchObject({ inside: true });
        }
      }
    }
  });
});
