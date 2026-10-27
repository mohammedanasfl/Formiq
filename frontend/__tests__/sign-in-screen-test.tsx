import { StyleSheet } from 'react-native';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { SignInScreen } from '../src/onboarding/screens/SignInScreen';
import { SignUpScreen } from '../src/onboarding/screens/SignUpScreen';
import { ThemeProvider, themes } from '../src/theme';
import { fakeToken, installMockFetch, type MockFetch } from '../test-utils/mockFetch';
import { renderWithTheme } from '../test-utils/renderWithTheme';

const dark = themes.dark.colors;
const TOKEN = fakeToken(42);
const LOGIN = '/auth/login';
const PROFILE = '/users/42/profile';
const SIGN_UP_LINK = 'New to Formiq? Create an account';

let backend: MockFetch;

beforeEach(() => {
  backend = installMockFetch();
});

async function renderSignIn(scheme: 'dark' | 'light' = 'dark', notice?: string) {
  const onSignedIn = jest.fn();
  const onBack = jest.fn();
  const onSwitchToSignUp = jest.fn();
  await renderWithTheme(
    <SignInScreen notice={notice} onSignedIn={onSignedIn} onBack={onBack} onSwitchToSignUp={onSwitchToSignUp} />,
    scheme,
  );
  return { onSignedIn, onBack, onSwitchToSignUp };
}

const type = (label: string, text: string) => fireEvent.changeText(screen.getByLabelText(label), text);
const logIn = () => fireEvent.press(screen.getByRole('button', { name: 'Log in' }));

async function fillIn(email = 'sam@example.com', password = 'longenough') {
  await type('Email', email);
  await type('Password', password);
}

// the replies of a successful login for someone who has (or has not) a profile
function acceptLogin(profile: { status: number; body?: unknown } = { status: 200, body: {} }) {
  backend.on('POST', LOGIN, { status: 200, body: { access_token: TOKEN } });
  backend.on('GET', PROFILE, profile);
}

