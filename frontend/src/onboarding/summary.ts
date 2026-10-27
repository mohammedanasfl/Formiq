import type { ProfileDraft } from './draft';
import {
  ACTIVITY_OPTIONS,
  EXPERIENCE_OPTIONS,
  GENDER_OPTIONS,
  GOAL_OPTIONS,
  LOCATION_OPTIONS,
  titleOf,
} from './options';
import type { ProfileStep } from './steps';
import { round1 } from './units';
import { heightInCm, weightInKg } from './validation';

export type SummaryRow = { label: string; value: string };
export type SummarySection = { step: ProfileStep; title: string; rows: SummaryRow[] };

const UNKNOWN = '—';

// What the review screen shows for the answers that go to the backend, in the form they will be
// saved (centimetres and kilograms), with what was typed beside it when it was in other units.
export function summarise(draft: ProfileDraft): SummarySection[] {
  const heightCm = heightInCm(draft);
  const weightKg = weightInKg(draft);
  const height =
    heightCm === null
      ? UNKNOWN
      : draft.heightUnit === 'cm'
        ? `${round1(heightCm)} cm`
        : `${Number(draft.heightFeet)} ft ${Number(draft.heightInches || 0)} in (${round1(heightCm)} cm)`;
  const weight =
    weightKg === null
      ? UNKNOWN
      : draft.weightUnit === 'kg'
        ? `${round1(weightKg)} kg`
        : `${Number(draft.weight.replace(',', '.'))} lb (${round1(weightKg)} kg)`;
  const days = draft.trainingDays;

  return [
    {
      step: 'goal',
      title: 'Goal',
      rows: [{ label: 'Goal', value: titleOf(GOAL_OPTIONS, draft.goal) || UNKNOWN }],
    },
    {
      step: 'details',
      title: 'Personal details',
      rows: [
        { label: 'Name', value: `${draft.firstName.trim()} ${draft.lastName.trim()}`.trim() || UNKNOWN },
        { label: 'Age', value: draft.age.trim() || UNKNOWN },
        { label: 'Gender', value: titleOf(GENDER_OPTIONS, draft.gender) || UNKNOWN },
        { label: 'Height', value: height },
        { label: 'Weight', value: weight },
      ],
    },
    {
      step: 'training',
      title: 'Training',
      rows: [
        { label: 'Experience', value: titleOf(EXPERIENCE_OPTIONS, draft.experience) || UNKNOWN },
        {
          label: 'Training days',
          value: days === null ? UNKNOWN : `${days} ${days === 1 ? 'day' : 'days'} a week`,
        },
        { label: 'Daily activity', value: titleOf(ACTIVITY_OPTIONS, draft.activityLevel) || UNKNOWN },
        { label: 'Sleep', value: draft.sleepHours.trim() ? `${draft.sleepHours.trim()} hours a night` : UNKNOWN },
      ],
    },
    {
      step: 'location',
      title: 'Workout location',
      rows: [{ label: 'Location', value: titleOf(LOCATION_OPTIONS, draft.location) || UNKNOWN }],
    },
  ];
}
