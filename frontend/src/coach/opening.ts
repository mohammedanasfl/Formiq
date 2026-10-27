import type { CoachContext } from '../shell/routes';
import type { ChatOpening } from './chatState';
import type { SuggestedReply } from './types';

// What the connected AI Coach screen opens with. Two lines of its own, not the coach's answers to anything: a
// greeting, and (when the screen was opened from a workout) a question that names it.
//
// Which workout a request is about travels in its own field (`workout_plan_id`, sent with every message of a
// conversation opened from a workout: src/coach/useCoachChat.ts), which the backend checks and holds the coach to. So
// neither line is sent as something said in the conversation (`inHistory: false`): the question is only the screen's
// way of showing which workout the conversation is about.

const NEW_WORKOUT: readonly SuggestedReply[] = [
  { id: 'new-upper-body', label: 'Create a 25-minute upper-body workout', expectsWorkout: true },
  { id: 'different-today', label: 'Suggest a different workout for today', expectsWorkout: true },
];

const EDIT_WORKOUT: readonly SuggestedReply[] = [
  { id: 'edit-shorter', label: 'Make it shorter', expectsWorkout: true },
  { id: 'edit-easier', label: 'Make it easier', expectsWorkout: true },
  { id: 'edit-different', label: 'Suggest a different workout', expectsWorkout: true },
];

export function coachOpening(launch: CoachContext | null): ChatOpening {
  // only a saved plan has an id the coach can be pointed at: anything else is opened as no workout in particular
  if (launch && typeof launch.workoutId === 'number') {
    return {
      items: [
        {
          kind: 'message',
          id: 'm1',
          role: 'assistant',
          text: `What would you like to change in “${launch.title}”?`,
          inHistory: false,
        },
      ],
      suggestions: EDIT_WORKOUT,
    };
  }
  return {
    items: [
      {
        kind: 'message',
        id: 'm1',
        role: 'assistant',
        text: "Hi, I'm Formiq Coach. I can build you a workout or change one you have. What would you like to do?",
        inHistory: false,
      },
    ],
    suggestions: NEW_WORKOUT,
  };
}
