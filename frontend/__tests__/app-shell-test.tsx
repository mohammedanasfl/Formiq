import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { MOCK_HOME } from '../src/mock/homeMock';
import { AppShell } from '../src/shell/AppShell';
import { TABS } from '../src/shell/tabs';
import { ThemeProvider, themes } from '../src/theme';
import { fixClockAt } from '../test-utils/clock';
import { captureHardwareBack } from '../test-utils/flow';
import { fakeToken, installMockFetch, type MockFetch } from '../test-utils/mockFetch';
import { renderWithTheme } from '../test-utils/renderWithTheme';
import { backendWorkouts, corePlan, NOW } from '../test-utils/workoutFixtures';

const HIDDEN = { includeHiddenElements: true };
const dark = themes.dark.colors;
const light = themes.light.colors;

const tab = (name: string) => screen.getByRole('tab', { name });

const SESSION = { token: fakeToken(7), userId: 7 };
const SAVED_PROFILE = { no_equipment: false, equipment: [{ id: 1, name: 'Dumbbell' }, { id: 2, name: 'Bench' }] };

// Home's today's workout is the backend's: a scripted one answers with the plan below, scheduled for the
// (fixed) day the tests run on, so the shell is drawn as it is for a user with a workout today
let backend: MockFetch;
let clock: ReturnType<typeof fixClockAt>;

beforeEach(() => {
  backend = installMockFetch();
  clock = fixClockAt(NOW);
  backendWorkouts(backend, SESSION.userId, { plans: [corePlan()] });
  // the Profile tab reads the equipment saved with the profile
  backend.on('GET', `/users/${SESSION.userId}/profile`, { status: 200, body: SAVED_PROFILE });
});

afterEach(() => {
  jest.restoreAllMocks();
  clock.restore();
});

// The AI Coach tab is the mock one here (the shell's own tests are about navigation); the coach on the backend has
// its own tests (coach-connected-test.tsx).
async function renderShell(scheme: 'dark' | 'light' = 'dark', coachMode: 'api' | 'mock' = 'mock') {
  const pressBack = captureHardwareBack();
  const onSignOut = jest.fn();
  const view = await renderWithTheme(<AppShell session={SESSION} onSignOut={onSignOut} coachMode={coachMode} />, scheme);
  // wait for today's card, so a test starts from a Home that has read the backend
  await screen.findByTestId('workout-card-41');
  return { ...view, onSignOut, pressBack };
}

