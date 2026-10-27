import { StyleSheet } from 'react-native';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { SignUpScreen } from '../src/onboarding/screens/SignUpScreen';
import { ThemeProvider, themes } from '../src/theme';
import { fakeToken, installMockFetch, type MockFetch } from '../test-utils/mockFetch';
import { renderWithTheme } from '../test-utils/renderWithTheme';

const dark = themes.dark.colors;
const TOKEN = fakeToken(42);
const REGISTER = '/auth/register';

let backend: MockFetch;

beforeEach(() => {
  backend = installMockFetch();
});

async function renderSignUp(scheme: 'dark' | 'light' = 'dark') {
  const onSignedUp = jest.fn();
  const onBack = jest.fn();
  const onSwitchToSignIn = jest.fn();
  await renderWithTheme(
    <SignUpScreen onSignedUp={onSignedUp} onBack={onBack} onSwitchToSignIn={onSwitchToSignIn} />,
    scheme,
  );
  return { onSignedUp, onBack, onSwitchToSignIn };
}

const type = (label: string, text: string) => fireEvent.changeText(screen.getByLabelText(label), text);
const createAccount = () => fireEvent.press(screen.getByRole('button', { name: 'Create Account' }));

async function fillIn(email = 'sam@example.com', password = 'longenough') {
  await type('Email', email);
  await type('Password', password);
}

describe('<SignUpScreen /> content', () => {
  test('has the heading, the supporting line, two fields and the actions, and nothing else', async () => {
    await renderSignUp();

    expect(screen.getByRole('header')).toHaveTextContent('Create Account');
    expect(screen.getAllByRole('header')).toHaveLength(1);
    screen.getByText('Start your fitness journey with Formiq.');
    screen.getByLabelText('Email');
    screen.getByLabelText('Password');
    screen.getByRole('button', { name: 'Create Account' });
    screen.getByRole('link', { name: 'Already have an account? Log in' });
    screen.getByRole('button', { name: 'Back' });
    // no social sign-in, and the only buttons are the ones above and the password toggle
    expect(screen.queryByText(/google|apple|facebook/i)).toBeNull();
    expect(screen.getAllByRole('button').map((button) => button.props.accessibilityLabel)).toEqual([
      'Back',
      'Show password',
      'Create Account',
    ]);
  });

  test('draws a small wordmark as text: "Form" white, "iq" green, one word for a screen reader', async () => {
    await renderSignUp();

    const wordmark = screen.getByLabelText('Formiq');
    expect(wordmark).toHaveTextContent('Formiq');
    expect(wordmark).toHaveStyle({ color: dark.textPrimary, fontWeight: '700' });
    expect(screen.getByText('iq')).toHaveStyle({ color: dark.accent, fontWeight: '700' });
    // small: well under the welcome screen's
    expect(StyleSheet.flatten(wordmark.props.style).fontSize).toBeLessThanOrEqual(32);
  });

  test('sits on the gym photo under a dark layer, and the photo is hidden from screen readers', async () => {
    await renderSignUp();

    const photo = screen.getByTestId('signup-photo');
    expect(photo).toHaveProp('source', require('../assets/images/signup-background.png'));
    expect(photo).toHaveProp('resizeMode', 'cover');
    expect(photo).toHaveProp('importantForAccessibility', 'no');
    expect(photo).not.toHaveProp('accessibilityLabel');
    expect(photo).toHaveStyle({ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, width: '100%', height: '100%' });
    const scrim = screen.getByTestId('signup-photo-scrim');
    expect(scrim).toHaveStyle({ backgroundColor: dark.background });
    expect(StyleSheet.flatten(scrim.props.style).opacity).toBeGreaterThan(0);
  });

  test('keeps the dark look in the light theme', async () => {
    await renderSignUp('light');

    expect(screen.getByTestId('signup-screen')).toHaveStyle({ backgroundColor: dark.background });
    expect(screen.getByRole('header')).toHaveStyle({ color: dark.textPrimary });
    expect(screen.getByRole('button', { name: 'Create Account' })).toHaveStyle({ backgroundColor: dark.primary });
  });

  test('styles the primary button like the welcome screen: green, 56 dp tall, rounded', async () => {
    await renderSignUp();

    const button = screen.getByRole('button', { name: 'Create Account' });
    expect(button).toHaveStyle({ backgroundColor: dark.primary, minHeight: 56, borderRadius: 16 });
    expect(within(button).getByText('Create Account')).toHaveStyle({ color: dark.textOnPrimary });
  });

  test('"Log in" is green inside the muted sentence, and the whole line is one tappable link', async () => {
    await renderSignUp();

    const link = screen.getByRole('link', { name: 'Already have an account? Log in' });
    expect(within(link).getByText('Log in')).toHaveStyle({ color: dark.accent });
    expect(link).toHaveStyle({ minHeight: 48 });
  });

  test('scrolls the form and keeps the button and the link in a footer above the keyboard', async () => {
    await renderSignUp();

    expect(screen.getByTestId('screen-scroll')).toHaveProp('keyboardShouldPersistTaps', 'handled');
    const footer = screen.getByTestId('screen-footer');
    expect(within(footer).getByRole('button', { name: 'Create Account' })).toBeOnTheScreen();
    expect(within(footer).getByRole('link', { name: 'Already have an account? Log in' })).toBeOnTheScreen();
    expect(within(screen.getByTestId('screen-scroll')).getByLabelText('Email')).toBeOnTheScreen();
  });

  test('keeps clear of the system bars', async () => {
    const insets = { top: 47, bottom: 34, left: 0, right: 0 };
    await render(
      <SafeAreaProvider initialMetrics={{ frame: { x: 0, y: 0, width: 390, height: 844 }, insets }}>
        <ThemeProvider>
          <SignUpScreen onSignedUp={jest.fn()} onBack={jest.fn()} onSwitchToSignIn={jest.fn()} />
        </ThemeProvider>
      </SafeAreaProvider>,
    );

    expect(screen.getByTestId('signup-content')).toHaveStyle({
      paddingTop: insets.top,
      paddingBottom: insets.bottom,
    });
  });
});

