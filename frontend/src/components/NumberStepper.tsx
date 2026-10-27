import { Pressable, View } from 'react-native';

import { layout, radii, spacing, useTheme } from '../theme';
import { AppIcon } from './AppIcon';
import { AppText } from './AppText';

type NumberStepperProps = {
  // what is being counted ("Reps", "Duration"): names the group for a screen reader
  label: string;
  // the value in words, as it is shown ("12 reps")
  valueLabel: string;
  onDecrease: () => void;
  onIncrease: () => void;
  // a button at its limit is dimmed and does nothing
  canDecrease: boolean;
  canIncrease: boolean;
  decreaseLabel: string;
  increaseLabel: string;
  testID?: string;
};

const BUTTON_SIZE = 56;

// A "-  12 reps  +" control: a square button each side of the value, in the emerald of an action. The screen owns
// the number and its limits and says when a button has reached one. The value is one adjustable element for a
// screen reader, which can swipe up and down to change it as well as press the two buttons.
export function NumberStepper({
  label,
  valueLabel,
  onDecrease,
  onIncrease,
  canDecrease,
  canIncrease,
  decreaseLabel,
  increaseLabel,
  testID,
}: NumberStepperProps) {
  return (
    <View testID={testID} style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.md }}>
      <StepButton icon="minus" label={decreaseLabel} enabled={canDecrease} onPress={onDecrease} testID={testID ? `${testID}-decrease` : undefined} />
      <View
        testID={testID ? `${testID}-value` : undefined}
        accessible
        accessibilityRole="adjustable"
        accessibilityLabel={label}
        accessibilityValue={{ text: valueLabel }}
        accessibilityActions={[{ name: 'increment' }, { name: 'decrement' }]}
        onAccessibilityAction={(event) => {
          if (event.nativeEvent.actionName === 'increment' && canIncrease) onIncrease();
          if (event.nativeEvent.actionName === 'decrement' && canDecrease) onDecrease();
        }}
        style={{ flex: 1, alignItems: 'center', justifyContent: 'center' }}
      >
        <AppText variant="heading" numberOfLines={1} maxFontSizeMultiplier={1.3} style={{ fontSize: 24, lineHeight: 30, fontWeight: '700', textAlign: 'center' }}>
          {valueLabel}
        </AppText>
      </View>
      <StepButton icon="plus" label={increaseLabel} enabled={canIncrease} onPress={onIncrease} testID={testID ? `${testID}-increase` : undefined} />
    </View>
  );
}

function StepButton({
  icon,
  label,
  enabled,
  onPress,
  testID,
}: {
  icon: 'minus' | 'plus';
  label: string;
  enabled: boolean;
  onPress: () => void;
  testID?: string;
}) {
  const { colors } = useTheme();

  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled: !enabled }}
      disabled={!enabled}
      onPress={onPress}
      style={({ pressed }) => ({
        width: BUTTON_SIZE,
        height: BUTTON_SIZE,
        alignItems: 'center',
        justifyContent: 'center',
        borderRadius: radii.md,
        borderWidth: layout.borderWidth.thin,
        borderColor: enabled ? colors.border : colors.disabledBackground,
        // a color change, not a fade: a faded button goes pale over a light page
        backgroundColor: !enabled ? colors.disabledBackground : pressed ? colors.primarySubtle : colors.surfaceMuted,
      })}
    >
      <AppIcon name={icon} size={28} color={enabled ? 'accent' : 'disabledText'} />
    </Pressable>
  );
}
