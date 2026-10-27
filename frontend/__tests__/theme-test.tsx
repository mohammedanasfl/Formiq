import {
  darkColors,
  layout,
  lightColors,
  radii,
  spacing,
  themes,
  typography,
  type ColorToken,
  type ColorTokens,
  type ThemeScheme,
} from '../src/theme';

// WCAG 2.x relative luminance and contrast ratio for #RRGGBB colors.
function channel(value: number) {
  const c = value / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string) {
  const n = parseInt(hex.slice(1), 16);
  return 0.2126 * channel(n >> 16) + 0.7152 * channel((n >> 8) & 255) + 0.0722 * channel(n & 255);
}

function contrast(a: string, b: string) {
  const [lighter, darker] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (lighter + 0.05) / (darker + 0.05);
}

describe('color tokens', () => {
  test('dark and light define exactly the same tokens', () => {
    expect(Object.keys(lightColors).sort()).toEqual(Object.keys(darkColors).sort());
  });

  test('every color is a 6-digit hex value', () => {
    for (const colors of [darkColors, lightColors]) {
      for (const value of Object.values(colors)) {
        expect(value).toMatch(/^#[0-9A-F]{6}$/i);
      }
    }
  });

  test('each scheme maps to its own colors', () => {
    expect(themes.dark).toEqual({ scheme: 'dark', colors: darkColors });
    expect(themes.light).toEqual({ scheme: 'light', colors: lightColors });
  });

  test('both themes keep the brand green and the dark theme keeps the approved surfaces', () => {
    expect(darkColors.primary).toBe('#10B981');
    expect(lightColors.primary).toBe('#10B981');
    expect(darkColors.background).toBe('#0B0D0E');
    expect(darkColors.surface).toBe('#16191B');
  });

  test('an unknown token is a type error', () => {
    // @ts-expect-error 'nope' is not a color token
    const unknown: ColorToken = 'nope';
    const colors: ColorTokens = darkColors;
    expect(colors).not.toHaveProperty(unknown);
  });
});

describe.each<ThemeScheme>(['dark', 'light'])('%s theme contrast (WCAG AA)', (scheme) => {
  const c = themes[scheme].colors;

  test.each(['textPrimary', 'textSecondary', 'textMuted'] as const)(
    '%s reads at 4.5:1 on every surface',
    (text) => {
      for (const surface of ['background', 'surface', 'surfaceMuted'] as const) {
        expect(contrast(c[text], c[surface])).toBeGreaterThanOrEqual(4.5);
      }
    },
  );

  test('the label on a primary button reads at 4.5:1, also while pressed', () => {
    expect(contrast(c.textOnPrimary, c.primary)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(c.textOnPrimary, c.primaryPressed)).toBeGreaterThanOrEqual(4.5);
  });

  test.each(['accent', 'success', 'warning', 'error'] as const)(
    '%s works as text on the page and on cards',
    (status) => {
      expect(contrast(c[status], c.background)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(c[status], c.surface)).toBeGreaterThanOrEqual(4.5);
    },
  );

  test('accent text works on a selected (subtle green) background', () => {
    expect(contrast(c.accent, c.primarySubtle)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(c.textPrimary, c.primarySubtle)).toBeGreaterThanOrEqual(4.5);
  });

  test('the colors that are only graphics (warm and progress) reach 3:1 against the page and cards', () => {
    for (const graphic of ['warm', 'progress'] as const) {
      for (const surface of ['background', 'surface'] as const) {
        expect(contrast(c[graphic], c[surface])).toBeGreaterThanOrEqual(3);
      }
    }
  });

  test('control outlines and the focus color reach 3:1 against the page and cards', () => {
    for (const surface of ['background', 'surface'] as const) {
      expect(contrast(c.borderStrong, c[surface])).toBeGreaterThanOrEqual(3);
      expect(contrast(c.accent, c[surface])).toBeGreaterThanOrEqual(3);
    }
  });
});

describe('spacing, radii, typography and layout', () => {
  test('spacing and radii grow with their names', () => {
    const ascending = (values: number[]) => values.every((v, i) => i === 0 || v > values[i - 1]);
    expect(ascending(Object.values(spacing))).toBe(true);
    expect(ascending([radii.sm, radii.md, radii.lg, radii.pill])).toBe(true);
  });

  test('every typography variant leaves room for its line', () => {
    for (const variant of Object.values(typography)) {
      expect(variant.lineHeight).toBeGreaterThan(variant.fontSize);
    }
  });

  test('touch targets are at least 44 and text can scale', () => {
    expect(layout.touchTarget).toBeGreaterThanOrEqual(44);
    expect(layout.maxFontScale).toBeGreaterThan(1);
  });
});