describe('<SignInScreen /> content', () => {
  test('has the heading, the supporting line, two fields and the actions, and nothing else', async () => {
    await renderSignIn();

    expect(screen.getByRole('header')).toHaveTextContent('Log in');
    expect(screen.getAllByRole('header')).toHaveLength(1);
    screen.getByText('Welcome back to Formiq.');
    screen.getByLabelText('Email');
    screen.getByLabelText('Password');
    screen.getByRole('button', { name: 'Log in' });
    screen.getByRole('link', { name: SIGN_UP_LINK });
    screen.getByRole('button', { name: 'Back' });
    // no social sign-in, and the only buttons are the ones above and the password toggle
    expect(screen.queryByText(/google|apple|facebook/i)).toBeNull();
    expect(screen.getAllByRole('button').map((button) => button.props.accessibilityLabel)).toEqual([
      'Back',
      'Show password',
      'Log in',
    ]);
  });

  test('draws the same small wordmark as the sign-up screen, one word for a screen reader', async () => {
    await renderSignIn();

    const wordmark = screen.getByLabelText('Formiq');
    expect(wordmark).toHaveTextContent('Formiq');
    expect(wordmark).toHaveStyle({ color: dark.textPrimary, fontWeight: '700' });
    expect(screen.getByText('iq')).toHaveStyle({ color: dark.accent, fontWeight: '700' });
    expect(StyleSheet.flatten(wordmark.props.style).fontSize).toBeLessThanOrEqual(32);
  });

  test('sits on the same gym photo as the sign-up screen, under a dark layer, hidden from screen readers', async () => {
    await renderSignIn();

    const photo = screen.getByTestId('signin-photo');
    expect(photo).toHaveProp('source', require('../assets/images/signup-background.png'));
    expect(photo).toHaveProp('resizeMode', 'cover');
    expect(photo).toHaveProp('importantForAccessibility', 'no');
    expect(photo).not.toHaveProp('accessibilityLabel');
    expect(photo).toHaveStyle({ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, width: '100%', height: '100%' });
    const scrim = screen.getByTestId('signin-photo-scrim');
    expect(scrim).toHaveStyle({ backgroundColor: dark.background });
    expect(StyleSheet.flatten(scrim.props.style).opacity).toBeGreaterThan(0);
  });

  test('keeps the dark look in the light theme', async () => {
    await renderSignIn('light');

    expect(screen.getByTestId('signin-screen')).toHaveStyle({ backgroundColor: dark.background });
    expect(screen.getByRole('header')).toHaveStyle({ color: dark.textPrimary });
    expect(screen.getByRole('button', { name: 'Log in' })).toHaveStyle({ backgroundColor: dark.primary });
    expect(screen.getByLabelText('Email')).toHaveStyle({ backgroundColor: dark.surface, color: dark.textPrimary });
  });

  test('is styled exactly like the sign-up screen: photo, layer, wordmark, heading, button and link', async () => {
    const styleOf = (element: ReturnType<typeof screen.getByTestId>) => StyleSheet.flatten(element.props.style);
    const look = (testID: string, button: string, link: string, supporting: string) => ({
      photo: styleOf(screen.getByTestId(`${testID}-photo`)),
      scrim: styleOf(screen.getByTestId(`${testID}-photo-scrim`)),
      content: styleOf(screen.getByTestId(`${testID}-content`)),
      wordmark: styleOf(screen.getByLabelText('Formiq')),
      heading: styleOf(screen.getByRole('header')),
      supporting: styleOf(screen.getByText(supporting)),
      button: styleOf(screen.getByRole('button', { name: button })),
      buttonLabel: styleOf(within(screen.getByRole('button', { name: button })).getByText(button)),
      link: styleOf(screen.getByRole('link', { name: link })),
      back: styleOf(screen.getByRole('button', { name: 'Back' })),
    });

    await renderWithTheme(
      <SignUpScreen onSignedUp={jest.fn()} onBack={jest.fn()} onSwitchToSignIn={jest.fn()} />,
    );
    const signUp = look('signup', 'Create Account', 'Already have an account? Log in', 'Start your fitness journey with Formiq.');
    await screen.unmount();

    await renderSignIn();
    const signIn = look('signin', 'Log in', SIGN_UP_LINK, 'Welcome back to Formiq.');

    expect(signIn).toEqual(signUp);
  });

  test('"Create an account" is green inside the muted sentence, and the whole line is one tappable link', async () => {
    await renderSignIn();

    const link = screen.getByRole('link', { name: SIGN_UP_LINK });
    expect(within(link).getByText('Create an account')).toHaveStyle({ color: dark.accent });
    expect(within(link).getByText(/New to Formiq\?/)).toHaveStyle({ color: dark.textSecondary });
    expect(link).toHaveStyle({ minHeight: 48 });
  });

  test('styles the primary button like the welcome screen: green, 56 dp tall, rounded', async () => {
    await renderSignIn();

    const button = screen.getByRole('button', { name: 'Log in' });
    expect(button).toHaveStyle({ backgroundColor: dark.primary, minHeight: 56, borderRadius: 16 });
    expect(within(button).getByText('Log in')).toHaveStyle({ color: dark.textOnPrimary });
  });

  test('scrolls the form and keeps the button, the message and the link in a footer above the keyboard', async () => {
    await renderSignIn();

    expect(screen.getByTestId('screen-scroll')).toHaveProp('keyboardShouldPersistTaps', 'handled');
    const footer = screen.getByTestId('screen-footer');
    expect(within(footer).getByRole('button', { name: 'Log in' })).toBeOnTheScreen();
    expect(within(footer).getByRole('link', { name: SIGN_UP_LINK })).toBeOnTheScreen();
    expect(within(screen.getByTestId('screen-scroll')).getByLabelText('Email')).toBeOnTheScreen();
  });

  test('keeps clear of the system bars', async () => {
    const insets = { top: 47, bottom: 34, left: 0, right: 0 };
    await render(
      <SafeAreaProvider initialMetrics={{ frame: { x: 0, y: 0, width: 390, height: 844 }, insets }}>
        <ThemeProvider>
          <SignInScreen onSignedIn={jest.fn()} onBack={jest.fn()} onSwitchToSignUp={jest.fn()} />
        </ThemeProvider>
      </SafeAreaProvider>,
    );

    expect(screen.getByTestId('signin-content')).toHaveStyle({
      paddingTop: insets.top,
      paddingBottom: insets.bottom,
    });
  });

  test('tells first what it was given to tell, such as an expired session, above the fields', async () => {
    await renderSignIn('dark', 'Your session expired, so nothing was saved. Log in again: your answers are kept.');

    const notice = screen.getByText('Your session expired, so nothing was saved. Log in again: your answers are kept.');
    expect(within(screen.getByTestId('screen-scroll')).getByText(/Your session expired/)).toBe(notice);
    expect(screen.queryByRole('alert')).toBeNull(); // information, not an error
  });

  test('has no notice when there is nothing to tell', async () => {
    await renderSignIn();

    expect(screen.queryByText(/session expired/)).toBeNull();
  });
});

