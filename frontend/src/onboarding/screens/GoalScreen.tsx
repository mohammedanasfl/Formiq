import { useState } from 'react';
import { View } from 'react-native';

import { FieldError, OptionCard } from '../../components';
import { spacing } from '../../theme';
import { GOAL_ICONS } from '../icons';
import { GOAL_OPTIONS } from '../options';
import { StepFrame } from '../StepFrame';
import { stepProgress } from '../steps';
import { hasErrors, validateGoal } from '../validation';
import type { StepScreenProps } from './types';

export function GoalScreen({ draft, onChange, onNext, onBack, nextLabel = 'Next' }: StepScreenProps) {
  const [attempted, setAttempted] = useState(false);
  const errors = attempted ? validateGoal(draft) : {};

  const next = () => {
    if (hasErrors(validateGoal(draft))) {
      setAttempted(true);
      return;
    }
    onNext();
  };

  return (
    <StepFrame
      step={stepProgress('goal')}
      title="Your Fitness Goal"
      subtitle="What do you want to achieve with Formiq?"
      // "Continue" on the way forward; the flow says "Done" when a goal is edited from the review
      primary={{ label: nextLabel === 'Done' ? 'Done' : 'Continue', onPress: next, arrow: true }}
      onBack={onBack}
      footerMessage={errors.goal ? <FieldError>{errors.goal}</FieldError> : null}
    >
      <View accessibilityRole="radiogroup" accessibilityLabel="Goal" style={{ gap: spacing.lg }}>
        {GOAL_OPTIONS.map((option) => (
          <OptionCard
            key={option.value}
            title={option.title}
            description={option.description}
            icon={GOAL_ICONS[option.value]}
            selected={draft.goal === option.value}
            onPress={() => onChange({ goal: option.value })}
          />
        ))}
      </View>
    </StepFrame>
  );
}
