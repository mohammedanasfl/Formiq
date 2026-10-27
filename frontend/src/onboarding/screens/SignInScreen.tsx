import { useRef, useState, type ComponentRef } from 'react';
import { TextInput, View } from 'react-native';

import { describeError, hasProfile, login, type Session } from '../../api';
import { AppInput, Notice, PasswordInput } from '../../components';
import { spacing } from '../../theme';
import { AccountFrame } from '../AccountFrame';
import { hasErrors, validateAccount } from '../validation';

type SignInScreenProps = {
  // something to tell first, such as an expired session
  notice?: string | null;
  // called only once the backend has accepted the login and answered whether a profile exists
  onSignedIn: (session: Session, profileExists: boolean) => void;
  onBack: () => void;
  onSwitchToSignUp: () => void;
};

// Signs in with POST /auth/login, then asks GET /users/{id}/profile whether setup was already done.
// It looks like the sign-up screen: both are built on `AccountFrame`.
export function SignInScreen({ notice, onSignedIn, onBack, onSwitchToSignUp }: SignInScreenProps) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [attempted, setAttempted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const passwordField = useRef<ComponentRef<typeof TextInput>>(null);
  // Set the moment a request starts, before any re-render: a double tap, or "done" on the keyboard
  // right after the button, cannot log in twice.
  const submitting = useRef(false);
  const errors = attempted ? validateAccount(email, password, 'signIn') : {};

  const submit = async () => {
    if (submitting.current) return;
    setAttempted(true);
    if (hasErrors(validateAccount(email, password, 'signIn'))) return;

    submitting.current = true;
    setLoading(true);
    setFailure(null);
    let session: Session;
    try {
      session = await login({ email, password });
    } catch (error) {
      submitting.current = false;
      setLoading(false);
      setFailure(describeError(error, 'signIn'));
      return;
    }
    try {
      const profileExists = await hasProfile(session);
      submitting.current = false;
      setLoading(false);
      onSignedIn(session, profileExists);
    } catch (error) {
      // logged in, but without knowing where to go next: nothing is started
      submitting.current = false;
      setLoading(false);
      setFailure(describeError(error, 'checkProfile'));
    }
  };

  return (
    <AccountFrame
      testID="signin"
      title="Log in"
      subtitle="Welcome back to Formiq."
      message={failure ? <Notice tone="error">{failure}</Notice> : null}
      primary={{ label: loading ? 'Logging in…' : 'Log in', onPress: submit, loading }}
      prompt={{ lead: 'New to Formiq?', action: 'Create an account', onPress: onSwitchToSignUp }}
      onBack={onBack}
    >
      <View style={{ gap: spacing.lg }}>
        {notice ? <Notice>{notice}</Notice> : null}
        <AppInput
          label="Email"
          leadingIcon="email-outline"
          value={email}
          onChangeText={setEmail}
          error={errors.email}
          keyboardType="email-address"
          autoCapitalize="none"
          autoComplete="email"
          autoCorrect={false}
          textContentType="emailAddress"
          returnKeyType="next"
          // keeps the keyboard up while focus moves on to the password
          submitBehavior="submit"
          onSubmitEditing={() => passwordField.current?.focus()}
        />
        <PasswordInput
          ref={passwordField}
          label="Password"
          value={password}
          onChangeText={setPassword}
          error={errors.password}
          autoComplete="current-password"
          textContentType="password"
          returnKeyType="done"
          onSubmitEditing={submit}
        />
      </View>
    </AccountFrame>
  );
}
