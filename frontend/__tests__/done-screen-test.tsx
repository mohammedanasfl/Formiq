import { fireEvent, screen, within } from '@testing-library/react-native';

import { DoneScreen } from '../src/onboarding/screens/DoneScreen';
import { themes } from '../src/theme';
import { renderWithTheme } from '../test-utils/renderWithTheme';

const dark = themes.dark.colors;
const HIDDEN = { includeHiddenElements: true };

async function renderDone(
  props: Partial<React.ComponentProps<typeof DoneScreen>> = {},
  scheme: 'dark' | 'light' = 'dark',
) {
  const onContinue = jest.fn();
  await renderWithTheme(
    <DoneScreen alreadySaved={false} onContinue={onContinue} {...props} />,
    scheme,
  );
  return { onContinue };
}

describe('<DoneScreen /> when the backend saved the profile', () => {
  test('says so, with one check mark, and promises nothing more', async () => {
    await renderDone();

    expect(screen.getByRole('header')).toHaveTextContent('Profile saved');
    expect(screen.getAllByRole('header')).toHaveLength(1);
    screen.getByText('Your profile is saved to your Formiq account.');
    screen.getByText("Workout plans aren't in the app yet.");
    expect(within(screen.getByTestId('done-check')).getByTestId('check-mark', HIDDEN)).toBeOnTheScreen();
    expect(screen.getByTestId('done-check')).toHaveStyle({ backgroundColor: dark.primary });
    expect(screen.queryByText(/personalised|plan is ready|your plan/i)).toBeNull();
  });

  test('has no celebration: no stars, dots or halo, and no progress bar or back arrow', async () => {
    await renderDone();

    expect(screen.queryByTestId('icon-star-four-points', HIDDEN)).toBeNull();
    expect(screen.queryByTestId('done-celebration', HIDDEN)).toBeNull();
    expect(screen.queryByRole('progressbar')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Back' })).toBeNull();
    expect(screen.queryByTestId('step-top-bar')).toBeNull();
  });

  test('is centered, a result rather than a step: the words sit in the middle of the screen', async () => {
    await renderDone();

    expect(screen.getByRole('header')).toHaveStyle({ textAlign: 'center' });
    expect(screen.getByText('Your profile is saved to your Formiq account.')).toHaveStyle({ textAlign: 'center' });
    expect(screen.getByText("Workout plans aren't in the app yet.")).toHaveStyle({ textAlign: 'center' });
  });

  test('says nothing about equipment not being saved: it is saved with the profile', async () => {
    await renderDone();

    expect(screen.queryByText(/equipment/i)).toBeNull();
  });

  test('continues from a button in the footer', async () => {
    const { onContinue } = await renderDone();

    const button = within(screen.getByTestId('screen-footer')).getByRole('button', { name: 'Continue' });
    expect(button).toHaveStyle({ backgroundColor: dark.primary });
    await fireEvent.press(button);
    expect(onContinue).toHaveBeenCalledTimes(1);
  });

  test('keeps the dark look in the light theme', async () => {
    await renderDone({}, 'light');

    expect(screen.getByTestId('step-frame')).toHaveStyle({ backgroundColor: dark.background });
    expect(screen.getByRole('header')).toHaveStyle({ color: dark.textPrimary });
  });
});

describe('<DoneScreen /> when the account already had a profile', () => {
  test('says that nothing was saved, and shows no check mark', async () => {
    await renderDone({ alreadySaved: true });

    expect(screen.getByRole('header')).toHaveTextContent('You already have a profile');
    screen.getByText('Your account already had a saved profile, so the answers from this session were not saved.');
    expect(screen.queryByTestId('done-check')).toBeNull();
    expect(screen.queryByTestId('check-mark', HIDDEN)).toBeNull();
    expect(screen.queryByText('Profile saved')).toBeNull();
    expect(screen.queryByText('Your profile is saved to your Formiq account.')).toBeNull();
  });

  test('can still continue', async () => {
    const { onContinue } = await renderDone({ alreadySaved: true });

    await fireEvent.press(screen.getByRole('button', { name: 'Continue' }));

    expect(onContinue).toHaveBeenCalledTimes(1);
  });
});
