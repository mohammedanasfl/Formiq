import { fireEvent, screen, within } from '@testing-library/react-native';

import {
  captureHardwareBack,
  chooseGoal,
  createAccount,
  EXPECTED_PROFILE,
  reachReview,
  renderFlow,
  tap,
  TOKEN,
  typeInto,
  USER_ID,
} from '../test-utils/flow';
import { installMockFetch, type MockFetch } from '../test-utils/mockFetch';
import { localDateKey } from '../src/home/format';
import { backendWorkouts, corePlan } from '../test-utils/workoutFixtures';

// Home greets for the time of day on the real clock (with the mock's name)
const HOME_GREETING = /^Good (morning|afternoon|evening), Anas$/;

let backend: MockFetch;
const PROFILE_PATH = `/users/${USER_ID}/profile`;

beforeEach(() => {
  backend = installMockFetch();
});

const profileRequests = () => backend.requests.filter((r) => r.path === PROFILE_PATH && r.method === 'POST');

describe('sign up that fails', () => {
  async function submit() {
    await tap('button', 'Get Started');
    await typeInto('Email', 'sam@example.com');
    await typeInto('Password', 'longenough');
    await tap('button', 'Create Account');
  }

  test.each([
    ['an email that already has an account', { status: 409, body: { detail: 'an account with this email already exists' } }, 'An account with this email already exists. Log in instead.'],
    ['no connection', 'network-error' as const, "Can't reach Formiq. Check your connection and try again."],
    ['a server error', { status: 500 }, "Something went wrong on Formiq's side. Try again."],
    ['a backend that cannot sign anyone in', { status: 503, body: { detail: 'authentication is not configured' } }, "Formiq isn't available right now. Try again in a moment."],
  ])('%s: says so, and does not move on as if it worked', async (_name, reply, message) => {
    backend.on('POST', '/auth/register', reply);
    await renderFlow();

    await submit();

    await screen.findByText(message);
    expect(screen.getByRole('alert')).toHaveTextContent(message);
    expect(screen.getByRole('header')).toHaveTextContent('Create Account');
    expect(screen.queryByText('Your Fitness Goal')).toBeNull();
    expect(screen.getByRole('button', { name: 'Create Account' })).toBeEnabled();
  });

  test('shows progress while waiting, then lets the person try again', async () => {
    let release: () => void = () => undefined;
    const answered = new Promise<void>((resolve) => (release = resolve));
    backend.on('POST', '/auth/register', async () => {
      await answered;
      return { status: 500 };
    });
    backend.on('POST', '/auth/register', { status: 201, body: { access_token: TOKEN } });
    await renderFlow();
    await tap('button', 'Get Started');
    await typeInto('Email', 'sam@example.com');
    await typeInto('Password', 'longenough');

    const pressed = fireEvent.press(screen.getByRole('button', { name: 'Create Account' }));
    await screen.findByRole('button', { name: 'Creating account…' });
    expect(screen.getByRole('button', { name: 'Creating account…' })).toBeDisabled();

    release();
    await pressed;
    await screen.findByText("Something went wrong on Formiq's side. Try again.");

    await tap('button', 'Create Account');
    await screen.findByText('Your Fitness Goal');
    expect(screen.queryByText("Something went wrong on Formiq's side. Try again.")).toBeNull();
  });
});

