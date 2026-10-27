import { fireEvent, render, screen } from '@testing-library/react-native';

import App from '../src/App';
import {
  chooseEquipment,
  chooseGoal,
  chooseLocation,
  createAccount,
  CATALOG,
  EXPECTED_PROFILE,
  fillDetails,
  fillTraining,
  reachReview,
  renderFlow,
  tap,
  TOKEN,
  typeInto,
  USER_ID,
} from '../test-utils/flow';
import { installMockFetch, type MockFetch } from '../test-utils/mockFetch';
import { backendWorkouts, readsMade } from '../test-utils/workoutFixtures';

// Home greets for the time of day on the real clock (with the mock's name)
const HOME_GREETING = /^Good (morning|afternoon|evening), Anas$/;

let backend: MockFetch;

beforeEach(() => {
  backend = installMockFetch();
});

describe('welcome', () => {
  test('the app opens on the welcome screen, in the dark theme', async () => {
    await render(<App />);

    expect(screen.getByRole('header')).toHaveTextContent('Formiq');
    screen.getByText('Your Personal Fitness Assistant');
    expect(screen.getByRole('button', { name: 'Get Started' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'I already have an account' })).toBeEnabled();
    expect(backend.requests).toHaveLength(0);
  });

  test('"Get Started" opens sign up and "I already have an account" opens log in', async () => {
    await renderFlow();

    await tap('button', 'Get Started');
    expect(screen.getByRole('header')).toHaveTextContent('Create Account');

    await tap('button', 'Back');
    await tap('button', 'I already have an account');
    expect(screen.getByRole('header')).toHaveTextContent('Log in');
  });

  test('offers no Google or Apple sign-in: the backend has none', async () => {
    await renderFlow();
    await tap('button', 'Get Started');

    expect(screen.queryByText(/google/i)).toBeNull();
    expect(screen.queryByText(/apple/i)).toBeNull();
  });
});

describe('sign up', () => {
  test('checks the fields before asking the backend', async () => {
    await renderFlow();
    await tap('button', 'Get Started');

    await tap('button', 'Create Account');
    expect(screen.getAllByRole('alert').map((alert) => alert.props.children ?? '')).not.toHaveLength(0);
    screen.getByText('Enter your email address.');
    screen.getByText('Enter your password.');

    await typeInto('Email', 'not-an-email');
    await typeInto('Password', 'short');
    await tap('button', 'Create Account');
    screen.getByText('Enter a valid email address.');
    screen.getByText('Use at least 8 characters.');
    expect(backend.requests).toHaveLength(0);
  });

  test('creates the account with the email and password only, then moves on to the goal', async () => {
    await renderFlow();
    await createAccount(backend);

    expect(backend.requests).toHaveLength(1);
    expect(backend.requests[0]).toMatchObject({
      method: 'POST',
      path: '/auth/register',
      body: { email: 'sam@example.com', password: 'longenough' },
    });
    expect(screen.getByRole('progressbar')).toHaveAccessibleName('Step 1 of 6');
  });
});

