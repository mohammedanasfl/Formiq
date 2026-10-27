import { useRef, useState, type ComponentRef, type ReactNode } from 'react';
import { TextInput, View } from 'react-native';

import { AppInput, AppText, ChoiceChips } from '../../components';
import { spacing } from '../../theme';
import { CheckAnswers } from '../CheckAnswers';
import type { HeightUnit, ProfileDraft, WeightUnit } from '../draft';
import { GENDER_OPTIONS } from '../options';
import { StepFrame } from '../StepFrame';
import { stepProgress } from '../steps';
import { UnitToggle } from '../UnitToggle';
import { cmToFeetInches, feetInchesToCm, kgToPounds, parseDecimal, parseWholeNumber, poundsToKg } from '../units';
import { hasErrors, INCHES_ERROR, validateDetails } from '../validation';
import type { StepScreenProps } from './types';

const HEIGHT_UNITS: { value: HeightUnit; label: string }[] = [
  { value: 'cm', label: 'cm' },
  { value: 'ft', label: 'ft / in' },
];
const WEIGHT_UNITS: { value: WeightUnit; label: string }[] = [
  { value: 'kg', label: 'kg' },
  { value: 'lb', label: 'lb' },
];

type Field = ComponentRef<typeof TextInput>;

// The person's name, age, gender, height and weight. How they train is asked on the next step.
export function DetailsScreen({ draft, onChange, onNext, onBack, nextLabel = 'Next' }: StepScreenProps) {
  const [attempted, setAttempted] = useState(false);
  const errors = attempted ? validateDetails(draft) : {};
  // "next" on the keyboard moves on to the following text field
  const lastNameField = useRef<Field>(null);
  const ageField = useRef<Field>(null);
  const heightField = useRef<Field>(null);
  const inchesField = useRef<Field>(null);
  const weightField = useRef<Field>(null);
  const keepKeyboardFor = (field: { current: Field | null }) => ({
    returnKeyType: 'next' as const,
    submitBehavior: 'submit' as const,
    onSubmitEditing: () => field.current?.focus(),
  });

  const next = () => {
    if (hasErrors(validateDetails(draft))) {
      setAttempted(true);
      return;
    }
    onNext();
  };

  return (
    <StepFrame
      step={stepProgress('details')}
      title="Tell us about yourself"
      subtitle="This helps create a plan that fits you."
      primary={{ label: nextLabel, onPress: next, arrow: true }}
      onBack={onBack}
      footerMessage={hasErrors(errors) ? <CheckAnswers /> : null}
    >
      <View style={{ gap: spacing.lg }}>
        <AppInput
          label="First name"
          value={draft.firstName}
          onChangeText={(firstName) => onChange({ firstName })}
          error={errors.firstName}
          autoCapitalize="words"
          autoComplete="given-name"
          textContentType="givenName"
          {...keepKeyboardFor(lastNameField)}
        />
        <AppInput
          ref={lastNameField}
          label="Last name (optional)"
          value={draft.lastName}
          onChangeText={(lastName) => onChange({ lastName })}
          error={errors.lastName}
          autoCapitalize="words"
          autoComplete="family-name"
          textContentType="familyName"
          {...keepKeyboardFor(ageField)}
        />
        <AppInput
          ref={ageField}
          label="Age"
          value={draft.age}
          onChangeText={(age) => onChange({ age })}
          error={errors.age}
          trailing={<Unit>years</Unit>}
          keyboardType="number-pad"
          maxLength={3}
          {...keepKeyboardFor(heightField)}
        />
        <ChoiceChips
          label="Gender"
          options={GENDER_OPTIONS.map((option) => ({ value: option.value, label: option.title }))}
          value={draft.gender}
          onChange={(gender) => onChange({ gender })}
          error={errors.gender}
        />

        <Measurement
          label="Height"
          unit={
            <UnitToggle
              label="Height unit"
              options={HEIGHT_UNITS}
              value={draft.heightUnit}
              onChange={(unit) => onChange(switchHeightUnit(draft, unit))}
            />
          }
        >
          {draft.heightUnit === 'cm' ? (
            <AppInput
              ref={heightField}
              hideLabel
              label="Height (cm)"
              value={draft.heightCm}
              onChangeText={(heightCm) => onChange({ heightCm })}
              error={errors.height}
              trailing={<Unit>cm</Unit>}
              keyboardType="decimal-pad"
              {...keepKeyboardFor(weightField)}
            />
          ) : (
            <View style={{ flexDirection: 'row', gap: spacing.md, alignItems: 'flex-start' }}>
              <View style={{ flex: 1 }}>
                <AppInput
                  ref={heightField}
                  hideLabel
                  label="Height (feet)"
                  value={draft.heightFeet}
                  onChangeText={(heightFeet) => onChange({ heightFeet })}
                  error={errors.height === INCHES_ERROR ? undefined : errors.height}
                  trailing={<Unit>ft</Unit>}
                  keyboardType="number-pad"
                  maxLength={1}
                  {...keepKeyboardFor(inchesField)}
                />
              </View>
              <View style={{ flex: 1 }}>
                <AppInput
                  ref={inchesField}
                  hideLabel
                  label="Height (inches)"
                  value={draft.heightInches}
                  onChangeText={(heightInches) => onChange({ heightInches })}
                  error={errors.height === INCHES_ERROR ? errors.height : undefined}
                  helperText="Optional."
                  trailing={<Unit>in</Unit>}
                  keyboardType="number-pad"
                  maxLength={2}
                  {...keepKeyboardFor(weightField)}
                />
              </View>
            </View>
          )}
        </Measurement>

        <Measurement
          label="Weight"
          unit={
            <UnitToggle
              label="Weight unit"
              options={WEIGHT_UNITS}
              value={draft.weightUnit}
              onChange={(unit) => onChange(switchWeightUnit(draft, unit))}
            />
          }
        >
          <AppInput
            ref={weightField}
            hideLabel
            label={`Weight (${draft.weightUnit})`}
            value={draft.weight}
            onChangeText={(weight) => onChange({ weight })}
            error={errors.weight}
            trailing={<Unit>{draft.weightUnit}</Unit>}
            keyboardType="decimal-pad"
            returnKeyType="done"
          />
        </Measurement>
      </View>
    </StepFrame>
  );
}

