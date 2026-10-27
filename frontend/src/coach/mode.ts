// Which coach the AI Coach tab talks to.
//   api   the Formiq backend (POST /coach/message and the approval route): what the app does.
//   mock  a made-up coach that answers from fixed examples and calls nothing (src/mock/): for looking at the screen
//         and its card without a backend, a language model or a network. Start the app with
//         EXPO_PUBLIC_COACH_MODE=mock to get it. Tests choose one explicitly.
export type CoachMode = 'api' | 'mock';

export const DEFAULT_COACH_MODE: CoachMode = process.env.EXPO_PUBLIC_COACH_MODE === 'mock' ? 'mock' : 'api';