describe('the profile steps', () => {
  test('a goal must be chosen, and the choice is announced as checked', async () => {
    await renderFlow();
    await createAccount(backend);

    await tap('button', 'Continue');
    screen.getByText('Choose a goal to continue.');
    expect(screen.getByRole('alert')).toHaveTextContent('Choose a goal to continue.');

    expect(screen.getAllByRole('radio')).toHaveLength(3);
    await tap('radio', /Build Muscle/);
    expect(screen.getByRole('radio', { name: /Build Muscle/ })).toBeChecked();
    expect(screen.getByRole('radio', { name: /Lose Weight/ })).not.toBeChecked();
    expect(screen.queryByRole('alert')).toBeNull(); // choosing a goal takes the message away

    await tap('radio', /Lose Weight/);
    expect(screen.getByRole('radio', { name: /Lose Weight/ })).toBeChecked();
    expect(screen.getByRole('radio', { name: /Build Muscle/ })).not.toBeChecked();
  });

  test('personal details are required and range-checked', async () => {
    await renderFlow();
    await createAccount(backend);
    await chooseGoal();

    await tap('button', 'Next');
    screen.getByText('Enter your first name.');
    screen.getByText('Enter your age as a whole number from 13 to 100.');
    screen.getByText('Choose an option.');
    screen.getByText('Enter a height from 100 to 250 cm.');
    screen.getByText('Enter a weight from 30 to 300 kg.');
    expect(screen.getByText('Tell us about yourself')).toBeOnTheScreen();

    await typeInto('First name', 'Sam');
    await typeInto('Age', '12');
    await typeInto('Height (cm)', '1750');
    await typeInto('Weight (kg)', '5');
    await tap('radio', 'Other');
    await tap('button', 'Next');
    screen.getByText('Enter your age as a whole number from 13 to 100.');
    screen.getByText('Enter a height from 100 to 250 cm.');
    screen.getByText('Enter a weight from 30 to 300 kg.');
    expect(screen.queryByText('Enter your first name.')).toBeNull();
    expect(screen.queryByText('Choose an option.')).toBeNull();
  });

  test('going back keeps everything entered', async () => {
    await renderFlow();
    await createAccount(backend);
    await chooseGoal();
    await fillDetails();

    await tap('button', 'Back');
    expect(screen.getByLabelText('First name')).toHaveDisplayValue('Sam');
    expect(screen.getByLabelText('Age')).toHaveDisplayValue('30');
    expect(screen.getByRole('radio', { name: 'Other' })).toBeChecked();
    expect(screen.getByLabelText('Height (cm)')).toHaveDisplayValue('175');
    expect(screen.getByLabelText('Weight (kg)')).toHaveDisplayValue('70');

    await tap('button', 'Back');
    expect(screen.getByRole('radio', { name: /Build Muscle/ })).toBeChecked();
    expect(screen.queryByRole('button', { name: 'Back' })).toBeNull(); // nothing before the goal
  });

  test('changing a unit converts what was typed', async () => {
    await renderFlow();
    await createAccount(backend);
    await chooseGoal();
    await typeInto('Height (cm)', '175');
    await typeInto('Weight (kg)', '70');

    await tap('radio', 'ft / in');
    expect(screen.getByLabelText('Height (feet)')).toHaveDisplayValue('5');
    expect(screen.getByLabelText('Height (inches)')).toHaveDisplayValue('9');
    await tap('radio', 'lb');
    expect(screen.getByLabelText('Weight (lb)')).toHaveDisplayValue('154.3');

    await tap('radio', 'cm');
    expect(screen.getByLabelText('Height (cm)')).toHaveDisplayValue('175.3');
    await tap('radio', 'kg');
    expect(screen.getByLabelText('Weight (kg)')).toHaveDisplayValue('70');
  });

  test('feet and inches have their own checks', async () => {
    await renderFlow();
    await createAccount(backend);
    await chooseGoal();
    await tap('radio', 'ft / in');
    await typeInto('Height (feet)', '5');
    await typeInto('Height (inches)', '12');

    await tap('button', 'Next');

    screen.getByText('Inches go from 0 to 11.');
  });

  test('training needs every answer', async () => {
    await renderFlow();
    await createAccount(backend);
    await chooseGoal();
    await fillDetails();

    await tap('button', 'Next');
    screen.getByText('Choose your experience level.');
    screen.getByText('Choose how many days a week.');
    screen.getByText('Choose an activity level.');
    screen.getByText('Enter the hours you usually sleep, from 3 to 14.');

    await tap('radio', /Advanced/);
    expect(screen.getByRole('radio', { name: /Advanced/ })).toBeChecked();
    await tap('radio', '4');
    expect(screen.getByRole('radio', { name: '4' })).toBeChecked();
    expect(screen.getByRole('radio', { name: '3' })).not.toBeChecked();
  });

  test('the workout location is a choice between gym and home, with the difference explained', async () => {
    await renderFlow();
    await createAccount(backend);
    await chooseGoal();
    await fillDetails();
    await fillTraining();

    screen.getByText(/You can use a gym/);
    screen.getByText(/You train at home with your body weight/);
    await tap('button', 'Next');
    screen.getByText('Choose where you will work out.');

    await tap('radio', /^Home/);
    expect(screen.getByRole('radio', { name: /^Home/ })).toBeChecked();
    expect(screen.getByRole('radio', { name: /^Gym/ })).not.toBeChecked();
  });
});

