// One turn of the conversation on the AI Coach screen. The coach API's history calls the assistant's turns
// "coach" (CoachHistoryTurn.role): the connected screen will map between the two.
export type ChatRole = 'assistant' | 'user';

export type ChatMessage = {
  // unique within the conversation on the screen
  id: string;
  role: ChatRole;
  text: string;
};

// A one-tap reply offered under the coach's last question. Tapping it sends `label` as the user's message.
export type SuggestedReply = {
  id: string;
  label: string;
  // The request is for a workout, so while the coach works on it the screen shows the workout card loading
  // (instead of the plain typing dots), and if the request fails, the card says it could not be made.
  expectsWorkout?: boolean;
};