// A measurement: its name and a unit switch on one row, the field under them. The name is for the
// eye only: the field's own label says it, with the unit, to a screen reader.
function Measurement({ label, unit, children }: { label: string; unit: ReactNode; children: ReactNode }) {
  return (
    <View style={{ gap: spacing.sm }}>
      <View
        style={{
          flexDirection: 'row',
          flexWrap: 'wrap',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: spacing.sm,
        }}
      >
        <AppText variant="label" color="textSecondary" accessibilityElementsHidden importantForAccessibility="no">
          {label}
        </AppText>
        {unit}
      </View>
      {children}
    </View>
  );
}

// The unit at the end of a field. The field's label already names it for a screen reader.
function Unit({ children }: { children: ReactNode }) {
  return (
    <AppText color="textMuted" accessibilityElementsHidden importantForAccessibility="no">
      {children}
    </AppText>
  );
}

// Changing the unit converts what was already typed, so the person never has to redo it.
function switchHeightUnit(draft: ProfileDraft, unit: HeightUnit): Partial<ProfileDraft> {
  if (unit === draft.heightUnit) return {};
  if (unit === 'ft') {
    const cm = parseDecimal(draft.heightCm);
    if (cm === null) return { heightUnit: unit };
    const { feet, inches } = cmToFeetInches(cm);
    return { heightUnit: unit, heightFeet: String(feet), heightInches: String(inches) };
  }
  const feet = parseWholeNumber(draft.heightFeet);
  const inches = draft.heightInches.trim() === '' ? 0 : parseWholeNumber(draft.heightInches);
  if (feet === null || inches === null) return { heightUnit: unit };
  return { heightUnit: unit, heightCm: String(feetInchesToCm(feet, inches)) };
}

function switchWeightUnit(draft: ProfileDraft, unit: WeightUnit): Partial<ProfileDraft> {
  if (unit === draft.weightUnit) return {};
  const weight = parseDecimal(draft.weight);
  if (weight === null) return { weightUnit: unit };
  return {
    weightUnit: unit,
    weight: String(unit === 'lb' ? kgToPounds(weight) : poundsToKg(weight)),
  };
}
