import type { ProfileDraft } from './draft';
import {
  cmToFeetInches,
  feetInchesToCm,
  kgToPounds,
  parseDecimal,
  parseWholeNumber,
  poundsToKg,
} from './units';

// Sanity ranges for typos ("1750" for a height). They are the app's, not the backend's rules: the
// backend only asks for positive numbers, and has the last word.
export const LIMITS = {
  age: { min: 13, max: 100 },
  heightCm: { min: 100, max: 250 },
  weightKg: { min: 30, max: 300 },
  sleepHours: { min: 3, max: 14 },
} as const;

// The same limits in the other units, rounded inwards so every value shown as allowed is allowed.
const HEIGHT_INCHES = {
  min: Math.ceil(LIMITS.heightCm.min / 2.54),
  max: Math.floor(LIMITS.heightCm.max / 2.54),
};
const WEIGHT_POUNDS = {
  min: Math.ceil(kgToPounds(LIMITS.weightKg.min)),
  max: Math.floor(kgToPounds(LIMITS.weightKg.max)),
};
// The message for inches that are out of range: the screen shows it under the inches field.
export const INCHES_ERROR = 'Inches go from 0 to 11.';
const MAX_NAME_LENGTH = 100;
const MAX_EMAIL_LENGTH = 255;
const MIN_PASSWORD_LENGTH = 8;
const MAX_PASSWORD_LENGTH = 1024;

export type Errors<Key extends string> = Partial<Record<Key, string>>;

export function hasErrors(errors: object): boolean {
  return Object.keys(errors).length > 0;
}

// Sign-up follows the backend's rules (backend/app/schemas/auth.py); signing in only needs both
// fields, and the backend decides whether they match an account.
export function validateAccount(
  email: string,
  password: string,
  mode: 'signIn' | 'signUp',
): Errors<'email' | 'password'> {
  const errors: Errors<'email' | 'password'> = {};
  const address = email.trim();
  if (address === '') {
    errors.email = 'Enter your email address.';
  } else if (
    mode === 'signUp' &&
    (address.length < 3 || address.length > MAX_EMAIL_LENGTH || !/^[^@\s]+@[^@\s]+$/.test(address))
  ) {
    errors.email = 'Enter a valid email address.';
  }

  if (password === '') {
    errors.password = 'Enter your password.';
  } else if (mode === 'signUp' && password.length < MIN_PASSWORD_LENGTH) {
    errors.password = `Use at least ${MIN_PASSWORD_LENGTH} characters.`;
  } else if (mode === 'signUp' && password.length > MAX_PASSWORD_LENGTH) {
    errors.password = `Use at most ${MAX_PASSWORD_LENGTH} characters.`;
  }
  return errors;
}

export function validateGoal(draft: ProfileDraft): Errors<'goal'> {
  return draft.goal === null ? { goal: 'Choose a goal to continue.' } : {};
}

// The height in centimetres, or null when what is typed is not a usable number.
export function heightInCm(draft: ProfileDraft): number | null {
  if (draft.heightUnit === 'cm') return parseDecimal(draft.heightCm);
  const feet = parseWholeNumber(draft.heightFeet);
  const inches = draft.heightInches.trim() === '' ? 0 : parseWholeNumber(draft.heightInches);
  if (feet === null || inches === null || inches > 11) return null;
  return feetInchesToCm(feet, inches);
}

export function weightInKg(draft: ProfileDraft): number | null {
  const weight = parseDecimal(draft.weight);
  if (weight === null) return null;
  return draft.weightUnit === 'kg' ? weight : poundsToKg(weight);
}

function heightError(draft: ProfileDraft): string | undefined {
  if (draft.heightUnit === 'cm') {
    const cm = heightInCm(draft);
    return cm !== null && cm >= LIMITS.heightCm.min && cm <= LIMITS.heightCm.max
      ? undefined
      : `Enter a height from ${LIMITS.heightCm.min} to ${LIMITS.heightCm.max} cm.`;
  }
  const feet = parseWholeNumber(draft.heightFeet);
  const inches = draft.heightInches.trim() === '' ? 0 : parseWholeNumber(draft.heightInches);
  if (feet !== null && inches !== null && inches > 11) return INCHES_ERROR;
  const total = feet === null || inches === null ? null : feet * 12 + inches;
  if (total !== null && total >= HEIGHT_INCHES.min && total <= HEIGHT_INCHES.max) return undefined;
  const low = cmToFeetInches(HEIGHT_INCHES.min * 2.54);
  const high = cmToFeetInches(HEIGHT_INCHES.max * 2.54);
  return `Enter a height from ${low.feet} ft ${low.inches} in to ${high.feet} ft ${high.inches} in.`;
}

function weightError(draft: ProfileDraft): string | undefined {
  const weight = parseDecimal(draft.weight);
  const range = draft.weightUnit === 'kg' ? LIMITS.weightKg : WEIGHT_POUNDS;
  return weight !== null && weight >= range.min && weight <= range.max
    ? undefined
    : `Enter a weight from ${range.min} to ${range.max} ${draft.weightUnit}.`;
}

export function validateDetails(
  draft: ProfileDraft,
): Errors<'firstName' | 'lastName' | 'age' | 'gender' | 'height' | 'weight'> {
  const errors: Errors<'firstName' | 'lastName' | 'age' | 'gender' | 'height' | 'weight'> = {};
  if (draft.firstName.trim() === '') errors.firstName = 'Enter your first name.';
  else if (draft.firstName.trim().length > MAX_NAME_LENGTH) {
    errors.firstName = `Use at most ${MAX_NAME_LENGTH} characters.`;
  }
  if (draft.lastName.trim().length > MAX_NAME_LENGTH) {
    errors.lastName = `Use at most ${MAX_NAME_LENGTH} characters.`;
  }

  const age = parseWholeNumber(draft.age);
  if (age === null || age < LIMITS.age.min || age > LIMITS.age.max) {
    errors.age = `Enter your age as a whole number from ${LIMITS.age.min} to ${LIMITS.age.max}.`;
  }
  if (draft.gender === null) errors.gender = 'Choose an option.';

  const height = heightError(draft);
  if (height) errors.height = height;
  const weight = weightError(draft);
  if (weight) errors.weight = weight;
  return errors;
}

export function validateTraining(
  draft: ProfileDraft,
): Errors<'experience' | 'trainingDays' | 'activityLevel' | 'sleepHours'> {
  const errors: Errors<'experience' | 'trainingDays' | 'activityLevel' | 'sleepHours'> = {};
  if (draft.experience === null) errors.experience = 'Choose your experience level.';
  if (draft.trainingDays === null) errors.trainingDays = 'Choose how many days a week.';
  if (draft.activityLevel === null) errors.activityLevel = 'Choose an activity level.';

  const sleep = parseDecimal(draft.sleepHours);
  if (sleep === null || sleep < LIMITS.sleepHours.min || sleep > LIMITS.sleepHours.max) {
    errors.sleepHours = `Enter the hours you usually sleep, from ${LIMITS.sleepHours.min} to ${LIMITS.sleepHours.max}.`;
  }
  return errors;
}

export function validateLocation(draft: ProfileDraft): Errors<'location'> {
  return draft.location === null ? { location: 'Choose where you will work out.' } : {};
}

// True when every question the backend requires has a usable answer.
export function isProfileComplete(draft: ProfileDraft): boolean {
  return ![
    validateGoal(draft),
    validateDetails(draft),
    validateTraining(draft),
    validateLocation(draft),
  ].some(hasErrors);
}