describe('saving that fails', () => {
  test.each([
    ['a server error', { status: 500 }, "Something went wrong on Formiq's side. Try again."],
    ['no connection', 'network-error' as const, "Can't reach Formiq. Check your connection and try again."],
    ['details the backend rejects', { status: 422, body: { detail: [{ msg: 'bad' }] } }, "Formiq couldn't accept some of your details. Go back and check them."],
  ])('%s: stays on the review, says so, and retrying saves the same profile', async (_name, reply, message) => {
    backend.on('POST', PROFILE_PATH, reply);
    backend.on('POST', PROFILE_PATH, { status: 201, body: {} });
    await renderFlow();
    await reachReview(backend);

    await tap('button', 'Save profile');

    await screen.findByText(message);
    expect(screen.getByRole('alert')).toHaveTextContent(message);
    screen.getByText('Review profile');
    expect(screen.queryByText('Profile saved')).toBeNull();
    screen.getByText('Build Muscle'); // the answers are still there
    screen.getByText('Nothing is stored in your Formiq account until you tap Save profile.');
    expect(screen.getByRole('button', { name: 'Try again' })).toBeEnabled();

    await tap('button', 'Try again');

    await screen.findByText('Profile saved');
    expect(profileRequests()).toHaveLength(2);
    expect(profileRequests()[1].body).toEqual(EXPECTED_PROFILE);
    expect(screen.queryByText(message)).toBeNull();
  });

  test('a save the backend refuses for the equipment is not shown as saved, and the choice is kept', async () => {
    backend.on('POST', PROFILE_PATH, { status: 400, body: { detail: 'equipment 3 is not in the catalog' } });
    await renderFlow();
    await reachReview(backend);

    await tap('button', 'Save profile');

    await screen.findByText('Equipment 3 is not in the catalog.');
    screen.getByText('Review profile');
    expect(screen.queryByText('Profile saved')).toBeNull();
    screen.getByText('Dumbbell, Kettlebell'); // still what the person chose, and still only a draft
    expect(profileRequests()).toHaveLength(1);
    expect(profileRequests()[0].body).toEqual(EXPECTED_PROFILE);
  });

  test('a save that never reached the backend does not say the equipment was saved either', async () => {
    backend.on('POST', PROFILE_PATH, 'network-error');
    await renderFlow();
    await reachReview(backend);

    await tap('button', 'Save profile');

    await screen.findByText("Can't reach Formiq. Check your connection and try again.");
    expect(screen.queryByText('Profile saved')).toBeNull();
    expect(screen.queryByText(/equipment.*saved/i)).toBeNull();
    screen.getByText('Nothing is stored in your Formiq account until you tap Save profile.');
  });

  test('the reason for a failed save is in the footer, in view whatever the scroll position', async () => {
    backend.on('POST', PROFILE_PATH, { status: 500 });
    await renderFlow();
    await reachReview(backend);

    await tap('button', 'Save profile');

    const footer = await screen.findByTestId('screen-footer');
    expect(within(footer).getByRole('alert')).toHaveTextContent("Something went wrong on Formiq's side. Try again.");
    expect(within(footer).getByRole('button', { name: 'Try again' })).toBeOnTheScreen();
    expect(within(screen.getByTestId('screen-scroll')).queryByRole('alert')).toBeNull();
  });

  test('an expired session goes to log in with a notice, keeps the answers, and returns to the review', async () => {
    backend.on('POST', PROFILE_PATH, { status: 401, body: { detail: 'not authenticated' } });
    backend.on('POST', PROFILE_PATH, { status: 201, body: {} });
    backend.on('POST', '/auth/login', { status: 200, body: { access_token: TOKEN } });
    backend.on('GET', PROFILE_PATH, { status: 404, body: { detail: 'no profile found' } });
    await renderFlow();
    await reachReview(backend);

    await tap('button', 'Save profile');

    await screen.findByText('Your session expired, so nothing was saved. Log in again: your answers are kept.');
    expect(screen.getByRole('header')).toHaveTextContent('Log in');
    expect(screen.queryByText('Profile saved')).toBeNull();

    await typeInto('Email', 'sam@example.com');
    await typeInto('Password', 'longenough');
    await tap('button', 'Log in');

    await screen.findByText('Review profile');
    screen.getByText('Build Muscle');
    screen.getByText('Dumbbell, Kettlebell');

    await tap('button', 'Save profile');
    await screen.findByText('Profile saved');
    expect(profileRequests()).toHaveLength(2);
  });

  test('a profile that already exists is reported, and says this one was not saved', async () => {
    backend.on('POST', PROFILE_PATH, { status: 409, body: { detail: 'a profile already exists' } });
    await renderFlow();
    await reachReview(backend);

    await tap('button', 'Save profile');

    await screen.findByText('You already have a profile');
    screen.getByText('Your account already had a saved profile, so the answers from this session were not saved.');
    expect(screen.queryByText('Your profile is saved to your Formiq account.')).toBeNull();
    expect(screen.queryByText('Profile saved')).toBeNull();
  });

  test('an unfinished draft is never sent', async () => {
    // reaching the review through the screens always gives a complete draft; clearing a field from
    // the review's edit link and skipping it is not possible, so the guard is the payload builder
    await renderFlow();
    await reachReview(backend);
    await tap('link', 'Edit personal details');
    await typeInto('Age', '');
    await tap('button', 'Done');

    screen.getByText('Enter your age as a whole number from 13 to 100.');
    expect(profileRequests()).toHaveLength(0);
  });
});

