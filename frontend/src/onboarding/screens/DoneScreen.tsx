import { View } from 'react-native';

import { AppText, CheckMark } from '../../components';
import { radii, spacing, useTheme } from '../../theme';
import { StepFrame } from '../StepFrame';

const DISC = spacing.xxxl + spacing.sm;

type DoneScreenProps = {
  // the backend already had a profile for this account, so what was entered was not saved
  alreadySaved: boolean;
  onContinue: () => void;
};

// Shown only after the backend has answered the save: with its success (201), or with the news that
// the account already has a profile (409). Only the success has the check: in the second case nothing
// was saved, and the screen must not look as if it was.
export function DoneScreen({ alreadySaved, onContinue }: DoneScreenProps) {
  const { colors } = useTheme();

  return (
    <StepFrame
      lead={
        alreadySaved ? undefined : (
          <View
            testID="done-check"
            style={{
              width: DISC,
              height: DISC,
              borderRadius: radii.pill,
              alignItems: 'center',
              justifyContent: 'center',
              backgroundColor: colors.primary,
            }}
          >
            <CheckMark size={spacing.xl} color={colors.textOnPrimary} />
          </View>
        )
      }
      title={alreadySaved ? 'You already have a profile' : 'Profile saved'}
      subtitle={
        alreadySaved
          ? 'Your account already had a saved profile, so the answers from this session were not saved.'
          : 'Your profile is saved to your Formiq account.'
      }
      primary={{ label: 'Continue', onPress: onContinue, arrow: true }}
      centered
    >
      <View style={{ gap: spacing.md }}>
        <AppText color="textMuted" style={{ textAlign: 'center' }}>
          Workout plans aren&apos;t in the app yet.
        </AppText>
      </View>
    </StepFrame>
  );
}