describe('<AppShell />', () => {
  test("opens on Home: today's workout from the backend, the rest of the dashboard still mock data", async () => {
    await renderShell();

    expect(screen.getByTestId('home-screen')).toBeOnTheScreen();
    screen.getByRole('header', { name: `Good morning, ${MOCK_HOME.userName}` });
    expect(screen.getByRole('button', { name: /^Core & Abs Focus\./ })).toBeOnTheScreen();
    expect(tab('Home')).toBeSelected();
  });

  test('has the five tabs, in this exact order, in a tab list', async () => {
    await renderShell();

    expect(screen.getByTestId('bottom-tab-bar')).toHaveProp('accessibilityRole', 'tablist');
    expect(screen.getAllByRole('tab').map((node) => node.props.accessibilityLabel)).toEqual([
      'Home',
      'Discover',
      'AI Coach',
      'Progress',
      'Profile',
    ]);
    expect(TABS.map((entry) => entry.id)).toEqual(['home', 'discover', 'coach', 'progress', 'profile']);
  });

  test('Workouts and Nutrition are no longer on the bar', async () => {
    await renderShell();

    for (const name of ['Workouts', 'Nutrition', 'Coach']) {
      expect(screen.queryByRole('tab', { name })).toBeNull();
    }
  });

  test('exactly one tab is selected, and pressing another moves the selection', async () => {
    await renderShell();

    await fireEvent.press(tab('Discover'));

    expect(tab('Discover')).toBeSelected();
    for (const other of ['Home', 'AI Coach', 'Progress', 'Profile']) expect(tab(other)).not.toBeSelected();
  });

  test('Progress opens a placeholder that says it is not designed yet, and Home brings the dashboard back', async () => {
    await renderShell();

    await fireEvent.press(tab('Progress'));

    expect(screen.getByTestId('progress-placeholder')).toBeOnTheScreen();
    expect(screen.getByRole('header')).toHaveTextContent('Progress');
    screen.getByText('Not designed yet');
    screen.getByText('This screen is designed after Home. Nothing here is real yet.');
    expect(screen.queryByTestId('home-screen')).toBeNull();
    expect(screen.getByTestId('bottom-tab-bar')).toBeOnTheScreen();

    await fireEvent.press(tab('Home'));
    expect(screen.getByTestId('home-screen')).toBeOnTheScreen();
  });

  test('AI Coach opens the coach conversation, not a placeholder, with the bar still under it', async () => {
    await renderShell();

    await fireEvent.press(tab('AI Coach'));

    expect(tab('AI Coach')).toBeSelected();
    expect(screen.getByTestId('coach-screen')).toBeOnTheScreen();
    screen.getByRole('header', { name: 'Formiq Coach' });
    screen.getByLabelText('Message');
    expect(screen.queryByText('Not designed yet')).toBeNull();
    expect(screen.queryByTestId('coach-placeholder')).toBeNull();
    expect(screen.queryByTestId('home-screen')).toBeNull();
    expect(screen.getByTestId('bottom-tab-bar')).toBeOnTheScreen();

    await fireEvent.press(tab('Home'));
    expect(screen.getByTestId('home-screen')).toBeOnTheScreen();
  });

  test('Discover and Profile open their own screens, with the bar still under them', async () => {
    await renderShell();

    await fireEvent.press(tab('Discover'));
    expect(screen.getByTestId('discover-screen')).toBeOnTheScreen();
    screen.getByRole('header', { name: 'Discover' });
    expect(screen.queryByTestId('home-screen')).toBeNull();
    expect(screen.getByTestId('bottom-tab-bar')).toBeOnTheScreen();

    await fireEvent.press(tab('Profile'));
    expect(screen.getByTestId('profile-screen')).toBeOnTheScreen();
    screen.getByRole('header', { name: MOCK_HOME.userName });
    expect(screen.queryByTestId('discover-screen')).toBeNull();
    expect(screen.getByTestId('bottom-tab-bar')).toBeOnTheScreen();

    await fireEvent.press(tab('Home'));
    expect(screen.getByTestId('home-screen')).toBeOnTheScreen();
  });

  test('the Profile tab shows the equipment saved with the profile, read from the backend when it is opened', async () => {
    await renderShell();
    expect(backend.requests.filter((r) => r.path === '/users/7/profile')).toHaveLength(0);

    await fireEvent.press(tab('Profile'));

    await screen.findByText('Dumbbell, Bench');
    expect(screen.getByTestId('profile-equipment')).toHaveAccessibleName('Equipment: Dumbbell, Bench');
    const read = backend.requests.filter((r) => r.path === '/users/7/profile');
    expect(read).toHaveLength(1);
    expect(read[0].method).toBe('GET');
    expect(read[0].headers.Authorization).toBe(`Bearer ${SESSION.token}`);
  });

  test('the Profile tab does not show equipment when the backend cannot say, and can ask again', async () => {
    backend.reset();
    backendWorkouts(backend, SESSION.userId, { plans: [corePlan()] });
    backend.on('GET', '/users/7/profile', { status: 500 });
    backend.on('GET', '/users/7/profile', { status: 200, body: SAVED_PROFILE });
    await renderShell();

    await fireEvent.press(tab('Profile'));

    await screen.findByText("Something went wrong on Formiq's side. Try again.");
    expect(screen.queryByTestId('profile-equipment')).toBeNull();

    await fireEvent.press(screen.getByRole('button', { name: 'Try again' }));

    await screen.findByText('Dumbbell, Bench');
  });

  test('the Progress placeholder shows nothing that looks like a chart or a progress figure', async () => {
    await renderShell();

    await fireEvent.press(tab('Progress'));

    expect(screen.queryByText(/kcal|exercises|min\b|Completed/)).toBeNull();
  });

  test("Home's controls lead to the tabs that exist", async () => {
    await renderShell();

    await fireEvent.press(screen.getByRole('button', { name: 'Ask Formiq. Get AI guidance' }));
    expect(tab('AI Coach')).toBeSelected();
    screen.getByRole('header', { name: 'Formiq Coach' });

    await fireEvent.press(tab('Home'));
    await fireEvent.press(screen.getByRole('button', { name: "Progress: On track, Weekly goal, 4 / 7" }));
    expect(tab('Progress')).toBeSelected();

    await fireEvent.press(tab('Home'));
    await fireEvent.press(screen.getByRole('button', { name: 'Update Profile. Keep your info current' }));
    expect(tab('Profile')).toBeSelected();
    expect(screen.getByTestId('profile-screen')).toBeOnTheScreen();
  });

  test("Home's header has no profile icon or avatar: Log out is only on the Profile tab", async () => {
    await renderShell();

    expect(screen.queryByRole('button', { name: 'Account menu' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Log out' })).toBeNull();
  });

  test("the theme toggle on Home switches the whole app, the bar included, and the Profile tab agrees", async () => {
    await renderShell();
    expect(screen.getByTestId('bottom-tab-bar')).toHaveStyle({ backgroundColor: dark.surface });

    await fireEvent.press(screen.getByRole('button', { name: 'Switch to light theme' }));
    expect(screen.getByTestId('bottom-tab-bar')).toHaveStyle({ backgroundColor: light.surface });

    // the Profile tab's own theme choice is the same state
    await fireEvent.press(tab('Profile'));
    expect(screen.getByRole('radio', { name: 'Light' })).toBeChecked();
    await fireEvent.press(screen.getByRole('radio', { name: 'Dark' }));
    expect(screen.getByTestId('bottom-tab-bar')).toHaveStyle({ backgroundColor: dark.surface });

    await fireEvent.press(tab('Home'));
    expect(screen.getByRole('button', { name: 'Switch to light theme' })).toBeOnTheScreen();
  });

  test('Log out on the Profile tab signs out', async () => {
    const { onSignOut } = await renderShell();
    await fireEvent.press(tab('Profile'));

    await fireEvent.press(screen.getByRole('button', { name: 'Log out' }));

    expect(onSignOut).toHaveBeenCalledTimes(1);
  });

  test("Android's back button goes to Home from another tab, and leaves the app from Home", async () => {
    const { pressBack } = await renderShell();

    // on Home nothing consumes it: the system leaves the app
    expect(await pressBack()).toBe(false);

    await fireEvent.press(tab('Progress'));
    expect(await pressBack()).toBe(true);
    expect(tab('Home')).toBeSelected();
    expect(screen.getByTestId('home-screen')).toBeOnTheScreen();

    expect(await pressBack()).toBe(false);
  });

  test('stops listening for the back button when it goes away', async () => {
    const { unmount, pressBack } = await renderShell();
    await fireEvent.press(tab('AI Coach'));

    await unmount();

    expect(await pressBack()).toBe(false);
  });
});

describe('Workouts and Nutrition & recovery: screens kept, now reached from Home and Discover', () => {
  test.each([
    [/^Lower Body Strength, Strength\./, 'workouts', 'Workouts'],
    [/^Mobility Reset, Mobility\./, 'workouts', 'Workouts'],
    ['View Plan. See your workouts', 'workouts', 'Workouts'],
    ['Upper Body Strength. Completed • Yesterday', 'workouts', 'Workouts'],
    ['Log Meal. Track your nutrition', 'nutrition', 'Nutrition & recovery'],
    ["Nutrition: 1,850 kcal, Today's target, 60%", 'nutrition', 'Nutrition & recovery'],
  ] as const)('%s opens the %s screen over the tabs, and Back returns to Home', async (name, section, title) => {
    await renderShell();

    await fireEvent.press(screen.getByRole('button', { name }));

    expect(screen.getByTestId(`${section}-placeholder`)).toBeOnTheScreen();
    screen.getByRole('header', { name: title });
    screen.getByText('Not designed yet');
    expect(screen.queryByTestId('bottom-tab-bar')).toBeNull();
    expect(screen.queryByTestId('home-screen')).toBeNull();

    await fireEvent.press(screen.getByRole('button', { name: 'Back' }));
    expect(screen.queryByTestId(`${section}-placeholder`)).toBeNull();
    expect(screen.getByTestId('home-screen')).toBeOnTheScreen();
    expect(tab('Home')).toBeSelected();
  });

  test('"See all" on recent activity opens Workouts too', async () => {
    await renderShell();

    await fireEvent.press(screen.getByRole('link', { name: 'See all recent activity' }));

    expect(screen.getByTestId('workouts-placeholder')).toBeOnTheScreen();
  });

  test.each([
    ['Workouts', 'workouts', 'Workouts'],
    ['Exercises', 'exercises', 'Exercises'],
    ['Mobility', 'mobility', 'Mobility'],
    ['Recovery', 'nutrition', 'Nutrition & recovery'],
  ] as const)("Discover's %s card opens %s over the tabs, and Back returns to Discover", async (area, section, title) => {
    await renderShell();
    await fireEvent.press(tab('Discover'));

    await fireEvent.press(screen.getByRole('button', { name: new RegExp(`^${area}\\.`) }));

    expect(screen.getByTestId(`${section}-placeholder`)).toBeOnTheScreen();
    screen.getByRole('header', { name: title });
    expect(screen.queryByTestId('bottom-tab-bar')).toBeNull();

    await fireEvent.press(screen.getByRole('button', { name: 'Back' }));
    expect(screen.getByTestId('discover-screen')).toBeOnTheScreen();
    expect(tab('Discover')).toBeSelected();
  });

  test("Android's back button closes the screen first, then goes Home from Discover, then leaves the app", async () => {
    const { pressBack } = await renderShell();
    await fireEvent.press(tab('Discover'));
    await fireEvent.press(screen.getByRole('button', { name: /^Workouts\./ }));

    expect(await pressBack()).toBe(true);
    expect(screen.getByTestId('discover-screen')).toBeOnTheScreen();
    expect(tab('Discover')).toBeSelected();

    expect(await pressBack()).toBe(true);
    expect(tab('Home')).toBeSelected();

    expect(await pressBack()).toBe(false);
  });

  test("the workout's own screen is still reached from today's card", async () => {
    await renderShell();

    await fireEvent.press(screen.getByRole('button', { name: /^Core & Abs Focus/ }));

    expect(screen.getByTestId('workout-details')).toBeOnTheScreen();
  });
});

describe('the workout screen, opened over the tabs', () => {
  const openToday = () => fireEvent.press(screen.getByRole('button', { name: /^Core & Abs Focus/ }));

  test("today's card opens its workout over the tabs, without the tab bar", async () => {
    await renderShell();

    await openToday();

    expect(screen.getByTestId('workout-details')).toBeOnTheScreen();
    screen.getByRole('header', { name: 'Core & Abs Focus' });
    expect(screen.queryByTestId('bottom-tab-bar')).toBeNull();
    expect(screen.queryByTestId('home-screen')).toBeNull();
  });

  test("the screen's Back arrow returns to Home, which is still the selected tab", async () => {
    await renderShell();
    await openToday();

    await fireEvent.press(screen.getByRole('button', { name: 'Back' }));

    expect(screen.queryByTestId('workout-details')).toBeNull();
    expect(screen.getByTestId('home-screen')).toBeOnTheScreen();
    expect(tab('Home')).toBeSelected();
  });

  test("Android's back button closes the workout first, and then leaves the app from Home", async () => {
    const { pressBack } = await renderShell();
    await openToday();

    expect(await pressBack()).toBe(true);
    expect(screen.queryByTestId('workout-details')).toBeNull();
    expect(tab('Home')).toBeSelected();

    expect(await pressBack()).toBe(false);
  });

  test('an exercise opens its own details over the workout, and each way back closes one screen', async () => {
    const { pressBack } = await renderShell();
    await openToday();

    await fireEvent.press(screen.getByRole('button', { name: /^Plank\./ }));

    expect(screen.getByTestId('exercise-details')).toBeOnTheScreen();
    screen.getByRole('header', { name: 'Plank' });
    expect(screen.queryByTestId('workout-details')).toBeNull();
    expect(screen.queryByText('Not designed yet')).toBeNull();

    // the arrow goes back to the workout, which is still there
    await fireEvent.press(screen.getByRole('button', { name: 'Back' }));
    expect(screen.queryByTestId('exercise-details')).toBeNull();
    expect(screen.getByTestId('workout-details')).toBeOnTheScreen();

    // and so does Android's button, one screen at a time
    await fireEvent.press(screen.getByRole('button', { name: /^Plank\./ }));
    expect(await pressBack()).toBe(true);
    expect(screen.getByTestId('workout-details')).toBeOnTheScreen();
    expect(await pressBack()).toBe(true);
    expect(screen.getByTestId('home-screen')).toBeOnTheScreen();
  });

  test.each([
    ['Mountain Climbers', 'Set 1 of 2', '30 seconds'],
    ['Lunges', 'Set 1 of 2', '10 reps'],
    ['Plank', 'Set 1 of 3', '30 seconds'],
    ['Hamstring Stretch', 'Set 1 of 1', '30 seconds'],
  ])('the details are those of the exercise that was pressed, and start from its own prescription: %s', async (name, setLabel, startsAt) => {
    await renderShell();
    await openToday();

    await fireEvent.press(screen.getByRole('button', { name: new RegExp(`^${name}\\.`) }));

    screen.getByRole('header', { name });
    expect(screen.getByTestId('exercise-set-label')).toHaveTextContent(setLabel);
    expect(screen.getByTestId('exercise-stepper-value')).toHaveAccessibilityValue({ text: startsAt });
  });

  test('sets marked done are kept while the app runs, and finishing them does not finish the workout', async () => {
    await renderShell();
    await openToday();
    await fireEvent.press(screen.getByRole('button', { name: /^Plank\./ }));

    await fireEvent.press(screen.getByRole('button', { name: 'Complete Set' }));
    expect(screen.getByTestId('exercise-set-label')).toHaveTextContent('Set 2 of 3');

    // away and back: the count is still there
    await fireEvent.press(screen.getByRole('button', { name: 'Back' }));
    await fireEvent.press(screen.getByRole('button', { name: /^Plank\./ }));
    expect(screen.getByTestId('exercise-set-label')).toHaveTextContent('Set 2 of 3');

    // another exercise has its own count
    await fireEvent.press(screen.getByRole('button', { name: 'Back' }));
    await fireEvent.press(screen.getByRole('button', { name: /^Lunges\./ }));
    expect(screen.getByTestId('exercise-set-label')).toHaveTextContent('Set 1 of 2');
    await fireEvent.press(screen.getByRole('button', { name: 'Back' }));

    // every set of Plank done: the exercise says so, and the workout screen is as it was, with its Start button
    await fireEvent.press(screen.getByRole('button', { name: /^Plank\./ }));
    await fireEvent.press(screen.getByRole('button', { name: 'Complete Set' }));
    await fireEvent.press(screen.getByRole('button', { name: 'Complete Set' }));
    expect(screen.getByTestId('exercise-set-label')).toHaveTextContent('All 3 sets done');
    await fireEvent.press(screen.getByRole('button', { name: 'Back to workout' }));
    expect(screen.getByTestId('workout-details')).toBeOnTheScreen();
    screen.getByRole('button', { name: 'Start Workout' });
    expect(screen.queryByText(/workout (is )?complete/i)).toBeNull();
  });

  test('"Edit with AI" opens the AI Coach tab with the workout as its context, and changes nothing', async () => {
    await renderShell();
    await openToday();

    await fireEvent.press(screen.getByRole('button', { name: 'Edit with AI' }));

    expect(screen.queryByTestId('workout-details')).toBeNull();
    expect(tab('AI Coach')).toBeSelected();
    screen.getByRole('header', { name: 'Formiq Coach' });
    const context = screen.getByTestId('coach-context');
    expect(within(context).getByText('Opened from Core & Abs Focus')).toBeOnTheScreen();
    expect(context).toHaveTextContent(/Nothing was changed or saved/);
    expect(context).toHaveTextContent(/until you approve a revised proposal/);
  });

  test("the note belongs to the conversation: back to Home and into AI Coach again, it is still there, and nothing was restarted", async () => {
    const { pressBack } = await renderShell();
    await openToday();
    await fireEvent.press(screen.getByRole('button', { name: 'Edit with AI' }));
    await fireEvent.press(screen.getByRole('button', { name: 'Keep same duration' }));

    expect(await pressBack()).toBe(true);
    expect(tab('Home')).toBeSelected();
    await fireEvent.press(tab('AI Coach'));

    expect(screen.getByTestId('coach-screen')).toBeOnTheScreen();
    expect(within(screen.getByTestId('coach-context')).getByText('Opened from Core & Abs Focus')).toBeOnTheScreen();
    expect(screen.getAllByTestId(/^message-/)).toHaveLength(4);
  });

  test('the AI Coach tab opened from the bar has no context either', async () => {
    await renderShell();

    await fireEvent.press(tab('AI Coach'));

    expect(screen.queryByTestId('coach-context')).toBeNull();
  });

  test('"Start Workout" says it is not available and starts nothing: the workout stays open', async () => {
    await renderShell();
    await openToday();

    await fireEvent.press(screen.getByRole('button', { name: 'Start Workout' }));

    within(screen.getByTestId('toast')).getByText("Starting a workout isn't available yet. Nothing was started.");
    expect(screen.getByTestId('workout-details')).toBeOnTheScreen();
  });
});

describe('the AI Coach tab: navigation and the mock conversation', () => {
  const openCoach = () => fireEvent.press(tab('AI Coach'));

  test("the screen's Back arrow goes to Home, as Android's back button does from any other tab", async () => {
    await renderShell();
    await openCoach();

    await fireEvent.press(screen.getByRole('button', { name: 'Back' }));

    expect(screen.queryByTestId('coach-screen')).toBeNull();
    expect(screen.getByTestId('home-screen')).toBeOnTheScreen();
    expect(tab('Home')).toBeSelected();
  });

  test("Android's back button goes to Home from the coach, and then leaves the app", async () => {
    const { pressBack } = await renderShell();
    await openCoach();

    expect(await pressBack()).toBe(true);
    expect(tab('Home')).toBeSelected();
    expect(screen.queryByTestId('coach-screen')).toBeNull();

    expect(await pressBack()).toBe(false);
  });

  test('the conversation is kept while the person looks at another tab: coming back finds it as it was', async () => {
    await renderShell();
    await openCoach();
    await fireEvent.press(screen.getByRole('button', { name: 'Keep same duration' }));
    expect(screen.getAllByTestId(/^message-/)).toHaveLength(4);

    await fireEvent.press(tab('Discover'));
    expect(screen.queryByTestId('coach-screen')).toBeNull();
    await openCoach();

    expect(screen.getAllByTestId(/^message-/)).toHaveLength(4);
    expect(screen.getByTestId('proposal-loading')).toBeOnTheScreen();
  });

  test('the coach is not mounted until it is first opened', async () => {
    await renderShell();

    expect(screen.queryByTestId('coach-screen', { includeHiddenElements: true })).toBeNull();
    await openCoach();
    expect(screen.getByTestId('coach-screen')).toBeOnTheScreen();
  });

  test('"Edit with AI" opens the same conversation: the example one, with the note above it', async () => {
    await renderShell();
    await fireEvent.press(screen.getByRole('button', { name: /^Core & Abs Focus/ }));
    await fireEvent.press(screen.getByRole('button', { name: 'Edit with AI' }));

    expect(screen.getAllByTestId(/^message-/)).toHaveLength(3);
    screen.getByRole('button', { name: 'Try different length' });
    screen.getByLabelText('Message');
  });

  test('the coach\'s menu opens the page of every card state over the tabs, and Back returns to the same conversation', async () => {
    await renderShell();
    await openCoach();
    await fireEvent.press(screen.getByRole('button', { name: 'Keep same duration' }));
    expect(screen.getAllByTestId(/^message-/)).toHaveLength(4);

    await fireEvent.press(screen.getByRole('button', { name: 'More options' }));
    await fireEvent.press(screen.getByRole('menuitem', { name: 'Preview card states' }));

    expect(screen.getByTestId('coach-card-preview')).toBeOnTheScreen();
    screen.getByRole('header', { name: 'Workout card states' });
    expect(screen.queryByTestId('bottom-tab-bar')).toBeNull();
    expect(screen.queryByTestId('coach-screen')).toBeNull();

    await fireEvent.press(screen.getByRole('button', { name: 'Back' }));
    expect(screen.queryByTestId('coach-card-preview')).toBeNull();
    expect(tab('AI Coach')).toBeSelected();
    // the conversation was only hidden under the page: it is as it was left
    expect(screen.getAllByTestId(/^message-/)).toHaveLength(4);
  });

  test("Android's back button closes the preview page first, then goes Home from the coach", async () => {
    const { pressBack } = await renderShell();
    await openCoach();
    await fireEvent.press(screen.getByRole('button', { name: 'More options' }));
    await fireEvent.press(screen.getByRole('menuitem', { name: 'Preview card states' }));

    expect(await pressBack()).toBe(true);
    expect(screen.getByTestId('coach-screen')).toBeOnTheScreen();
    expect(tab('AI Coach')).toBeSelected();

    expect(await pressBack()).toBe(true);
    expect(tab('Home')).toBeSelected();
  });

  test('talking to the coach calls no endpoint: the only requests are the Home reads that came before', async () => {
    await renderShell();
    const before = backend.requests.length;
    await openCoach();

    await fireEvent.press(screen.getByRole('button', { name: 'Keep same duration' }));
    await fireEvent.changeText(screen.getByLabelText('Message'), 'hello');
    await fireEvent.press(screen.getByRole('button', { name: 'Send message' }));

    expect(backend.requests).toHaveLength(before);
    expect(backend.requests.some((request) => /coach|proposal|approve/.test(request.path))).toBe(false);
  });
});

describe('the bottom tab bar', () => {
  const HIDDEN = { includeHiddenElements: true };
  // each tab's glyph while it is not current, and while it is
  const ICONS = [
    ['Home', 'home-outline', 'home'],
    ['Discover', 'compass-outline', 'compass'],
    ['AI Coach', 'chat-processing-outline', 'chat-processing'],
    ['Progress', 'chart-bar', 'chart-bar'],
    ['Profile', 'account-outline', 'account'],
  ] as const;

  test.each(ICONS)('%s has one icon, above its label', async (name, outline) => {
    await renderShell();

    const node = tab(name);
    // one icon and one label, the icon first, stacked in a column: the icon is above the words
    expect(within(node).getAllByTestId(/^icon-/, HIDDEN)).toHaveLength(1);
    expect(within(node).getAllByText(name)).toHaveLength(1);
    expect(node).not.toHaveStyle({ flexDirection: 'row' });
    expect(node).toHaveStyle({ alignItems: 'center', justifyContent: 'center' });
    // the bar opens on Home, so every other tab shows its outline glyph
    if (name !== 'Home') expect(within(node).getByTestId(`icon-${outline}`, HIDDEN)).toBeOnTheScreen();
  });

  test('the five tabs share the width evenly', async () => {
    await renderShell();

    for (const node of screen.getAllByRole('tab')) expect(node).toHaveStyle({ flex: 1 });
    expect(screen.getAllByRole('tab')).toHaveLength(5);
  });

  test.each(ICONS)('%s: filled and emerald when current, outlined and muted when not', async (name, outline, filled) => {
    await renderShell();
    if (name !== 'Home') await fireEvent.press(tab(name));

    const node = tab(name);
    expect(node).toBeSelected();
    expect(within(node).getByTestId(`icon-${filled}`, HIDDEN)).toBeOnTheScreen();
    if (outline !== filled) expect(within(node).queryByTestId(`icon-${outline}`, HIDDEN)).toBeNull();
    expect(within(node).getByText(name)).toHaveStyle({ color: dark.accent, fontWeight: '600' });

    for (const [other] of ICONS) {
      if (other === name) continue;
      expect(tab(other)).not.toBeSelected();
      expect(within(tab(other)).getByText(other)).toHaveStyle({ color: dark.textMuted, fontWeight: '400' });
    }
  });

  test('is a fixed bar under the screens: a charcoal surface with a thin line above it, in the dark theme', async () => {
    await renderShell();

    expect(screen.getByTestId('bottom-tab-bar')).toHaveStyle({
      flexDirection: 'row',
      backgroundColor: dark.surface,
      borderTopColor: dark.border,
      borderTopWidth: 1,
    });
  });

  test('follows the theme: the light surface, line and emerald in the light theme', async () => {
    await renderShell('light');

    expect(screen.getByTestId('bottom-tab-bar')).toHaveStyle({
      backgroundColor: light.surface,
      borderTopColor: light.border,
      borderTopWidth: 1,
    });
    expect(screen.getByText('Home')).toHaveStyle({ color: light.accent });
    expect(screen.getByText('Discover')).toHaveStyle({ color: light.textMuted });

    await fireEvent.press(tab('Profile'));
    expect(within(tab('Profile')).getByText('Profile')).toHaveStyle({ color: light.accent });
    expect(within(tab('Home')).getByText('Home')).toHaveStyle({ color: light.textMuted });
  });

  test('every tab is at least a touch target tall and a larger font setting may grow its name only a little', async () => {
    await renderShell();

    for (const node of screen.getAllByRole('tab')) expect(node).toHaveStyle({ minHeight: 64 });
    // "AI Coach" is the longest name: it stays on one line
    expect(screen.getByText('AI Coach')).toHaveProp('maxFontSizeMultiplier', 1.2);
    expect(screen.getByText('AI Coach')).toHaveProp('numberOfLines', 1);
  });

  test('has no badge, glow or gradient: a plain bar', async () => {
    await renderShell();

    const bar = within(screen.getByTestId('bottom-tab-bar'));
    expect(screen.getByTestId('bottom-tab-bar')).not.toHaveStyle({ backgroundImage: expect.anything() });
    // (Home's bell has its own red dot; the bar has none)
    expect(bar.queryByTestId('unread-dot', HIDDEN)).toBeNull();
    expect(bar.queryByText(/^\d+$/)).toBeNull();
  });
});

describe('the bottom tab bar and the safe areas', () => {
  const metrics = {
    frame: { x: 0, y: 0, width: 360, height: 800 },
    insets: { top: 40, bottom: 24, left: 8, right: 6 },
  };

  test("the gesture bar's inset belongs to the bar, and the sides keep it clear of a notch", async () => {
    await render(
      <SafeAreaProvider initialMetrics={metrics}>
        <ThemeProvider>
          <AppShell session={SESSION} onSignOut={jest.fn()} />
        </ThemeProvider>
      </SafeAreaProvider>,
    );

    expect(screen.getByTestId('bottom-tab-bar')).toHaveStyle({ paddingBottom: 24, paddingLeft: 8, paddingRight: 6 });
  });
});

describe('changing the equipment from the Profile tab', () => {
  const PROFILE = `/users/${SESSION.userId}/profile`;
  const CATALOG = [
    { id: 1, name: 'Dumbbell', description: null, is_active: true },
    { id: 2, name: 'Bench', description: null, is_active: true },
    { id: 3, name: 'Kettlebell', description: null, is_active: true },
  ];
  const piece = (id: number) => ({ id, name: CATALOG.find((item) => item.id === id)!.name });
  const profileWith = (ids: number[], noEquipment = false) => ({
    status: 200,
    body: { no_equipment: noEquipment, equipment: ids.map(piece) },
  });
  const patches = () => backend.requests.filter((request) => request.method === 'PATCH');
  const card = () => screen.getByTestId('profile-equipment');
  const hold = () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    return { release, wait: () => gate };
  };

  beforeEach(() => {
    backend.on('GET', '/equipment', { status: 200, body: CATALOG });
  });

  // opens the Profile tab on the saved equipment (Dumbbell, Bench), then the editor
  async function openEditor() {
    const view = await renderShell();
    await fireEvent.press(tab('Profile'));
    await screen.findByText('Dumbbell, Bench');
    await fireEvent.press(screen.getByRole('link', { name: 'Edit equipment' }));
    await screen.findByRole('checkbox', { name: 'Dumbbell' });
    return view;
  }

  test('"Edit" opens the editor over the tabs, started from the saved equipment', async () => {
    await openEditor();

    expect(screen.getByTestId('route-equipment-edit')).toBeOnTheScreen();
    expect(screen.getByTestId('app-shell-tabs', HIDDEN)).toHaveStyle({ display: 'none' });
    screen.getByRole('header', { name: 'Edit equipment' });
    expect(screen.getByRole('checkbox', { name: 'Dumbbell' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Bench' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Kettlebell' })).not.toBeChecked();
    expect(patches()).toHaveLength(0);
  });

  test('Save sends the change with the token, and the Profile tab shows what the backend answered, before it reads again', async () => {
    const reread = hold();
    // the read when the Profile tab regains focus is held: what shows meanwhile is the save's own answer
    backend.on('GET', PROFILE, async () => {
      await reread.wait();
      return profileWith([1, 3]);
    });
    // the backend kept Kettlebell and, on its own, dropped Bench: that is what counts
    backend.on('PATCH', PROFILE, profileWith([1, 3]));
    await openEditor();
    await fireEvent.press(screen.getByRole('checkbox', { name: 'Kettlebell' }));

    await fireEvent.press(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(screen.queryByTestId('route-equipment-edit')).toBeNull());
    expect(patches()).toHaveLength(1);
    expect(patches()[0].path).toBe(PROFILE);
    expect(patches()[0].headers.Authorization).toBe(`Bearer ${SESSION.token}`);
    expect(patches()[0].body).toEqual({ equipment_ids: [1, 2, 3], no_equipment: false });
    expect(tab('Profile')).toBeSelected();
    expect(card()).toHaveAccessibleName('Equipment: Dumbbell, Kettlebell');
    within(card()).getByText('Dumbbell, Kettlebell');

    reread.release();
    await act(async () => undefined);
    expect(card()).toHaveAccessibleName('Equipment: Dumbbell, Kettlebell');
    expect(backend.requests.filter((r) => r.method === 'GET' && r.path === PROFILE)).toHaveLength(2);
  });

  test('saving "no equipment" shows it as that', async () => {
    backend.on('PATCH', PROFILE, profileWith([], true));
    backend.on('GET', PROFILE, profileWith([], true));
    await openEditor();
    await fireEvent.press(screen.getByRole('checkbox', { name: 'No equipment. Bodyweight only' }));

    await fireEvent.press(screen.getByRole('button', { name: 'Save' }));

    await screen.findByText('No equipment (bodyweight only)');
    expect(patches()[0].body).toEqual({ equipment_ids: [], no_equipment: true });
    expect(screen.queryByTestId('route-equipment-edit')).toBeNull();
  });

  test('a failed save keeps the editor open, and the equipment saved before stays what the Profile tab shows', async () => {
    const reread = hold();
    backend.on('PATCH', PROFILE, { status: 500 });
    backend.on('GET', PROFILE, async () => {
      await reread.wait();
      return profileWith([1, 2]);
    });
    await openEditor();
    await fireEvent.press(screen.getByRole('checkbox', { name: 'Kettlebell' }));

    await fireEvent.press(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByRole('alert')).toHaveTextContent("Something went wrong on Formiq's side. Try again.");
    expect(screen.getByTestId('route-equipment-edit')).toBeOnTheScreen();
    expect(screen.getByRole('checkbox', { name: 'Kettlebell' })).toBeChecked();

    await fireEvent.press(screen.getByRole('button', { name: 'Cancel' }));

    // the card never shows the choice that failed to save, not even while the backend is read again
    expect(screen.queryByTestId('route-equipment-edit')).toBeNull();
    expect(card()).toHaveAccessibleName('Equipment: Dumbbell, Bench');
    expect(screen.queryByText(/Kettlebell/)).toBeNull();
    reread.release();
    await act(async () => undefined);
    expect(card()).toHaveAccessibleName('Equipment: Dumbbell, Bench');
  });

  test('a save whose answer the app cannot read is not shown as saved, and the Profile tab then follows the backend', async () => {
    // the backend did save it, but its answer is unreadable: the editor says so, and the next read tells the truth
    backend.on('PATCH', PROFILE, { status: 200, body: { no_equipment: 'maybe' } });
    backend.on('GET', PROFILE, profileWith([1, 2, 3]));
    await openEditor();
    await fireEvent.press(screen.getByRole('checkbox', { name: 'Kettlebell' }));

    await fireEvent.press(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Formiq sent an answer the app could not read. Try again.');
    expect(screen.getByTestId('route-equipment-edit')).toBeOnTheScreen();

    await fireEvent.press(screen.getByRole('button', { name: 'Cancel' }));

    await waitFor(() => expect(card()).toHaveAccessibleName('Equipment: Dumbbell, Bench, Kettlebell'));
  });

  test('an unchanged choice closes the editor and asks nothing of the backend', async () => {
    await openEditor();

    await fireEvent.press(screen.getByRole('button', { name: 'Save' }));

    expect(screen.queryByTestId('route-equipment-edit')).toBeNull();
    expect(patches()).toHaveLength(0);
    expect(card()).toHaveAccessibleName('Equipment: Dumbbell, Bench');
  });

  test('Cancel and Back leave without sending anything, and the Profile tab is as it was', async () => {
    await openEditor();
    await fireEvent.press(screen.getByRole('checkbox', { name: 'Kettlebell' }));

    await fireEvent.press(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByTestId('route-equipment-edit')).toBeNull();
    expect(tab('Profile')).toBeSelected();
    expect(card()).toHaveAccessibleName('Equipment: Dumbbell, Bench');

    await fireEvent.press(screen.getByRole('link', { name: 'Edit equipment' }));
    await fireEvent.press(await screen.findByRole('checkbox', { name: 'Bench' }));
    await fireEvent.press(screen.getByRole('button', { name: 'Back' }));
    expect(screen.queryByTestId('route-equipment-edit')).toBeNull();
    expect(card()).toHaveAccessibleName('Equipment: Dumbbell, Bench');
    expect(patches()).toHaveLength(0);
  });

  test("Android's back button closes the editor without saving, and stays on the Profile tab", async () => {
    const { pressBack } = await openEditor();
    await fireEvent.press(screen.getByRole('checkbox', { name: 'Kettlebell' }));

    expect(await pressBack()).toBe(true);

    expect(screen.queryByTestId('route-equipment-edit')).toBeNull();
    expect(tab('Profile')).toBeSelected();
    expect(patches()).toHaveLength(0);
    expect(card()).toHaveAccessibleName('Equipment: Dumbbell, Bench');
  });

  test('a save still out when the back button is pressed still ends up shown, as the backend answered it', async () => {
    const saving = hold();
    backend.on('PATCH', PROFILE, async () => {
      await saving.wait();
      return profileWith([1, 2, 3]);
    });
    // the read after the editor closes comes first, and predates the save's answer
    const reread = hold();
    backend.on('GET', PROFILE, async () => {
      await reread.wait();
      return profileWith([1, 2]);
    });
    const { pressBack } = await openEditor();
    await fireEvent.press(screen.getByRole('checkbox', { name: 'Kettlebell' }));
    await fireEvent.press(screen.getByRole('button', { name: 'Save' }));

    expect(await pressBack()).toBe(true);
    expect(screen.queryByTestId('route-equipment-edit')).toBeNull();
    saving.release();
    await waitFor(() => expect(card()).toHaveAccessibleName('Equipment: Dumbbell, Bench, Kettlebell'));
    reread.release();
    await act(async () => undefined);

    expect(card()).toHaveAccessibleName('Equipment: Dumbbell, Bench, Kettlebell');
    expect(tab('Profile')).toBeSelected();
  });

  test('an expired session says so in the editor, saves nothing, and Log out is still there on the Profile tab', async () => {
    backend.on('PATCH', PROFILE, { status: 401, body: { detail: 'invalid token' } });
    const { onSignOut } = await openEditor();
    await fireEvent.press(screen.getByRole('checkbox', { name: 'Kettlebell' }));

    await fireEvent.press(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Your session has expired. Log in again.');
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    expect(patches()).toHaveLength(1);

    await fireEvent.press(screen.getByRole('button', { name: 'Cancel' }));
    expect(card()).toHaveAccessibleName('Equipment: Dumbbell, Bench');
    await fireEvent.press(screen.getByRole('button', { name: 'Log out' }));
    expect(onSignOut).toHaveBeenCalledTimes(1);
  });

  test('the editor is offered only over equipment the backend has said', async () => {
    backend.reset();
    backendWorkouts(backend, SESSION.userId, { plans: [corePlan()] });
    backend.on('GET', PROFILE, { status: 500 });
    await renderShell();

    await fireEvent.press(tab('Profile'));

    await screen.findByRole('alert');
    expect(screen.queryByRole('link', { name: 'Edit equipment' })).toBeNull();
  });
});

