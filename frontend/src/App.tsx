import { SafeAreaProvider } from 'react-native-safe-area-context';

import { OnboardingFlow } from './onboarding/OnboardingFlow';
import { SessionProvider } from './session/SessionProvider';
import { ThemeProvider } from './theme';

export default function App() {
  return (
    <SafeAreaProvider>
      <ThemeProvider>
        <SessionProvider>
          <OnboardingFlow />
        </SessionProvider>
      </ThemeProvider>
    </SafeAreaProvider>
  );
}
