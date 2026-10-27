import { ApiError } from './client';

export type ErrorContext =
  | 'signIn'
  | 'signUp'
  | 'saveProfile'
  | 'checkProfile'
  | 'savedEquipment'
  | 'saveEquipment'
  | 'equipment'
  | 'todayWorkout'
  | 'coach';

// Whether the backend refused the request because the person's token is no longer good (a 401). Asking again with the same
// token cannot work, so a screen leaves "Try again" out for it: only signing in again helps. Not for the sign-in itself,
// where a 401 is a wrong email or password and trying again with other ones is exactly right.
export function isSessionExpired(error: unknown): boolean {
  return error instanceof ApiError && error.kind === 'http' && error.status === 401;
}

// The sentence a person reads for a failed request. Never claims anything succeeded.
export function describeError(error: unknown, context: ErrorContext): string {
  if (!(error instanceof ApiError)) return 'Something went wrong. Try again.';

  if (error.kind === 'network') {
    return "Can't reach Formiq. Check your connection and try again.";
  }
  if (error.kind === 'timeout') return 'Formiq took too long to answer. Try again.';
  if (error.kind === 'invalid-response') {
    return 'Formiq sent an answer the app could not read. Try again.';
  }

  if (context === 'saveEquipment' && error.status === 404) {
    return 'Formiq could not find your profile, so nothing was changed.';
  }

  switch (error.status) {
    case 401:
      return context === 'signIn'
        ? 'Incorrect email or password.'
        : 'Your session has expired. Log in again.';
    case 409:
      return context === 'signUp'
        ? 'An account with this email already exists. Log in instead.'
        : 'This already exists.';
    case 400:
      // the backend names ids and says "retired": nothing a person can act on, and the editor lists only what it offers
      if (context === 'saveEquipment') return "Formiq couldn't accept some of that equipment. Go back, open the list again and choose again.";
      return error.detail ? sentence(error.detail) : 'Formiq could not accept that. Check it and try again.';
    case 422:
      if (context === 'saveEquipment') return "Formiq couldn't accept that equipment. Go back and choose again.";
      return context === 'signUp'
        ? 'Enter a valid email address and a password of at least 8 characters.'
        : "Formiq couldn't accept some of your details. Go back and check them.";
    case 503:
      return "Formiq isn't available right now. Try again in a moment.";
    default:
      return error.status !== null && error.status >= 500
        ? "Something went wrong on Formiq's side. Try again."
        : 'Something went wrong. Try again.';
  }
}

function sentence(text: string): string {
  const trimmed = text.trim();
  const capitalised = trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
  return /[.!?]$/.test(capitalised) ? capitalised : `${capitalised}.`;
}
