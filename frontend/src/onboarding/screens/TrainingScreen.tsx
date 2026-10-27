import { useState } from 'react';
import { View } from 'react-native';

import { AppInput, AppText, ChoiceChips, FieldError, OptionCard } from '../../components';
import { spacing } from '../../theme';
import { CheckAnswers } from '../CheckAnswers';
import { ACTIVITY_OPTIONS, EXPERIENCE_OPTIONS, TRAINING_DAY_OPTIONS } from '../options';
import { StepFrame } from '../StepFrame';
import { stepProgress } from '../steps';
import { hasErrors, validateTraining } from '../validation';
import type { StepScreenProps } from './types';

// The profile also asks how a person trains: these answers are required by the backend, though the
// mockup has no screen for them. They sit after the personal details, before the location.
export function TrainingScreen({ draft, onChange, onNext, onBack, nextLabel = 'Next' }: StepScreenProps) {
  const [attempted, setAttempted] = useState(false);
  const errors = attempted ? validateTraining(draft) : {};

  const next = () => {
    if (hasErrors(validateTraining(draft))) {
      setAttempted(true);
      return;
    }
    onNext();
  };

  return (
    <StepFrame
      step={stepProgress('training')}
      title="Your training"
      subtitle="How you train now, so your profile fits you."
      primary={{ label: nextLabel, onPress: next, arrow: true }}
      onBack={onBack}
      footerMessage={hasErrors(errors) ? <CheckAnswers /> : null}
    >
      <View style={{ gap: spacing.lg }}>
        <View style={{ gap: spacing.sm }}>
          <AppText variant="label" color="textSecondary">
            Experience
          </AppText>
          <View accessibilityRole="radiogroup" accessibilityLabel="Experience" style={{ gap: spacing.md }}>
            {EXPERIENCE_OPTIONS.map((option) => (
              <OptionCard
                key={option.value}
                title={option.title}
                description={option.description}
                selected={draft.experience === option.value}
                onPress={() => onChange({ experience: option.value })}
              />
            ))}
          </View>
          {errors.experience ? <FieldError>{errors.experience}</FieldError> : null}
        </View>

        <ChoiceChips
          label="Training days per week"
          options={TRAINING_DAY_OPTIONS.map((days) => ({ value: days, label: String(days) }))}
          value={draft.trainingDays}
          onChange={(trainingDays) => onChange({ trainingDays })}
          error={errors.trainingDays}
          helperText="How many days you train, or want to."
          columns={4}
        />
        <ChoiceChips
          label="Daily activity"
          options={ACTIVITY_OPTIONS.map((option) => ({ value: option.value, label: option.title }))}
          value={draft.activityLevel}
          onChange={(activityLevel) => onChange({ activityLevel })}
          error={errors.activityLevel}
          helperText="Outside your workouts."
          columns={2}
        />
        <AppInput
          label="Sleep per night"
          value={draft.sleepHours}
          onChangeText={(sleepHours) => onChange({ sleepHours })}
          error={errors.sleepHours}
          helperText="Hours on a typical night, for example 7.5."
          trailing={
            <AppText color="textMuted" accessibilityElementsHidden importantForAccessibility="no">
              hours
            </AppText>
          }
          keyboardType="decimal-pad"
          returnKeyType="done"
        />
      </View>
    </StepFrame>
  );
}