describe('<SignUpScreen /> fields', () => {
  test('the email field asks for the email keyboard and does not capitalise or correct', async () => {
    await renderSignUp();

    const email = screen.getByLabelText('Email');
    expect(email).toHaveProp('keyboardType', 'email-address');
    expect(email).toHaveProp('autoCapitalize', 'none');
    expect(email).toHaveProp('autoCorrect', false);
    expect(email).toHaveProp('autoComplete', 'email');
    expect(email).toHaveProp('textContentType', 'emailAddress');
    expect(email).toHaveProp('returnKeyType', 'next');
  });

  test('the password is hidden until asked, and the toggle says what it will do', async () => {
    await renderSignUp();

    expect(screen.getByLabelText('Password')).toHaveProp('secureTextEntry', true);
    expect(screen.getByLabelText('Password')).toHaveProp('autoComplete', 'new-password');
    screen.getByText('At least 8 characters.');

    await fireEvent.press(screen.getByRole('button', { name: 'Show password' }));
    expect(screen.getByLabelText('Password')).toHaveProp('secureTextEntry', false);
    await fireEvent.press(screen.getByRole('button', { name: 'Hide password' }));
    expect(screen.getByLabelText('Password')).toHaveProp('secureTextEntry', true);
  });
});

describe('<SignUpScreen /> validation', () => {
  test('asks for both fields, inline, and sends nothing', async () => {
    await renderSignUp();

    await createAccount();

    screen.getByText('Enter your email address.');
    screen.getByText('Enter your password.');
    expect(screen.getAllByRole('alert')).toHaveLength(2);
    expect(backend.requests).toHaveLength(0);
  });

  test('explains a malformed email and a short password, and updates as they are fixed', async () => {
    await renderSignUp();
    await fillIn('not-an-email', 'short');

    await createAccount();
    screen.getByText('Enter a valid email address.');
    screen.getByText('Use at least 8 characters.');
    expect(backend.requests).toHaveLength(0);

    await type('Email', 'sam@example.com');
    expect(screen.queryByText('Enter a valid email address.')).toBeNull();
    screen.getByText('Use at least 8 characters.');
  });

  test('a password of only spaces is still a password, but one under 8 characters is not', async () => {
    await renderSignUp();
    await fillIn('sam@example.com', '       ');

    await createAccount();

    screen.getByText('Use at least 8 characters.');
    expect(backend.requests).toHaveLength(0);
  });
});

