import type { SuggestedReply } from './types';

// What the screen offers to say once the coach has shown a workout for the user to review: ways to change it, in
// the user's own words. Pressing one sends it as the user's message, with the conversation, like any message;
// the coach reads the workout waiting for approval itself (the request carries no proposal) and may answer with
// another one. Each is a request about a workout, so the card shows loading while the coach works on it.
export const REFINEMENT_SUGGESTIONS: readonly SuggestedReply[] = [
  { id: 'refine-same-duration', label: 'Keep same duration', expectsWorkout: true },
  { id: 'refine-length', label: 'Try different length', expectsWorkout: true },
  { id: 'refine-intense', label: 'Make it more intense', expectsWorkout: true },
  { id: 'refine-no-equipment', label: 'Use no equipment', expectsWorkout: true },
];
