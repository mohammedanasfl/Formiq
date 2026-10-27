// The profile steps, in order: the progress shown is the position in this list.
export const PROFILE_STEPS = ['goal', 'details', 'training', 'location', 'equipment', 'review'] as const;
export type ProfileStep = (typeof PROFILE_STEPS)[number];

// Every screen of the flow.
export type StepId = 'welcome' | 'signUp' | 'signIn' | ProfileStep | 'done' | 'home';

export function stepProgress(step: ProfileStep) {
  return { index: PROFILE_STEPS.indexOf(step) + 1, total: PROFILE_STEPS.length };
}
