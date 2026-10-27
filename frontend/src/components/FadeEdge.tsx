import { View, type DimensionValue } from 'react-native';

type FadeEdgeProps = {
  // the color that is solid at the left edge; use the color of what the picture fades into (a hex color)
  color: string;
  // how far in from the left the fade reaches, where it is gone
  width?: DimensionValue;
  // the first part of that width, from 0 to 1, that stays fully solid before the fade begins: it
  // hides detail at the edge of a picture that a thin fade would leave showing
  hold?: number;
  testID?: string;
};

// Colour stops after the solid part: enough that the straight lines between them follow the easing curve
// to well under one brightness step.
const SAMPLES = 16;

export type FadeStop = {
  // from the left edge, 0 to 1 of the fade's width
  position: number;
  // 1 is solid, 0 is clear
  opacity: number;
};

// Where the fade is how solid: solid through `hold`, then easing to clear (smoothstep: no visible line
// where the fade starts or ends).
export function fadeStops(hold: number, samples: number = SAMPLES): FadeStop[] {
  const solidUntil = Math.min(Math.max(hold, 0), 0.99);
  const stops: FadeStop[] = solidUntil > 0 ? [{ position: 0, opacity: 1 }] : [];
  for (let sample = 0; sample <= samples; sample += 1) {
    const along = sample / samples;
    stops.push({
      position: solidUntil + along * (1 - solidUntil),
      opacity: 1 - along * along * (3 - 2 * along),
    });
  }
  return stops;
}

function hexToRgb(color: string): [number, number, number] | null {
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(color.trim())?.[1];
  if (!hex) return null;
  const full = hex.length === 3 ? [...hex].map((digit) => digit + digit).join('') : hex;
  return [0, 2, 4].map((at) => parseInt(full.slice(at, at + 2), 16)) as [number, number, number];
}

export type FadeDirection = 'to right' | 'to left' | 'to bottom' | 'to top';

// The CSS gradient React Native draws for `color` and `hold`: the same color at every stop, only its
// opacity changes, so nothing greys in between. It is solid at the start of `direction` (the left edge, for
// "to right") and clears toward the other end; `strength` (0 to 1) scales how solid it is at most, for a veil
// that should never hide the picture entirely.
export function fadeGradient(
  color: string,
  hold: number,
  direction: FadeDirection = 'to right',
  strength: number = 1,
): string {
  const rgb = hexToRgb(color);
  if (!rgb) return `linear-gradient(${direction}, ${color}, transparent)`;
  const stops = fadeStops(hold).map(
    ({ position, opacity }) =>
      `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${Number((opacity * strength).toFixed(4))}) ${Number((position * 100).toFixed(2))}%`,
  );
  return `linear-gradient(${direction}, ${stops.join(', ')})`;
}

// A scrim that is solid at the left edge and clear at the other, for text that sits on one side of a
// photo. It is one native gradient (React Native's own `backgroundImage`), so there are no steps and no
// seams to see over a bright picture; place it over the picture and under the text, inside a clipped
// container.
export function FadeEdge({ color, width = '75%', hold = 0, testID }: FadeEdgeProps) {
  return (
    <View
      testID={testID}
      pointerEvents="none"
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      style={{ position: 'absolute', top: 0, bottom: 0, left: 0, width, backgroundImage: fadeGradient(color, hold) }}
    />
  );
}
