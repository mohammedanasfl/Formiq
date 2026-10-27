import { useRef, useState, type ComponentRef } from 'react';
import { TextInput, View } from 'react-native';

import { describeError, register, type Session } from '../../api';
import { AppInput, Notice, PasswordInput } from '../../components';
import { spacing } from '../../theme';
import { AccountFrame } from '../AccountFrame';
import { hasErrors, validateAccount } from '../validation';

type SignUpScreenProps = {
  // called only once the backend has created the account and signed it in
  onSignedUp: (session: Session) => void;
  onBack: () => void;
  onSwitchToSignIn: () => void;
};

// Creates an account with POST /auth/register, which takes an email and a password and nothing
// else (the name goes in the profile later). The look is the one the log-in screen shares
// (`AccountFrame`).
export function SignUpScreen({ onSignedUp, onBack, onSwitchToSignIn }: SignUpScreenProps) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [attempted, setAttempted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const passwordField = useRef<ComponentRef<typeof TextInput>>(null);
  // Set the moment a request starts, before any re-render: a double tap, or "done" on the keyboard
  // right after the button, cannot send two requests.
  const submitting = useRef(false);
  const errors = attempted ? validateAccount(email, password, 'signUp') : {};

  const submit = async () => {
    if (submitting.current) return;
    setAttempted(true);
    if (hasErrors(validateAccount(email, password, 'signUp'))) return;

    submitting.current = true;
    setLoading(true);
    setFailure(null);
    let session: Session;
    try {
      session = await register({ email, password });
    } catch (error) {
      submitting.current = false;
      setLoading(false);
      setFailure(describeError(error, 'signUp'));
      return;
    }
    submitting.current = false;
    setLoading(false);
    onSignedUp(session);
  };

  return (
    <AccountFrame
      testID="signup"
      title="Create Account"
      subtitle="Start your fitness journey with Formiq."
      message={failure ? <Notice tone="error">{failure}</Notice> : null}
      primary={{ label: loading ? 'Creating account…' : 'Create Account', onPress: submit, loading }}
      prompt={{ lead: 'Already have an account?', action: 'Log in', onPress: onSwitchToSignIn }}
      onBack={onBack}
    >
      <View style={{ gap: spacing.lg }}>
        <AppInput
          label="Email"
          leadingIcon="email-outline"
          value={email}
          onChangeText={(text) => {
            setEmail(text);
            setFailure(null);
          }}
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
          onChangeText={(text) => {
            setPassword(text);
            setFailure(null);
          }}
          error={errors.password}
          helperText="At least 8 characters."
          autoComplete="new-password"
          textContentType="newPassword"
          returnKeyType="done"
          onSubmitEditing={submit}
        />
      </View>
    </AccountFrame>
  );
}
