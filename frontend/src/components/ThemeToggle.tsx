import { Pressable } from 'react-native';

import { layout, radii, useTheme } from '../theme';
import { AppIcon } from './AppIcon';

const BUTTON_SIZE = 44;
const ICON_SIZE = 22;

// A round icon button that switches the app between its dark and light themes through ThemeProvider. It shows
// the theme it will switch to (a sun while the app is dark, a moon while it is light) and is named for what
// pressing it does, so a screen reader says "Switch to light theme". The choice is the app's own state: it is
// not remembered after the app is closed. The icon is plain, in the text color: emerald is kept for accents.
export function ThemeToggle({ testID }: { testID?: string }) {
  const { colors, scheme, setScheme } = useTheme();
  const next = scheme === 'dark' ? 'light' : 'dark';

  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      accessibilityLabel={`Switch to ${next} theme`}
      onPress={() => setScheme(next)}
      // the circle is a little under a thumb: the touch area reaches out to the full 48 dp
      hitSlop={(layout.touchTarget - BUTTON_SIZE) / 2}
      style={({ pressed }) => ({
        width: BUTTON_SIZE,
        height: BUTTON_SIZE,
        alignItems: 'center',
        justifyContent: 'center',
        borderRadius: radii.pill,
        borderWidth: layout.borderWidth.thin,
        borderColor: colors.border,
        backgroundColor: pressed ? colors.surfaceMuted : colors.surface,
      })}
    >
      <AppIcon name={scheme === 'dark' ? 'weather-sunny' : 'weather-night'} size={ICON_SIZE} color="textPrimary" />
    </Pressable>
  );
}
