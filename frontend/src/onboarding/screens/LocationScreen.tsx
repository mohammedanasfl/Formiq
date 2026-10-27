import { useState } from 'react';
import { View } from 'react-native';

import { FieldError, OptionCard } from '../../components';
import { spacing } from '../../theme';
import { LOCATION_ICONS } from '../icons';
import { LOCATION_OPTIONS } from '../options';
import { StepFrame } from '../StepFrame';
import { stepProgress } from '../steps';
import { hasErrors, validateLocation } from '../validation';
import type { StepScreenProps } from './types';

export function LocationScreen({ draft, onChange, onNext, onBack, nextLabel = 'Next' }: StepScreenProps) {
  const [attempted, setAttempted] = useState(false);
  const errors = attempted ? validateLocation(draft) : {};

  const next = () => {
    if (hasErrors(validateLocation(draft))) {
      setAttempted(true);
      return;
    }
    onNext();
  };

  return (
    <StepFrame
      step={stepProgress('location')}
      title="Workout location"
      subtitle="Where do you plan to work out?"
      primary={{ label: nextLabel, onPress: next, arrow: true }}
      onBack={onBack}
      // in the footer, so it is in view whatever the scroll position
      footerMessage={errors.location ? <FieldError>{errors.location}</FieldError> : null}
    >
      <View accessibilityRole="radiogroup" accessibilityLabel="Workout location" style={{ gap: spacing.lg }}>
        {LOCATION_OPTIONS.map((option) => (
          <OptionCard
            key={option.value}
            title={option.title}
            description={option.description}
            icon={LOCATION_ICONS[option.value]}
            selected={draft.location === option.value}
            onPress={() => onChange({ location: option.value })}
          />
        ))}
      </View>
    </StepFrame>
  );
}
