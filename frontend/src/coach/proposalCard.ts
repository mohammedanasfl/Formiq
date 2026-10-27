import type { PlanSectionName, ProposedExercise, SessionFocus, WorkoutProposal } from '../api';
import type { WorkoutCategory } from '../workouts/categories';
import { exerciseCountLabel, formatPrescription, PLAN_SECTIONS, positiveInteger } from '../workouts/planDetails';
import { dayLabel } from './days';
import { compareWithOriginal, keyChangeText, markKey, type KeyChange } from './proposalChanges';

// What the workout card shows for a proposal, worked out from the proposal alone. For a revision, what it changes in
// the saved plan it replaces is the backend's own comparison (`proposal.changes`, and the replaced plan's length in
// `revision.replaces_plan_estimated_minutes`): the card words it and works nothing out. A field the backend's
// proposal does not carry (a description, a difficulty) is not shown, and none is made up. See src/api/types.ts.

// What each focus is called on the card, and the picture's category it calls for. The focus is the proposal's own
// (coverage.focus), so the picture and the label are as true as the data.
const FOCUS: Record<SessionFocus, { label: string; categories: WorkoutCategory[] }> = {
  CORE: { label: 'Core', categories: ['core'] },
  UPPER_BODY: { label: 'Upper body', categories: ['upper-body'] },
  PUSH: { label: 'Push', categories: ['upper-body'] },
  PULL: { label: 'Pull', categories: ['upper-body'] },
  LOWER_BODY: { label: 'Lower body', categories: ['lower-body'] },
  FULL_BODY: { label: 'Full body', categories: ['full-body'] },
};

// "new": the proposal adds a workout. "updated": it would replace one of the user's saved workouts.
export type ProposalKind = 'new' | 'updated';

export type CardExercise = {
  key: string;
  name: string;
  // "3 sets • 30 seconds • 45 s rest", with "• 20 kg" after the target when it has a weight
  prescription: string;
  // "Bodyweight" or the catalog's equipment names
  equipment: string;
  // against the plan it replaces: new there, or prescribed differently; null when the same or not compared
  mark: 'new' | 'changed' | null;
};

export type CardSection = {
  id: PlanSectionName;
  title: string;
  // Formiq's estimate for the section; null when it is not a positive whole number
  minutes: number | null;
  exercises: CardExercise[];
};

// How the card stands against the plan it replaces:
//   none         a new workout: nothing to compare with
//   compared     the backend compared it with the plan and the lists below are its differences
//   unavailable  it replaces a plan but the backend could not compare (the plan is not as it was when proposed): only
//                what the proposal itself says is shown
export type ComparisonState = 'none' | 'compared' | 'unavailable';

export type ProposalCardData = {
  proposalId: string;
  kind: ProposalKind;
  title: string;
  // "Core focus • Today": the proposal's focus and day, which is all the proposal says about the workout
  subtitle: string | null;
  // what the picture shows and the chip over it says: from the proposal's focus
  focusLabel: string;
  categories: WorkoutCategory[];
  minutes: number | null;
  exerciseCount: number;
  exerciseCountLabel: string;
  sections: CardSection[];
  comparison: ComparisonState;
  keyChanges: KeyChange[];
  keyChangeLines: string[];
  // the saved plan it would replace
  replaces: { planId: number; name: string; keptExercises: string[] } | null;
  // The title of the workout the conversation was opened from, when the proposal replaces a different one: what it
  // changes is not what the person opened the coach to edit, and the card says so.
  offTarget: string | null;
  // why the workout falls short of its focus, when it does (Formiq's catalog had nothing better)
  coverageNotes: string[];
};

const equipmentText = (exercise: Pick<ProposedExercise, 'equipment'>) => {
  const names = exercise.equipment.map((name) => name.trim()).filter(Boolean);
  return names.length === 0 ? 'Bodyweight' : names.join(', ');
};

// "3 sets • 10 reps • 20 kg • 45 s rest": the weight, when the proposal gives one, after the target (kilograms; null is no
// weight, and the line is as it was).
const prescriptionLine = (exercise: ProposedExercise) => {
  const base = formatPrescription({ sets: exercise.sets, reps: exercise.reps, durationSeconds: exercise.duration_seconds });
  const weight = exercise.weight_kg === null ? null : `${exercise.weight_kg} kg`;
  const rest = exercise.rest_seconds ? `${exercise.rest_seconds} s rest` : null;
  return [base, weight, rest].filter(Boolean).join(' • ');
};

// `now` gives "Today" and "Tomorrow" their meaning. `openedFrom` is the workout the conversation is about (the one
// "Edit with AI" opened it from, or the saved plan an applied revision made of it), if it is about one.
export function proposalCardData(
  proposal: WorkoutProposal,
  now: Date,
  openedFrom: { planId: number; title: string } | null = null,
): ProposalCardData {
  const revision = proposal.revision;
  const focus = FOCUS[proposal.coverage.focus] ?? { label: 'Workout', categories: [] };
  // the backend's comparison with the plan the proposal replaces; none for a new workout, or when it could not compare
  const comparison = proposal.changes ? compareWithOriginal(proposal) : null;
  const sectionMinutes: Record<PlanSectionName, number> = {
    WARM_UP: proposal.warm_up_minutes,
    MAIN_WORKOUT: proposal.main_minutes,
    COOL_DOWN: proposal.cool_down_minutes,
  };
  const day = dayLabel(proposal.scheduled_date, now);
  const keyChanges = comparison?.changes ?? [];

  return {
    proposalId: proposal.proposal_id,
    kind: revision ? 'updated' : 'new',
    title: proposal.name,
    subtitle: [`${focus.label} focus`, day].filter(Boolean).join(' • '),
    focusLabel: focus.label,
    categories: focus.categories,
    minutes: positiveInteger(proposal.estimated_minutes) ? proposal.estimated_minutes : null,
    exerciseCount: proposal.exercises.length,
    exerciseCountLabel: exerciseCountLabel(proposal.exercises.length),
    sections: PLAN_SECTIONS.map(({ id, title }) => ({
      id,
      title,
      minutes: positiveInteger(sectionMinutes[id]) ? sectionMinutes[id] : null,
      exercises: [...proposal.exercises]
        .filter((exercise) => exercise.section === id)
        .sort((a, b) => a.exercise_order - b.exercise_order)
        .map((exercise) => ({
          key: `${exercise.exercise_order}-${exercise.exercise_id}`,
          name: exercise.exercise_name,
          prescription: prescriptionLine(exercise),
          equipment: equipmentText(exercise),
          mark: comparison?.marks.get(markKey(exercise.section, exercise.exercise_name)) ?? null,
        })),
    })).filter((section) => section.exercises.length > 0),
    comparison: revision === null ? 'none' : comparison ? 'compared' : 'unavailable',
    keyChanges,
    keyChangeLines: keyChanges.map(keyChangeText),
    replaces: revision
      ? { planId: revision.replaces_plan_id, name: revision.replaces_plan_name, keptExercises: revision.kept_exercises }
      : null,
    offTarget: revision && openedFrom && revision.replaces_plan_id !== openedFrom.planId ? openedFrom.title : null,
    coverageNotes: proposal.coverage.complete ? [] : proposal.coverage.limitations.map((limitation) => limitation.message),
  };
}
