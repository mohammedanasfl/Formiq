import { fireEvent, screen, within } from '@testing-library/react-native';

import { CoachCardPreviewScreen } from '../src/mock/CoachCardPreviewScreen';
import { themes, type ThemeScheme } from '../src/theme';
import { fixClockAt } from '../test-utils/clock';
import { installMockFetch, type MockFetch } from '../test-utils/mockFetch';
import { renderWithTheme } from '../test-utils/renderWithTheme';

const NOW = new Date(2026, 9, 22, 9, 0, 0);
let clock: ReturnType<typeof fixClockAt>;
let backend: MockFetch;

beforeEach(() => {
  backend = installMockFetch();
  clock = fixClockAt(NOW);
});

afterEach(() => {
  clock.restore();
  jest.restoreAllMocks();
});

async function renderPreview(scheme: ThemeScheme = 'dark') {
  const onBack = jest.fn();
  const view = await renderWithTheme(<CoachCardPreviewScreen onBack={onBack} />, scheme);
  return { ...view, onBack };
}

// each state, by the label above it
const state = (label: string) => {
  const found = screen.getAllByTestId('preview-state').find((node) => within(node).getAllByText(/./)[0].props.children === label);
  if (!found) throw new Error(`no state "${label}"`);
  return within(found);
};

describe('<CoachCardPreviewScreen />', () => {
  test('says what it is: every state of the card, made up, with nothing sent and buttons that do nothing', async () => {
    await renderPreview();

    screen.getByRole('header', { name: 'Workout card states' });
    screen.getByText(/Nothing here is sent or saved, and the buttons do nothing on this page\./);
  });

  test('shows every state the card has, one under the other', async () => {
    await renderPreview();

    expect(screen.getAllByTestId('preview-state').map((node) => within(node).getAllByText(/./)[0].props.children)).toEqual([
      'New workout',
      'Updated workout, with Key Changes',
      'Updated workout, after "easier on my knees"',
      'Updated workout, dropping a weight',
      'Updated workout, the backend could not compare',
      'Loading proposal',
      'Applying',
      'Applied',
      'Applied, new workout',
      'Apply failed, can try again',
      'Apply failed, needs a new proposal',
      'Dismissing',
      'Dismissed',
      'Dismissed, an updated workout',
      'Dismiss failed, can try again',
      'Dismiss failed, already applied or changed',
      'No longer waiting (expired)',
      'Waiting from before, the newest',
      'Waiting from before, an older one',
      'Several workouts waiting, to choose from',
      'Looking for waiting workouts failed',
      'Proposal generation failed',
      'Older version',
      'Workout the catalog could not fully cover',
    ]);
  });

  test('draws each as the one card, in the state it names', async () => {
    await renderPreview();

    within(state('New workout').getByTestId('proposal-status')).getByText('New Workout');
    state('New workout').getByRole('button', { name: 'Apply This Workout' });

    within(state('Updated workout, with Key Changes').getByTestId('proposal-status')).getByText('Updated Workout');
    state('Updated workout, with Key Changes').getByText('Replaced Bicycle Crunches with Dead Bug');

    state('Updated workout, with Key Changes').getByText('Kept the same duration (18 min)');

    state('Updated workout, after "easier on my knees"').getByText('Replaced Lunges with Glute Bridge in the warm-up');
    // a weight the saved workout has and the proposal drops is a change like any other
    state('Updated workout, dropping a weight').getByText('Goblet Squat: 20 kg → no weight');
    state('Updated workout, the backend could not compare').getByTestId('key-changes-unavailable');

    state('Loading proposal').getByLabelText('Preparing your workout');

    state('Applying').getByRole('button', { name: 'Applying…' });
    within(state('Applied').getByTestId('proposal-status')).getByText('Applied');
    within(state('Applied, new workout').getByTestId('proposal-status')).getByText('Applied');

    state('Apply failed, can try again').getByRole('button', { name: 'Try Again' });
    expect(state('Apply failed, needs a new proposal').getByRole('button', { name: 'Apply Updated Workout' })).toBeDisabled();

    state('Dismissing').getByRole('button', { name: 'Dismissing…' });
    within(state('Dismissed').getByTestId('proposal-status')).getByText('Dismissed');
    within(state('Dismissed, an updated workout').getByTestId('proposal-status')).getByText('Dismissed');
    state('Dismiss failed, can try again').getByRole('button', { name: 'Dismiss Again' });
    state('Dismiss failed, can try again').getByTestId('dismiss-error');
    expect(state('Dismiss failed, already applied or changed').getByRole('button', { name: 'Apply Updated Workout' })).toBeDisabled();
    within(state('No longer waiting (expired)').getByTestId('proposal-status')).getByText('No longer waiting');

    // a workout that was waiting from before: when it was proposed, and (for an older one) why changes cannot be asked for
    state('Waiting from before, the newest').getByText('Proposed 5 min ago');
    state('Waiting from before, the newest').getByRole('button', { name: 'Ask for More Changes' });
    state('Waiting from before, an older one').getByText('Proposed 12 min ago');
    state('Waiting from before, an older one').getByTestId('ask-unavailable');
    expect(state('Waiting from before, an older one').queryByRole('button', { name: 'Ask for More Changes' })).toBeNull();
    state('Several workouts waiting, to choose from').getByText('2 workouts are waiting for your approval');
    expect(state('Several workouts waiting, to choose from').getAllByRole('button', { name: 'Review' })).toHaveLength(2);
    state('Looking for waiting workouts failed').getByRole('button', { name: 'Try Again' });

    within(state('Proposal generation failed').getByTestId('proposal-status')).getByText("Couldn't create the workout");
    within(state('Older version').getByTestId('proposal-status')).getByText('Older version');
    state('Workout the catalog could not fully cover').getByTestId('coverage-note');
  });

  test('the buttons do nothing here: pressing them changes no state and sends nothing', async () => {
    await renderPreview();
    const apply = state('New workout').getByRole('button', { name: 'Apply This Workout' });

    await fireEvent.press(apply);
    await fireEvent.press(state('Updated workout, with Key Changes').getByRole('button', { name: 'Ask for More Changes' }));
    await fireEvent.press(state('New workout').getByRole('button', { name: 'Dismiss' }));
    await fireEvent.press(state('Several workouts waiting, to choose from').getAllByRole('button', { name: 'Review' })[0]);
    await fireEvent.press(state('Looking for waiting workouts failed').getByRole('button', { name: 'Try Again' }));
    await fireEvent.press(state('Proposal generation failed').getByRole('button', { name: 'Try Again' }));

    within(state('New workout').getByTestId('proposal-status')).getByText('New Workout');
    expect(backend.requests).toEqual([]);
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  test('shows the cards\' days against today: scheduled for today', async () => {
    await renderPreview();

    expect(screen.getAllByText(/focus • Today/).length).toBeGreaterThan(5);
  });

  test('has a Back arrow', async () => {
    const { onBack } = await renderPreview();

    await fireEvent.press(screen.getByRole('button', { name: 'Back' }));

    expect(onBack).toHaveBeenCalledTimes(1);
  });

  test.each([
    ['dark', themes.dark.colors],
    ['light', themes.light.colors],
  ] as const)('follows the %s theme', async (scheme, colors) => {
    await renderPreview(scheme);

    expect(screen.getByTestId('coach-card-preview')).toHaveStyle({ backgroundColor: colors.background });
    expect(screen.getAllByTestId('proposal-card')[0]).toHaveStyle({ backgroundColor: colors.surface });
  });
});
