import { ApiError } from './client';
import type { PlanSectionName } from './types';

// The checks the readers of the backend's answers share (workouts.ts, coach.ts). An answer the app cannot read in
// full is refused as a whole, never trimmed: a plan or an exercise that was dropped would be taken for one that
// does not exist, and a workout shown with a piece missing could be applied without the person ever seeing it.
export function invalid(): never {
  throw new ApiError('invalid-response', null, null);
}

export const isInteger = (value: unknown): value is number => typeof value === 'number' && Number.isInteger(value);
export const isText = (value: unknown): value is string => typeof value === 'string';
export const isNumberOrNull = (value: unknown): value is number | null =>
  value === null || (typeof value === 'number' && Number.isFinite(value));
export const isTextOrNull = (value: unknown): value is string | null => value === null || typeof value === 'string';
export const isIntegerOrNull = (value: unknown): value is number | null => value === null || isInteger(value);
export const isTime = (value: unknown): value is string => typeof value === 'string' && !Number.isNaN(Date.parse(value));

const SECTIONS: readonly string[] = ['WARM_UP', 'MAIN_WORKOUT', 'COOL_DOWN'] satisfies PlanSectionName[];
export const isSection = (value: unknown): value is PlanSectionName => isText(value) && SECTIONS.includes(value);
