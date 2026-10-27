import { AppText } from '../components';

// The line above a step's button when Next was pressed with answers missing. The answers to fix may be
// above the part of the form in view, so this says so next to the button; each field announces its
// own message.
export function CheckAnswers() {
  return (
    <AppText variant="caption" color="error">
      Check the answers marked in red.
    </AppText>
  );
}