describe('<SignUpScreen /> registering', () => {
  test('sends the email (trimmed) and the password (exactly as typed) to POST /auth/register, and nothing else', async () => {
    backend.on('POST', REGISTER, { status: 201, body: { access_token: TOKEN, token_type: 'bearer' } });
    await renderSignUp();
    await fillIn('  sam@example.com  ', '  spaces kept  ');

    await createAccount();

    await screen.findByRole('button', { name: 'Create Account' });
    expect(backend.requests).toHaveLength(1);
    const [request] = backend.requests;
    expect(request.method).toBe('POST');
    expect(request.path).toBe(REGISTER);
    expect(request.body).toEqual({ email: 'sam@example.com', password: '  spaces kept  ' });
    expect(request.headers.Authorization).toBeUndefined();
  });

  test('moves on only after the backend has said yes, with the session it issued', async () => {
    let release: () => void = () => undefined;
    const answered = new Promise<void>((resolve) => (release = resolve));
    backend.on('POST', REGISTER, async () => {
      await answered;
      return { status: 201, body: { access_token: TOKEN, token_type: 'bearer' } };
    });
    const { onSignedUp } = await renderSignUp();
    await fillIn();

    const pressed = createAccount();
    await screen.findByRole('button', { name: 'Creating account…' });
    expect(onSignedUp).not.toHaveBeenCalled();

    await act(async () => {
      release();
      await answered;
    });
    await pressed;
    await waitFor(() => expect(onSignedUp).toHaveBeenCalledTimes(1));
    expect(onSignedUp).toHaveBeenCalledWith({ token: TOKEN, userId: 42 });
  });

  test('shows progress, turns every way out off, and never sends twice', async () => {
    let release: () => void = () => undefined;
    const answered = new Promise<void>((resolve) => (release = resolve));
    backend.on('POST', REGISTER, async () => {
      await answered;
      return { status: 201, body: { access_token: TOKEN } };
    });
    const { onSignedUp, onBack, onSwitchToSignIn } = await renderSignUp();
    await fillIn();

    // "done" on the keyboard twice in the same instant: before the screen has re-rendered, so only
    // the guard inside the handler can stop the second one
    const password = screen.getByLabelText('Password');
    await act(async () => {
      password.props.onSubmitEditing();
      password.props.onSubmitEditing();
    });
    await screen.findByRole('button', { name: 'Creating account…' });
    expect(backend.requests).toHaveLength(1);

    expect(screen.getByRole('button', { name: 'Creating account…' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Back' })).toBeDisabled();
    expect(screen.getByRole('link', { name: 'Already have an account? Log in' })).toBeDisabled();
    await fireEvent.press(screen.getByRole('button', { name: 'Creating account…' }));
    await fireEvent.press(screen.getByRole('button', { name: 'Back' }));
    await fireEvent.press(screen.getByRole('link', { name: 'Already have an account? Log in' }));
    expect(onBack).not.toHaveBeenCalled();
    expect(onSwitchToSignIn).not.toHaveBeenCalled();

    await act(async () => {
      release();
      await answered;
    });
    await waitFor(() => expect(onSignedUp).toHaveBeenCalledTimes(1));
    expect(backend.requests).toHaveLength(1);
  });

  test.each([
    ['an email that already has an account', { status: 409, body: { detail: 'an account with this email already exists' } }, 'An account with this email already exists. Log in instead.'],
    ['a rejected request', { status: 422, body: { detail: [{ msg: 'bad' }] } }, 'Enter a valid email address and a password of at least 8 characters.'],
    ['no connection', 'network-error' as const, "Can't reach Formiq. Check your connection and try again."],
    ['a server error', { status: 500 }, "Something went wrong on Formiq's side. Try again."],
    ['an answer without a token', { status: 201, body: {} }, 'Formiq sent an answer the app could not read. Try again.'],
  ])('%s: says so, stays here, and keeps what was typed', async (_name, reply, message) => {
    backend.on('POST', REGISTER, reply);
    const { onSignedUp } = await renderSignUp();
    await fillIn();

    await createAccount();

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(message);
    expect(within(screen.getByTestId('screen-footer')).getByRole('alert')).toBe(alert);
    expect(onSignedUp).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Create Account' })).toBeEnabled();
    expect(screen.getByLabelText('Email')).toHaveDisplayValue('sam@example.com');
    expect(screen.getByLabelText('Password')).toHaveDisplayValue('longenough');
  });

  test('a failed try can be retried, and the old message goes away as soon as it is edited or retried', async () => {
    backend.on('POST', REGISTER, { status: 500 });
    backend.on('POST', REGISTER, { status: 201, body: { access_token: TOKEN } });
    const { onSignedUp } = await renderSignUp();
    await fillIn();

    await createAccount();
    await screen.findByText("Something went wrong on Formiq's side. Try again.");

    await type('Email', 'sam@example.org');
    expect(screen.queryByText("Something went wrong on Formiq's side. Try again.")).toBeNull();

    await createAccount();
    await screen.findByRole('button', { name: 'Create Account' });
    expect(backend.requests).toHaveLength(2);
    expect(onSignedUp).toHaveBeenCalledTimes(1);
  });
});

describe('<SignUpScreen /> moving around', () => {
  test('"Log in" opens the login screen and Back goes back, without any request', async () => {
    const { onBack, onSwitchToSignIn } = await renderSignUp();

    await fireEvent.press(screen.getByRole('link', { name: 'Already have an account? Log in' }));
    expect(onSwitchToSignIn).toHaveBeenCalledTimes(1);

    await fireEvent.press(screen.getByRole('button', { name: 'Back' }));
    expect(onBack).toHaveBeenCalledTimes(1);
    expect(backend.requests).toHaveLength(0);
  });

  test('"next" on the email keyboard keeps the keyboard up for the password; "done" submits', async () => {
    backend.on('POST', REGISTER, { status: 201, body: { access_token: TOKEN } });
    await renderSignUp();
    await fillIn();

    expect(screen.getByLabelText('Email')).toHaveProp('submitBehavior', 'submit');

    await fireEvent(screen.getByLabelText('Password'), 'submitEditing');
    await screen.findByRole('button', { name: 'Create Account' });
    expect(backend.requests).toHaveLength(1);
  });
});
