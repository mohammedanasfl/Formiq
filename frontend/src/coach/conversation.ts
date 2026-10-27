// The plain rules of the conversation on the AI Coach screen, apart from how it is drawn.

// The longest message the composer takes: the coach API's own limit for one message
// (backend/app/schemas/coach.py, CoachMessageText), so a message the screen lets through is never too long
// for the coach.
export const MAX_MESSAGE_LENGTH = 4000;

// A message as it is sent: without the spaces and line breaks around it.
export const cleanDraft = (draft: string): string => draft.trim();

// Whether sending is possible: there is something to say, and nothing is going on that a new message would cross
// (the coach still answering the last one, or a workout being applied). A blank message is never sent.
export const canSend = (draft: string, busy: boolean): boolean => !busy && cleanDraft(draft).length > 0;
