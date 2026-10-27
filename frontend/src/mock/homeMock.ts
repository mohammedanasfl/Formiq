// MOCK DATA: nothing in this file comes from the Formiq backend.
//
// The UI-first design phase builds the screens against these made-up values so their look can be
// settled before any integration. They are not a user's workouts, calories or progress, and no screen
// may present them as if they were. When a screen is connected, it receives its `HomeData` from a
// service instead, and this file goes away.
//
// Where this differs from the design reference on purpose: the reference lists "Core & Abs Focus" both
// as today's workout and as completed today, which cannot both be true, so the recent activity here
// holds earlier sessions.
//
// A workout's `categories` and `durationMinutes` are invented here: the backend's workout plan has
// neither (see src/workouts/types.ts), and the real plans of the integration phase will not carry them
// until a source for them is decided. The mock also shows what a real plan looks like today: one of the
// up-next workouts has no length at all.

import type { WorkoutCategory } from '../workouts/categories';
import type { WorkoutCardData } from '../workouts/types';

// Today's workout is not here: it is the backend's (src/home/todayWorkout.ts), and the rest of Home is still
// mock data.
export type HomeData = {
  // first name, for the greeting; a blank one is left out of it
  userName: string;
  // planned workouts after today's, in the order they come
  upNext: WorkoutCardData[];
  nutrition: {
    kcal: number;
    // 0 to 1
    progress: number;
  };
  weeklyGoal: {
    // a short verdict such as "On track"
    status: string;
    sessionsDone: number;
    sessionsTarget: number;
  };
  recentActivity: { id: string; title: string; subtitle: string; categories?: WorkoutCategory[] }[];
};

export const MOCK_HOME: HomeData = {
  userName: 'Anas',
  upNext: [
    // no length: a real plan stores none
    {
      id: 'mock-workout-up-1',
      title: 'Lower Body Strength',
      description: 'Squats and hinges for stronger legs and glutes.',
      exerciseCount: 6,
      categories: ['lower-body'],
    },
    {
      id: 'mock-workout-up-2',
      title: 'Mobility Reset',
      durationMinutes: 18,
      exerciseCount: 5,
      categories: ['mobility'],
    },
  ],
  nutrition: { kcal: 1850, progress: 0.6 },
  weeklyGoal: { status: 'On track', sessionsDone: 4, sessionsTarget: 7 },
  recentActivity: [
    { id: 'mock-1', title: 'Upper Body Strength', subtitle: 'Completed • Yesterday', categories: ['upper-body'] },
    { id: 'mock-2', title: 'Lower Body Power', subtitle: 'Completed • Sunday', categories: ['lower-body'] },
    { id: 'mock-3', title: 'Full Body Mobility', subtitle: 'Completed • Friday', categories: ['mobility'] },
  ],
};
