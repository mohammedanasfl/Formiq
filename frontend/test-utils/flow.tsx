import { AppState, BackHandler, type AppStateStatus } from 'react-native';
import { act, fireEvent, screen } from '@testing-library/react-native';

import { OnboardingFlow } from '../src/onboarding/OnboardingFlow';
import { SessionProvider } from '../src/session/SessionProvider';
import type { ThemeScheme } from '../src/theme';
import { fakeToken, type MockFetch } from './mockFetch';
import { renderWithTheme } from './renderWithTheme';

export const USER_ID = 7;
export const TOKEN = fakeToken(USER_ID);

export const CATALOG = [
  { id: 1, name: 'Dumbbell', description: null, is_active: true },
  { id: 2, name: 'Barbell', description: null, is_active: true },
  { id: 3, name: 'Kettlebell', description: null, is_active: true },
  { id: 4, name: 'Resistance Band', description: null, is_active: true },
];

export function renderFlow(scheme: ThemeScheme = 'dark') {
  return renderWithTheme(
    <SessionProvider>
      <OnboardingFlow />
    </SessionProvider>,
    scheme,
  );
}

type Role = 'button' | 'radio' | 'checkbox' | 'link' | 'tab';

export async function tap(role: Role, name: string | RegExp) {
  await fireEvent.press(screen.getByRole(role, { name }));
}

export async function typeInto(label: string, text: string) {
  await fireEvent.changeText(screen.getByLabelText(label), text);
}

// Walks the happy path one screen at a time, each helper ending on the next screen.
export async function createAccount(backend: MockFetch) {
  backend.on('POST', '/auth/register', { status: 201, body: { access_token: TOKEN, token_type: 'bearer' } });
  await tap('button', 'Get Started');
  await typeInto('Email', 'sam@example.com');
  await typeInto('Password', 'longenough');
  await tap('button', 'Create Account');
  await screen.findByText('Your Fitness Goal');
}

export async function chooseGoal() {
  await tap('radio', /Build Muscle/);
  await tap('button', 'Continue');
  await screen.findByText('Tell us about yourself');
}

export async function fillDetails() {
  await typeInto('First name', 'Sam');
  await typeInto('Age', '30');
  await tap('radio', 'Other');
  await typeInto('Height (cm)', '175');
  await typeInto('Weight (kg)', '70');
  await tap('button', 'Next');
  await screen.findByText('Your training');
}

export async function fillTraining() {
  await tap('radio', /Beginner/);
  await tap('radio', '3');
  await tap('radio', 'Moderate');
  await typeInto('Sleep per night', '7.5');
  await tap('button', 'Next');
  await screen.findByText('Workout location');
}

// Arrives on the equipment step, which asks the backend for the catalog as soon as it opens: the
// reply must be ready before then.
export async function chooseLocation(backend: MockFetch) {
  backend.on('GET', '/equipment', { status: 200, body: CATALOG });
  await tap('radio', /^Gym/);
  await tap('button', 'Next');
  await screen.findByText('Available equipment');
}

export async function chooseEquipment() {
  await screen.findByRole('checkbox', { name: /Dumbbell/ });
  await tap('checkbox', /Dumbbell/);
  await tap('checkbox', /Kettlebell/);
  await tap('button', 'Next');
  await screen.findByText('Review profile');
}

export async function reachReview(backend: MockFetch) {
  await createAccount(backend);
  await chooseGoal();
  await fillDetails();
  await fillTraining();
  await chooseLocation(backend);
  await chooseEquipment();
}

// The profile the happy path above enters, as the backend should receive it.
export const EXPECTED_PROFILE = {
  first_name: 'Sam',
  age: 30,
  height_cm: 175,
  weight_kg: 70,
  gender: 'other',
  fitness_experience: 'beginner',
  goal: 'build_muscle',
  training_frequency_per_week: 3,
  training_location: 'gym',
  activity_level: 'moderate',
  sleep_hours: 7.5,
  // chooseEquipment picks Dumbbell and Kettlebell (ids 1 and 3 of CATALOG)
  equipment_ids: [1, 3],
  no_equipment: false,
};

// Android's hardware back button: the handlers the flow has registered, most recent first.
type BackHandlerCallback = Parameters<typeof BackHandler.addEventListener>[1];

export function captureHardwareBack() {
  const handlers: BackHandlerCallback[] = [];
  jest.spyOn(BackHandler, 'addEventListener').mockImplementation((_event, handler) => {
    handlers.push(handler);
    return {
      remove: () => {
        const index = handlers.indexOf(handler);
        if (index >= 0) handlers.splice(index, 1);
      },
    };
  });
  return async function pressHardwareBack(): Promise<boolean> {
    let consumed = false;
    await act(async () => {
      for (const handler of [...handlers].reverse()) {
        if (handler({} as never)) {
          consumed = true;
          return;
        }
      }
    });
    return consumed;
  };
}

// The app moving to the background and coming back: the handlers registered for AppState's "change", and a
// function that tells them the new state.
type AppStateCallback = (state: AppStateStatus) => void;

export function captureAppState() {
  const handlers: AppStateCallback[] = [];
  jest.spyOn(AppState, 'addEventListener').mockImplementation((_event, handler) => {
    handlers.push(handler as AppStateCallback);
    return {
      remove: () => {
        const index = handlers.indexOf(handler as AppStateCallback);
        if (index >= 0) handlers.splice(index, 1);
      },
    };
  });
  return async function moveAppTo(state: AppStateStatus): Promise<void> {
    await act(async () => {
      for (const handler of [...handlers]) handler(state);
    });
  };
}
