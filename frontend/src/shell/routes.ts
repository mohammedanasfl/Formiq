import type { SavedEquipment } from '../api';
import type { PlannedExercise, WorkoutDetailsData } from '../workouts/planDetails';
import type { SectionId } from './tabs';

// The screens that open over the tabs, one on top of another (the tab bar is not shown under them). They
// carry the data they show, so a screen never has to look its workout up again.
export type Route =
  | { screen: 'workout'; workout: WorkoutDetailsData }
  | { screen: 'exercise'; workout: WorkoutDetailsData; exercise: PlannedExercise }
  // Workouts, Nutrition & recovery, Exercises and Mobility: placeholders for now, reached from Home and Discover
  | { screen: 'section'; section: SectionId }
  // The Profile tab's equipment editor, opened from the equipment saved with the profile: the choice starts from it
  | { screen: 'equipment-edit'; saved: SavedEquipment }
  // MOCK: every state of the AI Coach's workout card, reached from the coach's menu (src/mock/CoachCardPreviewScreen.tsx)
  | { screen: 'coach-preview' };

// What the AI Coach tab is opened with when it is opened from a workout ("Edit with AI"). The coach screen shows
// this as a note at the top of the conversation (which workout it was opened from), and the connected screen sends
// the workout's id (when it is a saved plan's, a number) as `workout_plan_id` with every message of the
// conversation, so the backend lets the coach revise that workout and no other. It never carries a change to the
// workout, and opening the coach changes nothing: only approving a proposal saves a plan.
export type CoachContext = {
  workoutId: number | string;
  title: string;
};