describe('equipment', () => {
  async function reachEquipment() {
    await renderFlow();
    await createAccount(backend);
    await chooseGoal();
    await fillDetails();
    await fillTraining();
    await tap('radio', /^Home/);
    await tap('button', 'Next');
  }

  test('lists the catalog equipment from the backend, without signing in', async () => {
    backend.on('GET', '/equipment', { status: 200, body: CATALOG });
    await reachEquipment();

    await screen.findByRole('checkbox', { name: /Dumbbell/ });
    for (const name of ['Dumbbell', 'Barbell', 'Kettlebell', 'Resistance Band']) {
      expect(screen.getByRole('checkbox', { name: new RegExp(name) })).toBeOnTheScreen();
    }
    const request = backend.requests.find((r) => r.path === '/equipment')!;
    expect(request.headers.Authorization).toBeUndefined();
  });

  test('does not say the choice is lost, and still does not promise exercises', async () => {
    backend.on('GET', '/equipment', { status: 200, body: CATALOG });
    await reachEquipment();

    expect(screen.queryByText(/Formiq doesn't store your equipment/)).toBeNull();
    screen.getByText(/doesn't mean there are exercises for it/);
  });

  test('no equipment and other equipment exclude each other', async () => {
    backend.on('GET', '/equipment', { status: 200, body: CATALOG });
    await reachEquipment();
    await screen.findByRole('checkbox', { name: /Dumbbell/ });

    await tap('checkbox', /Dumbbell/);
    await tap('checkbox', /Barbell/);
    expect(screen.getByRole('checkbox', { name: /Dumbbell/ })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /Barbell/ })).toBeChecked();

    await tap('checkbox', /No equipment/);
    expect(screen.getByRole('checkbox', { name: /No equipment/ })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /Dumbbell/ })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: /Barbell/ })).not.toBeChecked();

    await tap('checkbox', /Kettlebell/);
    expect(screen.getByRole('checkbox', { name: /Kettlebell/ })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /No equipment/ })).not.toBeChecked();

    await tap('checkbox', /Kettlebell/);
    expect(screen.getByRole('checkbox', { name: /Kettlebell/ })).not.toBeChecked();
  });

  test('keeps the catalog and the selection when going back and forward', async () => {
    backend.on('GET', '/equipment', { status: 200, body: CATALOG });
    await reachEquipment();
    await screen.findByRole('checkbox', { name: /Dumbbell/ });
    await tap('checkbox', /Dumbbell/);

    await tap('button', 'Back');
    await tap('button', 'Next');

    expect(screen.getByRole('checkbox', { name: /Dumbbell/ })).toBeChecked();
    expect(backend.requests.filter((r) => r.path === '/equipment')).toHaveLength(1);
  });

  test('a failed load says so and can be retried; the step can also be skipped', async () => {
    backend.on('GET', '/equipment', 'network-error');
    backend.on('GET', '/equipment', { status: 200, body: CATALOG });
    await reachEquipment();

    await screen.findByText("Can't reach Formiq. Check your connection and try again.");
    expect(screen.getByRole('alert')).toBeOnTheScreen();
    screen.getByText('You can also continue without choosing equipment.');
    expect(screen.getByRole('button', { name: 'Next' })).toBeEnabled();

    await tap('button', 'Try again');
    await screen.findByRole('checkbox', { name: /Dumbbell/ });
    expect(screen.queryByText("Can't reach Formiq. Check your connection and try again.")).toBeNull();
  });
});

