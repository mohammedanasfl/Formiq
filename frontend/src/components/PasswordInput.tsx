import { useState } from 'react';
import { Pressable } from 'react-native';

import { layout } from '../theme';
import { AppIcon } from './AppIcon';
import { AppInput, type AppInputProps } from './AppInput';

export type PasswordInputProps = Omit<AppInputProps, 'secureTextEntry' | 'trailing'>;

// A password field with an eye button to show or hide it. The password is hidden until the user asks.
export function PasswordInput(props: PasswordInputProps) {
  const [visible, setVisible] = useState(false);

  return (
    <AppInput
      leadingIcon="lock-outline"
      autoCapitalize="none"
      autoCorrect={false}
      {...props}
      secureTextEntry={!visible}
      trailing={
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={visible ? 'Hide password' : 'Show password'}
          onPress={() => setVisible((current) => !current)}
          style={{
            minHeight: layout.touchTarget,
            minWidth: layout.touchTarget,
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <AppIcon name={visible ? 'eye-off-outline' : 'eye-outline'} color="textSecondary" />
        </Pressable>
      }
    />
  );
}
