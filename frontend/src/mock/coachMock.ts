// MOCK DATA: nothing in this file comes from the Formiq backend or from a language model.
//
// Mock mode (EXPO_PUBLIC_COACH_MODE=mock, src/coach/mode.ts) and the tests of the screen use this made-up
// conversation, so the screen's look and feel can be seen without a backend. It is not a real exchange with the
// coach, and nothing may present it as one: in mock mode no coach endpoint (POST /coach/message) is called, and
// every line below is fixed. The connected app opens with src/coach/opening.ts and gets its messages from the coach
// API. The workouts mock mode proposes are in coachProposalsMock.ts, and what decides which line answers which
// message is mockCoachGateway.ts.
//
// What the lines never do: claim to have read the user's data, to have built, changed, approved or saved a
// workout, or to give advice. The coach only proposes, and only the user's approval saves a plan, so a line
// that said otherwise would show the screen doing what the product never does. The replies to typed messages
// the preview has no answer for say plainly that the coach is a preview.

import type { ChatItem } from '../coach/chatState';
import type { CoachOpening } from '../coach/useCoachChat';
import type { SuggestedReply } from '../coach/types';

// The conversation the screen opens with.
export const MOCK_INTRO: readonly ChatItem[] = [
  {
    kind: 'message',
    id: 'm1',
    role: 'assistant',
    text: "Hi, I'm Formiq Coach. I can suggest changes to your workouts and answer training questions. What would you like to work on?",
  },
  { kind: 'message', id: 'm2', role: 'user', text: 'Can I get a different ab workout?' },
  { kind: 'message', id: 'm3', role: 'assistant', text: 'Sure. Do you want to keep the same duration, or try a different length?' },
];

// The replies offered under the coach's question, in the order shown: the two answers to it, and a way to ask for
// a new workout.
export const MOCK_SUGGESTIONS: readonly SuggestedReply[] = [
  { id: 'keep-duration', label: 'Keep same duration', expectsWorkout: true },
  { id: 'different-length', label: 'Try different length' },
  { id: 'new-upper-body', label: 'Create a 25-minute upper-body workout', expectsWorkout: true },
];

export const MOCK_OPENING: CoachOpening = { items: MOCK_INTRO, suggestions: MOCK_SUGGESTIONS };

// the answer to "Try different length": a question, as the opening's was
export const MOCK_LENGTH_QUESTION = 'No problem. How long would you like it to be: 10, 20 or 30 minutes?';

// What the coach says to a message the preview has no workout for: these lines in turn, then round again, so the
// same conversation always gets the same answers.
export const MOCK_TYPED_REPLIES: readonly string[] = [
  "Thanks, I've read that. This is a preview of the coach, so it can't change your workout yet. Nothing was changed or saved.",
  "Got it. The coach isn't connected yet, so this is an example reply. Your workout stays as it is.",
  'Understood. When the coach is connected it will suggest changes for you to approve. For now, nothing changes.',
];

// What the coach says when the preview has run out of workouts to show for a change.
export const MOCK_NO_MORE_REVISIONS =
  "That's as far as this preview goes: it has one revision of each workout. Use Start over in the menu to run it again.";
export const MOCK_ALREADY_REPLACED =
  "Core & Abs Focus was already replaced in this preview, so there's nothing left to change. Use Start over in the menu to run it again.";
