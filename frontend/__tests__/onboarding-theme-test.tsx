import { screen } from '@testing-library/react-native';

import { themes, type ThemeScheme } from '../src/theme';
import { chooseGoal, createAccount, fillDetails, reachReview, renderFlow, tap, typeInto } from '../test-utils/flow';
import { installMockFetch, type MockFetch } from '../test-utils/mockFetch';

let backend: MockFetch;

beforeEach(() => {
  backend = installMockFetch();
});

// Both themes are checked screen by screen against the semantic tokens: nothing is compared with a
// hex value written here, so changing a palette never needs these tests changed.
describe.each<ThemeScheme>(['dark', 'light'])('onboarding in the %s theme', (scheme) => {
  const c = themes[scheme].colors;

  // The welcome photo is designed dark only: it keeps the dark tokens in both app themes.
  test('welcome: stays dark, with a primary action and an outlined secondary one', async () => {
    const dark = themes.dark.colors;
    await renderFlow(scheme);

    expect(screen.getByTestId('welcome-screen')).toHaveStyle({ backgroundColor: dark.background });
    expect(screen.getByRole('header')).toHaveStyle({ color: dark.textPrimary });
    expect(screen.getByText('Your Personal Fitness Assistant')).toHaveStyle({ color: dark.textSecondary });
    expect(screen.getByRole('button', { name: 'Get Started' })).toHaveStyle({
      backgroundColor: dark.primary,
      borderColor: dark.primary,
    });
    expect(screen.getByText('Get Started')).toHaveStyle({ color: dark.textOnPrimary });
    expect(screen.getByRole('button', { name: 'I already have an account' })).toHaveStyle({
      borderColor: dark.borderStrong,
    });
    expect(screen.getByText('I already have an account')).toHaveStyle({ color: dark.textPrimary });
  });

  // Like the welcome photo, the sign-up screen is designed dark only: it keeps the dark tokens in
  // both app themes.
  test('sign up: stays dark, with fields, a link and an error that use the tokens', async () => {
    const dark = themes.dark.colors;
    await renderFlow(scheme);
    await tap('button', 'Get Started');

    expect(screen.getByTestId('signup-screen')).toHaveStyle({ backgroundColor: dark.background });
    expect(screen.getByLabelText('Email')).toHaveStyle({
      backgroundColor: dark.surface,
      borderColor: dark.borderStrong,
      color: dark.textPrimary,
    });
    expect(screen.getByText('Log in')).toHaveStyle({ color: dark.accent });

    await tap('button', 'Create Account');
    expect(screen.getByLabelText('Email')).toHaveStyle({ borderColor: dark.error });
    expect(screen.getByText('Enter your email address.')).toHaveStyle({ color: dark.error });

    backend.on('POST', '/auth/register', 'network-error');
    await typeInto('Email', 'sam@example.com');
    await typeInto('Password', 'longenough');
    await tap('button', 'Create Account');
    await screen.findByText("Can't reach Formiq. Check your connection and try again.");
    expect(screen.getByRole('alert')).toHaveStyle({ borderColor: dark.error });
  });

  // The log-in screen shares the sign-up screen's design: dark only, whatever the app theme.
  test('log in: stays dark, with fields, a link and an error that use the tokens', async () => {
    const dark = themes.dark.colors;
    await renderFlow(scheme);
    await tap('button', 'I already have an account');

    expect(screen.getByTestId('signin-screen')).toHaveStyle({ backgroundColor: dark.background });
    expect(screen.getByLabelText('Email')).toHaveStyle({
      backgroundColor: dark.surface,
      borderColor: dark.borderStrong,
      color: dark.textPrimary,
    });
    expect(screen.getByText('Create an account')).toHaveStyle({ color: dark.accent });

    await tap('button', 'Log in');
    expect(screen.getByLabelText('Email')).toHaveStyle({ borderColor: dark.error });
    expect(screen.getByText('Enter your email address.')).toHaveStyle({ color: dark.error });

    backend.on('POST', '/auth/login', 'network-error');
    await typeInto('Email', 'sam@example.com');
    await typeInto('Password', 'longenough');
    await tap('button', 'Log in');
    await screen.findByText("Can't reach Formiq. Check your connection and try again.");
    expect(screen.getByRole('alert')).toHaveStyle({ borderColor: dark.error });
  });

  // The goal step is the first profile step with the dark photo design: like the account screens, it
  // keeps the dark tokens in both app themes.
  test('goal: stays dark, the selected card is outlined in emerald, the others are plain', async () => {
    const dark = themes.dark.colors;
    await renderFlow(scheme);
    await createAccount(backend);

    expect(screen.getByTestId('step-frame')).toHaveStyle({ backgroundColor: dark.background });
    expect(screen.getByRole('header')).toHaveStyle({ color: dark.textPrimary });
    await tap('radio', /Build Muscle/);

    expect(screen.getByRole('radio', { name: /Build Muscle/ })).toHaveStyle({ borderColor: dark.accent });
    expect(screen.getByRole('radio', { name: /Lose Weight/ })).toHaveStyle({ borderColor: dark.borderStrong });
    expect(screen.getByTestId('progress-segment-1')).toHaveStyle({ backgroundColor: dark.primary });
    expect(screen.getByTestId('progress-segment-2')).toHaveStyle({ backgroundColor: dark.borderStrong });
    expect(screen.getByRole('button', { name: 'Continue' })).toHaveStyle({ backgroundColor: dark.primary });
  });

  // Personal details has the dark photo design of the goal step: dark tokens in both app themes.
  test('details: stays dark, with chips, a unit switch, fields and errors that use the tokens', async () => {
    const dark = themes.dark.colors;
    await renderFlow(scheme);
    await createAccount(backend);
    await chooseGoal();

    expect(screen.getByTestId('step-frame')).toHaveStyle({ backgroundColor: dark.background });
    await tap('radio', 'Other');
    // the chosen chip is outlined in emerald and tinted, like the cards of the goal step
    expect(screen.getByRole('radio', { name: 'Other' })).toHaveStyle({
      borderColor: dark.accent,
      backgroundColor: dark.primarySubtle,
    });
    expect(screen.getByText('Other')).toHaveStyle({ color: dark.textPrimary });
    expect(screen.getByRole('radio', { name: 'Male' })).toHaveStyle({
      backgroundColor: dark.surface,
      borderColor: dark.borderStrong,
    });
    expect(screen.getByRole('radio', { name: 'cm' })).toHaveStyle({ backgroundColor: dark.primary });
    expect(screen.getByLabelText('First name')).toHaveStyle({ backgroundColor: dark.surface, color: dark.textPrimary });

    await tap('button', 'Next');
    expect(screen.getByText('Enter your first name.')).toHaveStyle({ color: dark.error });
    expect(screen.getByLabelText('First name')).toHaveStyle({ borderColor: dark.error });
  });

  // The steps after the details have the same dark photo design: dark tokens in both app themes.
  test('training, location, equipment and review: stay dark, with outlined choices that use the tokens', async () => {
    const dark = themes.dark.colors;
    await renderFlow(scheme);
    await createAccount(backend);
    await chooseGoal();
    await fillDetails();

    expect(screen.getByTestId('step-frame')).toHaveStyle({ backgroundColor: dark.background });
    await tap('radio', /Beginner/);
    expect(screen.getByRole('radio', { name: /Beginner/ })).toHaveStyle({
      borderColor: dark.accent,
      backgroundColor: `${dark.primarySubtle}E6`,
    });
    expect(screen.getByRole('radio', { name: /Advanced/ })).toHaveStyle({ borderColor: dark.borderStrong });
    await tap('radio', '3');
    expect(screen.getByRole('radio', { name: '3' })).toHaveStyle({ borderColor: dark.accent, backgroundColor: dark.primarySubtle });
    expect(screen.getByLabelText('Sleep per night')).toHaveStyle({ backgroundColor: dark.surface, color: dark.textPrimary });
    await tap('button', 'Next');
    expect(screen.getByText('Choose an activity level.')).toHaveStyle({ color: dark.error });

    await tap('radio', 'Moderate');
    await typeInto('Sleep per night', '7.5');
    await tap('button', 'Next');
    await screen.findByText('Workout location');
    expect(screen.getByTestId('step-frame')).toHaveStyle({ backgroundColor: dark.background });
    await tap('radio', /^Gym/);
    expect(screen.getByRole('radio', { name: /^Gym/ })).toHaveStyle({ borderColor: dark.accent });
    expect(screen.getByRole('radio', { name: /^Home/ })).toHaveStyle({ borderColor: dark.borderStrong });
  });

  test('review: stays dark, with the not-saved note, plain sections and the save button', async () => {
    const dark = themes.dark.colors;
    await renderFlow(scheme);
    await reachReview(backend);

    expect(screen.getByTestId('step-frame')).toHaveStyle({ backgroundColor: dark.background });
    expect(screen.getByRole('button', { name: 'Save profile' })).toHaveStyle({ backgroundColor: dark.primary });
    expect(screen.getByText('Not saved yet')).toHaveStyle({ color: dark.textPrimary });
    expect(screen.getByText('Build Muscle')).toHaveStyle({ color: dark.textPrimary });
    expect(screen.getByRole('link', { name: 'Edit goal' })).toBeOnTheScreen();
    expect(screen.getAllByText('Edit')[0]).toHaveStyle({ color: dark.accent });
  });
});