describe('log in', () => {
  async function submitLogin() {
    await tap('button', 'I already have an account');
    await typeInto('Email', 'sam@example.com');
    await typeInto('Password', 'whatever');
    await tap('button', 'Log in');
  }

  test('checks both fields before asking the backend', async () => {
    await renderFlow();
    await tap('button', 'I already have an account');

    await tap('button', 'Log in');

    screen.getByText('Enter your email address.');
    screen.getByText('Enter your password.');
    expect(backend.requests).toHaveLength(0);
  });

  test('someone with a saved profile goes straight to the home dashboard, which shows their workout for today', async () => {
    backend.on('POST', '/auth/login', { status: 200, body: { access_token: TOKEN } });
    backend.on('GET', PROFILE_PATH, { status: 200, body: {} });
    backendWorkouts(backend, USER_ID, { plans: [corePlan(localDateKey(new Date()))] });
    await renderFlow();

    await submitLogin();

    await screen.findByRole('header', { name: HOME_GREETING });
    await screen.findByRole('button', { name: /^Core & Abs Focus\./ });
    expect(backend.requests[0]).toMatchObject({
      path: '/auth/login',
      body: { email: 'sam@example.com', password: 'whatever' },
    });
    expect(backend.requests[1].headers.Authorization).toBe(`Bearer ${TOKEN}`);
  });

  test('someone without a profile continues with the goal', async () => {
    backend.on('POST', '/auth/login', { status: 200, body: { access_token: TOKEN } });
    backend.on('GET', PROFILE_PATH, { status: 404, body: { detail: 'no profile found' } });
    await renderFlow();

    await submitLogin();

    await screen.findByText('Your Fitness Goal');
  });

  test('a wrong password is refused with a plain message', async () => {
    backend.on('POST', '/auth/login', { status: 401, body: { detail: 'invalid email or password' } });
    await renderFlow();

    await submitLogin();

    await screen.findByText('Incorrect email or password.');
    expect(screen.getByRole('alert')).toBeOnTheScreen();
    expect(screen.getByRole('header')).toHaveTextContent('Log in');
    expect(backend.requests.filter((r) => r.method === 'GET')).toHaveLength(0);
  });

  test('logged in but unable to check the profile: says so, goes nowhere, and can retry', async () => {
    backend.on('POST', '/auth/login', { status: 200, body: { access_token: TOKEN } });
    backend.on('GET', PROFILE_PATH, { status: 500 });
    backend.on('GET', PROFILE_PATH, { status: 200, body: {} });
    backendWorkouts(backend, USER_ID);
    await renderFlow();

    await submitLogin();

    await screen.findByText("Something went wrong on Formiq's side. Try again.");
    expect(screen.getByRole('header')).toHaveTextContent('Log in');
    expect(screen.queryByRole('header', { name: HOME_GREETING })).toBeNull();

    await tap('button', 'Log in');
    await screen.findByRole('header', { name: HOME_GREETING });
  });

  test('the two account screens link to each other', async () => {
    await renderFlow();
    await tap('button', 'Get Started');
    await tap('link', 'Already have an account? Log in');
    expect(screen.getByRole('header')).toHaveTextContent('Log in');
    await tap('link', 'New to Formiq? Create an account');
    expect(screen.getByRole('header')).toHaveTextContent('Create Account');
  });
});

describe("Android's back button", () => {
  test('leaves the app from the welcome screen and the first step, and steps back elsewhere', async () => {
    const pressBack = captureHardwareBack();
    await renderFlow();

    expect(await pressBack()).toBe(false); // welcome: the app closes
    await tap('button', 'Get Started');
    expect(await pressBack()).toBe(true);
    expect(screen.getByRole('header')).toHaveTextContent('Formiq');

    await createAccount(backend);
    expect(await pressBack()).toBe(false); // the first profile step: nothing before it
    await chooseGoal();
    expect(await pressBack()).toBe(true);
    await screen.findByText('Your Fitness Goal');
    expect(screen.getByRole('radio', { name: /Build Muscle/ })).toBeChecked();
  });

  test('does nothing while saving, and cannot go back from the saved screen', async () => {
    const pressBack = captureHardwareBack();
    let release: () => void = () => undefined;
    const answered = new Promise<void>((resolve) => (release = resolve));
    backend.on('POST', PROFILE_PATH, async () => {
      await answered;
      return { status: 201, body: {} };
    });
    await renderFlow();
    await reachReview(backend);

    const pressed = fireEvent.press(screen.getByRole('button', { name: 'Save profile' }));
    await screen.findByRole('button', { name: 'Saving…' });
    expect(await pressBack()).toBe(true);
    screen.getByText('Review profile'); // still here

    release();
    await pressed;
    await screen.findByText('Profile saved');
    expect(await pressBack()).toBe(true);
    screen.getByText('Profile saved');
  });

  test('editing from the review goes back to the review', async () => {
    const pressBack = captureHardwareBack();
    await renderFlow();
    await reachReview(backend);

    await tap('link', 'Edit workout location');
    expect(await pressBack()).toBe(true);

    await screen.findByText('Review profile');
  });
});
