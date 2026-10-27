// The backend stores centimetres and kilograms. The app lets people type feet and inches or pounds
// and converts them here, once, with the exact factors.
const CM_PER_INCH = 2.54;
const KG_PER_POUND = 0.45359237;

export function round1(value: number): number {
  return Math.round(value * 10) / 10;
}

export function feetInchesToCm(feet: number, inches: number): number {
  return round1((feet * 12 + inches) * CM_PER_INCH);
}

// Whole inches, as people say a height.
export function cmToFeetInches(cm: number): { feet: number; inches: number } {
  const totalInches = Math.round(cm / CM_PER_INCH);
  return { feet: Math.floor(totalInches / 12), inches: totalInches % 12 };
}

export function poundsToKg(pounds: number): number {
  return round1(pounds * KG_PER_POUND);
}

export function kgToPounds(kg: number): number {
  return round1(kg / KG_PER_POUND);
}

// A number typed as people type it: digits with an optional decimal point or comma. Anything else
// (empty, letters, "1e3", "-5", "1.2.3") is not a number.
export function parseDecimal(text: string): number | null {
  const normalised = text.trim().replace(',', '.');
  return /^\d+(\.\d+)?$/.test(normalised) ? Number(normalised) : null;
}

export function parseWholeNumber(text: string): number | null {
  const trimmed = text.trim();
  return /^\d+$/.test(trimmed) ? Number(trimmed) : null;
}
