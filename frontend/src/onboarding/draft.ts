import type {
  ActivityValue,
  ExperienceValue,
  GenderValue,
  GoalValue,
  LocationValue,
} from './options';

export type HeightUnit = 'cm' | 'ft';
export type WeightUnit = 'kg' | 'lb';

// Everything entered so far, as typed. It is local and unsaved until the backend has accepted the
// profile; numbers stay text so a half-typed value is never lost or rewritten.
export type ProfileDraft = {
  goal: GoalValue | null;
  firstName: string;
  lastName: string;
  age: string;
  gender: GenderValue | null;
  heightUnit: HeightUnit;
  heightCm: string;
  heightFeet: string;
  heightInches: string;
  weightUnit: WeightUnit;
  weight: string;
  experience: ExperienceValue | null;
  trainingDays: number | null;
  activityLevel: ActivityValue | null;
  sleepHours: string;
  location: LocationValue | null;
  // The catalog equipment chosen (Equipment.id from GET /equipment), or noEquipment: bodyweight only. Never both;
  // neither says nothing. They are sent with the profile, so the backend keeps them.
  equipmentIds: number[];
  noEquipment: boolean;
};

export const emptyDraft: ProfileDraft = {
  goal: null,
  firstName: '',
  lastName: '',
  age: '',
  gender: null,
  heightUnit: 'cm',
  heightCm: '',
  heightFeet: '',
  heightInches: '',
  weightUnit: 'kg',
  weight: '',
  experience: null,
  trainingDays: null,
  activityLevel: null,
  sleepHours: '',
  location: null,
  equipmentIds: [],
  noEquipment: false,
};