describe('<SignInScreen /> fields', () => {
  test('the email field asks for the email keyboard and does not capitalise or correct', async () => {
    await renderSignIn();

    const email = screen.getByLabelText('Email');
    expect(email).toHaveProp('keyboardType', 'email-address');
    expect(email).toHaveProp('autoCapitalize', 'none');
    expect(email).toHaveProp('autoCorrect', false);
    expect(email).toHaveProp('autoComplete', 'email');
    expect(email).toHaveProp('textContentType', 'emailAddress');
    expect(email).toHaveProp('returnKeyType', 'next');
    expect(email).toHaveProp('submitBehavior', 'submit');
  });

  test('the password is hidden until asked, offered to a password manager as an existing one, with no rule shown', async () => {
    await renderSignIn();

    const password = screen.getByLabelText('Password');
    expect(password).toHaveProp('secureTextEntry', true);
    expect(password).toHaveProp('autoComplete', 'current-password');
    expect(password).toHaveProp('textContentType', 'password');
    expect(screen.queryByText('At least 8 characters.')).toBeNull();

    await fireEvent.press(screen.getByRole('button', { name: 'Show password' }));
    expect(screen.getByLabelText('Password')).toHaveProp('secureTextEntry', false);
    await fireEvent.press(screen.getByRole('button', { name: 'Hide password' }));
    expect(screen.getByLabelText('Password')).toHaveProp('secureTextEntry', true);
  });
});

describe('<SignInScreen /> validation', () => {
  test('asks for both fields, inline, and sends nothing', async () => {
    await renderSignIn();

    await logIn();

    screen.getByText('Enter your email address.');
    screen.getByText('Enter your password.');
    expect(screen.getAllByRole('alert')).toHaveLength(2);
    expect(backend.requests).toHaveLength(0);
  });

  test('updates as the fields are filled in', async () => {
    await renderSignIn();
    await logIn();

    await type('Email', 'sam@example.com');
    expect(screen.queryByText('Enter your email address.')).toBeNull();
    screen.getByText('Enter your password.');
  });
});