describe('review and save', () => {
  test('shows every answer, and says nothing is saved yet', async () => {
    await renderFlow();
    await reachReview(backend);

    screen.getByText('Not saved yet');
    screen.getByText('Nothing is stored in your Formiq account until you tap Save profile.');
    for (const text of [
      'Build Muscle',
      'Sam',
      'Other',
      '175 cm',
      '70 kg',
      'Beginner',
      '3 days a week',
      'Moderate',
      '7.5 hours a night',
      'Gym',
      'Dumbbell, Kettlebell',
    ]) {
      expect(screen.getByText(text)).toBeOnTheScreen();
    }
    // the equipment goes with the rest of the profile: it is not said to stay on the device
    expect(screen.queryByText(/Only on this device/)).toBeNull();
    expect(backend.requests.filter((r) => r.path.endsWith('/profile'))).toHaveLength(0);
  });

  test('"No equipment" is shown as chosen', async () => {
    await renderFlow();
    await createAccount(backend);
    await chooseGoal();
    await fillDetails();
    await fillTraining();
    await chooseLocation(backend);
    await screen.findByRole('checkbox', { name: /No equipment/ });
    await tap('checkbox', /No equipment/);
    await tap('button', 'Next');

    screen.getByText('No equipment');
  });

  test('an answer can be edited from the review, and returns to the review', async () => {
    await renderFlow();
    await reachReview(backend);

    await tap('link', 'Edit goal');
    expect(screen.getByRole('radio', { name: /Build Muscle/ })).toBeChecked();
    await tap('radio', /Lose Weight/);
    await tap('button', 'Done');

    await screen.findByText('Review profile');
    screen.getByText('Lose Weight');
    expect(screen.queryByText('Build Muscle')).toBeNull();
  });

  test('saves the profile with the token, exactly the backend fields and the equipment chosen, and only then shows success', async () => {
    let release: () => void = () => undefined;
    const answered = new Promise<void>((resolve) => (release = resolve));
    backend.on('POST', `/users/${USER_ID}/profile`, async () => {
      await answered;
      return { status: 201, body: { id: 1, user_id: USER_ID } };
    });
    await renderFlow();
    await reachReview(backend);

    // The press resolves when the save does, so it is not awaited until the reply is released.
    const pressed = fireEvent.press(screen.getByRole('button', { name: 'Save profile' }));

    // while the backend has not answered: still the review, a busy button, no success
    await screen.findByRole('button', { name: 'Saving…' });
    expect(screen.getByRole('button', { name: 'Saving…' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Saving…' })).toHaveProp('accessibilityState', { disabled: true });
    expect(screen.queryByText('Profile saved')).toBeNull();
    screen.getByText('Review profile');

    release();
    await pressed;
    await screen.findByText('Profile saved');

    const request = backend.requests.find((r) => r.path === `/users/${USER_ID}/profile`)!;
    expect(request.method).toBe('POST');
    expect(request.headers.Authorization).toBe(`Bearer ${TOKEN}`);
    expect(request.body).toEqual(EXPECTED_PROFILE);
    screen.getByText('Your profile is saved to your Formiq account.');
    // the equipment went with the profile: nothing says it was lost
    expect(screen.queryByText(/equipment/i)).toBeNull();
    screen.getByText("Workout plans aren't in the app yet.");
    expect(screen.queryByText(/personalised/i)).toBeNull();
  });

  test('sends "no equipment" explicitly, and no ids', async () => {
    backend.on('POST', `/users/${USER_ID}/profile`, { status: 201, body: {} });
    await renderFlow();
    await createAccount(backend);
    await chooseGoal();
    await fillDetails();
    await fillTraining();
    await chooseLocation(backend);
    await screen.findByRole('checkbox', { name: /No equipment/ });
    await tap('checkbox', /No equipment/);
    await tap('button', 'Next');

    await tap('button', 'Save profile');
    await screen.findByText('Profile saved');

    const request = backend.requests.find((r) => r.path === `/users/${USER_ID}/profile`)!;
    expect(request.body).toEqual({ ...EXPECTED_PROFILE, equipment_ids: [], no_equipment: true });
  });

  test('a person who chose no equipment and no "no equipment" sends neither: the backend keeps that they did not say', async () => {
    backend.on('POST', `/users/${USER_ID}/profile`, { status: 201, body: {} });
    await renderFlow();
    await createAccount(backend);
    await chooseGoal();
    await fillDetails();
    await fillTraining();
    await chooseLocation(backend);
    await screen.findByRole('checkbox', { name: /Dumbbell/ });
    await tap('button', 'Next');
    screen.getByText('Not chosen');

    await tap('button', 'Save profile');
    await screen.findByText('Profile saved');

    const request = backend.requests.find((r) => r.path === `/users/${USER_ID}/profile`)!;
    expect(request.body).toEqual({ ...EXPECTED_PROFILE, equipment_ids: [], no_equipment: false });
  });

  test('changing the equipment from the review saves the changed choice', async () => {
    backend.on('POST', `/users/${USER_ID}/profile`, { status: 201, body: {} });
    await renderFlow();
    await reachReview(backend);

    await tap('link', 'Edit equipment');
    await tap('checkbox', /Dumbbell/);
    await tap('checkbox', /Barbell/);
    await tap('button', 'Done');
    await screen.findByText('Review profile');
    screen.getByText('Barbell, Kettlebell');
    await tap('button', 'Save profile');
    await screen.findByText('Profile saved');

    const request = backend.requests.find((r) => r.path === `/users/${USER_ID}/profile`)!;
    expect(request.body).toMatchObject({ equipment_ids: [3, 2], no_equipment: false });
  });

  test('continues to the home dashboard, and logging out starts over', async () => {
    backend.on('POST', `/users/${USER_ID}/profile`, { status: 201, body: {} });
    // the dashboard reads today's workout for the user who just signed up: nothing is planned yet
    backendWorkouts(backend, USER_ID);
    await renderFlow();
    await reachReview(backend);
    await tap('button', 'Save profile');
    await screen.findByText('Profile saved');

    await tap('button', 'Continue');
    // the dashboard is built on mock data for now, so its greeting is the mock name, not "Sam"
    screen.getByRole('header', { name: HOME_GREETING });
    expect(screen.queryByText('Temporary screen')).toBeNull();
    await screen.findByText('No workout planned today');
    // only reads, for this user, with their token, after the profile was saved
    expect(readsMade(backend).filter((read) => read.startsWith('GET /users/'))).toHaveLength(3);

    // Log out is on the Profile tab (Home's header has no account menu any more)
    await tap('tab', 'Profile');
    await tap('button', 'Log out');
    expect(screen.getByRole('header')).toHaveTextContent('Formiq');
    await tap('button', 'Get Started');
    await typeInto('Email', 'sam@example.com');
    await typeInto('Password', 'longenough');
    backend.on('POST', '/auth/register', { status: 201, body: { access_token: TOKEN } });
    await tap('button', 'Create Account');
    await screen.findByText('Your Fitness Goal');
    expect(screen.getByRole('radio', { name: /Build Muscle/ })).not.toBeChecked(); // a clean draft
  });
});

describe('steps are numbered', () => {
  test('progress runs from 1 to 6 across the profile steps', async () => {
    await renderFlow();
    await createAccount(backend);
    const progress = () => screen.getByRole('progressbar');

    expect(progress()).toHaveProp('accessibilityValue', { min: 1, max: 6, now: 1 });
    await chooseGoal();
    expect(progress()).toHaveAccessibleName('Step 2 of 6');
    await fillDetails();
    expect(progress()).toHaveAccessibleName('Step 3 of 6');
    await fillTraining();
    expect(progress()).toHaveAccessibleName('Step 4 of 6');
    await chooseLocation(backend);
    expect(progress()).toHaveAccessibleName('Step 5 of 6');
    await chooseEquipment();
    expect(progress()).toHaveAccessibleName('Step 6 of 6');
  });
});