describe('<SignInScreen /> logging in', () => {
  test('sends the email (trimmed) and the password (exactly as typed) to POST /auth/login, then asks for the profile with the token', async () => {
    acceptLogin();
    const { onSignedIn } = await renderSignIn();
    await fillIn('  sam@example.com  ', '  spaces kept  ');

    await logIn();

    await waitFor(() => expect(onSignedIn).toHaveBeenCalledTimes(1));
    expect(backend.requests).toHaveLength(2);
    expect(backend.requests[0]).toMatchObject({
      method: 'POST',
      path: LOGIN,
      body: { email: 'sam@example.com', password: '  spaces kept  ' },
    });
    expect(backend.requests[0].headers.Authorization).toBeUndefined();
    expect(backend.requests[1]).toMatchObject({ method: 'GET', path: PROFILE });
    expect(backend.requests[1].headers.Authorization).toBe(`Bearer ${TOKEN}`);
  });

  test.each([
    ['has a profile', { status: 200, body: {} }, true],
    ['has no profile yet', { status: 404, body: { detail: 'no profile found' } }, false],
  ])('moves on only after both answers, telling whether the person %s', async (_name, profile, profileExists) => {
    let release: () => void = () => undefined;
    const answered = new Promise<void>((resolve) => (release = resolve));
    backend.on('POST', LOGIN, async () => {
      await answered;
      return { status: 200, body: { access_token: TOKEN } };
    });
    backend.on('GET', PROFILE, profile);
    const { onSignedIn } = await renderSignIn();
    await fillIn();

    const pressed = logIn();
    await screen.findByRole('button', { name: 'Logging in…' });
    expect(onSignedIn).not.toHaveBeenCalled();

    await act(async () => {
      release();
      await answered;
    });
    await pressed;
    await waitFor(() => expect(onSignedIn).toHaveBeenCalledTimes(1));
    expect(onSignedIn).toHaveBeenCalledWith({ token: TOKEN, userId: 42 }, profileExists);
  });

  test('shows progress, turns every way out off, and never logs in twice', async () => {
    let release: () => void = () => undefined;
    const answered = new Promise<void>((resolve) => (release = resolve));
    backend.on('POST', LOGIN, async () => {
      await answered;
      return { status: 200, body: { access_token: TOKEN } };
    });
    backend.on('GET', PROFILE, { status: 200, body: {} });
    const { onSignedIn, onBack, onSwitchToSignUp } = await renderSignIn();
    await fillIn();

    // "done" on the keyboard twice in the same instant: before the screen has re-rendered, so only
    // the guard inside the handler can stop the second one
    const password = screen.getByLabelText('Password');
    await act(async () => {
      password.props.onSubmitEditing();
      password.props.onSubmitEditing();
    });
    await screen.findByRole('button', { name: 'Logging in…' });
    expect(backend.requests).toHaveLength(1);

    expect(screen.getByRole('button', { name: 'Logging in…' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Back' })).toBeDisabled();
    expect(screen.getByRole('link', { name: SIGN_UP_LINK })).toBeDisabled();
    await fireEvent.press(screen.getByRole('button', { name: 'Logging in…' }));
    await fireEvent.press(screen.getByRole('button', { name: 'Back' }));
    await fireEvent.press(screen.getByRole('link', { name: SIGN_UP_LINK }));
    expect(onBack).not.toHaveBeenCalled();
    expect(onSwitchToSignUp).not.toHaveBeenCalled();

    await act(async () => {
      release();
      await answered;
    });
    await waitFor(() => expect(onSignedIn).toHaveBeenCalledTimes(1));
    expect(backend.requests.filter((request) => request.path === LOGIN)).toHaveLength(1);
  });

  test.each([
    ['a wrong email or password', { status: 401, body: { detail: 'invalid email or password' } }, 'Incorrect email or password.'],
    ['no connection', 'network-error' as const, "Can't reach Formiq. Check your connection and try again."],
    ['a server error', { status: 500 }, "Something went wrong on Formiq's side. Try again."],
    ['an answer without a token', { status: 200, body: {} }, 'Formiq sent an answer the app could not read. Try again.'],
  ])('%s: says so in the footer, stays here, goes nowhere and keeps what was typed', async (_name, reply, message) => {
    backend.on('POST', LOGIN, reply);
    const { onSignedIn } = await renderSignIn();
    await fillIn();

    await logIn();

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(message);
    expect(within(screen.getByTestId('screen-footer')).getByRole('alert')).toBe(alert);
    expect(onSignedIn).not.toHaveBeenCalled();
    expect(backend.requests.filter((request) => request.method === 'GET')).toHaveLength(0);
    expect(screen.getByRole('button', { name: 'Log in' })).toBeEnabled();
    expect(screen.getByLabelText('Email')).toHaveDisplayValue('sam@example.com');
    expect(screen.getByLabelText('Password')).toHaveDisplayValue('longenough');
  });

  test('logged in but unable to check the profile: says so, goes nowhere, and can retry', async () => {
    backend.on('POST', LOGIN, { status: 200, body: { access_token: TOKEN } });
    backend.on('GET', PROFILE, { status: 500 });
    backend.on('GET', PROFILE, { status: 404, body: { detail: 'no profile found' } });
    const { onSignedIn } = await renderSignIn();
    await fillIn();

    await logIn();

    await screen.findByText("Something went wrong on Formiq's side. Try again.");
    expect(onSignedIn).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Log in' })).toBeEnabled();

    await logIn();
    await waitFor(() => expect(onSignedIn).toHaveBeenCalledTimes(1));
    expect(onSignedIn).toHaveBeenCalledWith({ token: TOKEN, userId: 42 }, false);
    expect(screen.queryByText("Something went wrong on Formiq's side. Try again.")).toBeNull();
  });
});

describe('<SignInScreen /> moving around', () => {
  test('"Create an account" opens the sign-up screen and Back goes back, without any request', async () => {
    const { onBack, onSwitchToSignUp } = await renderSignIn();

    await fireEvent.press(screen.getByRole('link', { name: SIGN_UP_LINK }));
    expect(onSwitchToSignUp).toHaveBeenCalledTimes(1);

    await fireEvent.press(screen.getByRole('button', { name: 'Back' }));
    expect(onBack).toHaveBeenCalledTimes(1);
    expect(backend.requests).toHaveLength(0);
  });

  test('"done" on the password keyboard logs in', async () => {
    acceptLogin();
    const { onSignedIn } = await renderSignIn();
    await fillIn();

    await fireEvent(screen.getByLabelText('Password'), 'submitEditing');

    await waitFor(() => expect(onSignedIn).toHaveBeenCalledTimes(1));
  });
});
