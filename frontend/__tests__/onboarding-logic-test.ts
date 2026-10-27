import { emptyDraft, type ProfileDraft } from '../src/onboarding/draft';
import {
  ACTIVITY_OPTIONS,
  EXPERIENCE_OPTIONS,
  GENDER_OPTIONS,
  GOAL_OPTIONS,
  LOCATION_OPTIONS,
} from '../src/onboarding/options';
import { buildProfilePayload } from '../src/onboarding/profilePayload';
import {
  cmToFeetInches,
  feetInchesToCm,
  kgToPounds,
  parseDecimal,
  parseWholeNumber,
  poundsToKg,
} from '../src/onboarding/units';
import {
  hasErrors,
  isProfileComplete,
  validateAccount,
  validateDetails,
  validateGoal,
  validateLocation,
  validateTraining,
} from '../src/onboarding/validation';

const COMPLETE: ProfileDraft = {
  ...emptyDraft,
  goal: 'build_muscle',
  firstName: ' Sam ',
  lastName: '',
  age: '30',
  gender: 'other',
  heightCm: '175',
  weight: '70',
  experience: 'beginner',
  trainingDays: 3,
  activityLevel: 'moderate',
  sleepHours: '7.5',
  location: 'gym',
};

describe('the values sent to the backend', () => {
  test('the goals are the ones the backend recognises (backend/app/guidance/nutrition.py)', () => {
    const recognisedByTheBackend = ['lose_weight', 'fat_loss', 'build_muscle', 'muscle_gain', 'general_fitness'];
    expect(GOAL_OPTIONS.map((goal) => goal.value)).toEqual(['build_muscle', 'lose_weight', 'general_fitness']);
    for (const goal of GOAL_OPTIONS) expect(recognisedByTheBackend).toContain(goal.value);
  });

  test('every value fits the backend text limit of 50 characters', () => {
    for (const options of [GOAL_OPTIONS, GENDER_OPTIONS, EXPERIENCE_OPTIONS, ACTIVITY_OPTIONS, LOCATION_OPTIONS]) {
      for (const option of options) expect(option.value.length).toBeLessThanOrEqual(50);
    }
  });
});

describe('units', () => {
  test('converts heights both ways', () => {
    expect(feetInchesToCm(5, 9)).toBe(175.3);
    expect(feetInchesToCm(6, 0)).toBe(182.9);
    expect(cmToFeetInches(175)).toEqual({ feet: 5, inches: 9 });
    expect(cmToFeetInches(182.88)).toEqual({ feet: 6, inches: 0 });
  });

  test('converts weights both ways', () => {
    expect(poundsToKg(154)).toBe(69.9);
    expect(kgToPounds(70)).toBe(154.3);
  });

  test.each([
    ['70', 70],
    ['7.5', 7.5],
    ['7,5', 7.5],
    [' 7 ', 7],
  ])('reads %j as %d', (text, value) => {
    expect(parseDecimal(text)).toBe(value);
  });

  test.each(['', 'abc', '-5', '1e3', '1.2.3', '.5', '5.', '1 000', '０'])('does not read %j as a number', (text) => {
    expect(parseDecimal(text)).toBeNull();
  });

  test('whole numbers have no decimals', () => {
    expect(parseWholeNumber('30')).toBe(30);
    expect(parseWholeNumber('30.5')).toBeNull();
    expect(parseWholeNumber('')).toBeNull();
  });
});

describe('account validation', () => {
  test('sign up follows the backend rules', () => {
    expect(validateAccount('sam@example.com', 'longenough', 'signUp')).toEqual({});
    expect(validateAccount('', '', 'signUp')).toEqual({
      email: 'Enter your email address.',
      password: 'Enter your password.',
    });
    expect(validateAccount('not-an-email', 'longenough', 'signUp').email).toBe('Enter a valid email address.');
    expect(validateAccount('a b@c.d', 'longenough', 'signUp').email).toBe('Enter a valid email address.');
    expect(validateAccount('sam@example.com', '1234567', 'signUp').password).toBe('Use at least 8 characters.');
    expect(validateAccount('sam@example.com', '12345678', 'signUp')).toEqual({});
    expect(validateAccount('sam@example.com', 'x'.repeat(1025), 'signUp').password).toBe('Use at most 1024 characters.');
  });

  test('a password is not trimmed, so spaces count', () => {
    expect(validateAccount('sam@example.com', '        ', 'signUp')).toEqual({});
  });

  test('signing in only needs both fields: the backend decides if they match', () => {
    expect(validateAccount('whatever', 'x', 'signIn')).toEqual({});
    expect(validateAccount('  ', '', 'signIn')).toEqual({
      email: 'Enter your email address.',
      password: 'Enter your password.',
    });
  });
});

describe('step validation', () => {
  test('a goal and a location must be chosen', () => {
    expect(validateGoal(emptyDraft)).toEqual({ goal: 'Choose a goal to continue.' });
    expect(validateGoal(COMPLETE)).toEqual({});
    expect(validateLocation(emptyDraft)).toEqual({ location: 'Choose where you will work out.' });
    expect(validateLocation(COMPLETE)).toEqual({});
  });

  test('empty personal details list every problem', () => {
    expect(validateDetails(emptyDraft)).toEqual({
      firstName: 'Enter your first name.',
      age: 'Enter your age as a whole number from 13 to 100.',
      gender: 'Choose an option.',
      height: 'Enter a height from 100 to 250 cm.',
      weight: 'Enter a weight from 30 to 300 kg.',
    });
    expect(validateDetails(COMPLETE)).toEqual({});
  });

  test.each([
    ['age', '12', false],
    ['age', '13', true],
    ['age', '100', true],
    ['age', '101', false],
    ['age', '30.5', false],
    ['heightCm', '99.9', false],
    ['heightCm', '100', true],
    ['heightCm', '250', true],
    ['heightCm', '250.1', false],
    ['weight', '29.9', false],
    ['weight', '30', true],
    ['weight', '300', true],
    ['weight', '300.1', false],
  ] as const)('%s %s is valid: %s', (field, value, valid) => {
    const errors = validateDetails({ ...COMPLETE, [field]: value });
    const key = field === 'heightCm' ? 'height' : field;
    expect(errors[key] === undefined).toBe(valid);
  });

  test('a first name is needed and has a length limit; a last name is optional', () => {
    expect(validateDetails({ ...COMPLETE, firstName: '   ' }).firstName).toBe('Enter your first name.');
    expect(validateDetails({ ...COMPLETE, firstName: 'x'.repeat(101) }).firstName).toBe('Use at most 100 characters.');
    expect(validateDetails({ ...COMPLETE, lastName: 'x'.repeat(101) }).lastName).toBe('Use at most 100 characters.');
    expect(validateDetails({ ...COMPLETE, lastName: '' })).toEqual({});
  });

  test('feet and inches are checked in their own units', () => {
    const imperial = { ...COMPLETE, heightUnit: 'ft' as const, heightCm: '', heightFeet: '5', heightInches: '9' };
    expect(validateDetails(imperial).height).toBeUndefined();
    expect(validateDetails({ ...imperial, heightInches: '' }).height).toBeUndefined(); // 5 ft
    expect(validateDetails({ ...imperial, heightInches: '12' }).height).toBe('Inches go from 0 to 11.');
    expect(validateDetails({ ...imperial, heightFeet: '' }).height).toBe('Enter a height from 3 ft 4 in to 8 ft 2 in.');
    expect(validateDetails({ ...imperial, heightFeet: '3', heightInches: '3' }).height).toBeDefined();
    expect(validateDetails({ ...imperial, heightFeet: '3', heightInches: '4' }).height).toBeUndefined();
    expect(validateDetails({ ...imperial, heightFeet: '8', heightInches: '2' }).height).toBeUndefined();
    expect(validateDetails({ ...imperial, heightFeet: '8', heightInches: '3' }).height).toBeDefined();
  });

  test('pounds are checked in pounds', () => {
    const pounds = { ...COMPLETE, weightUnit: 'lb' as const };
    expect(validateDetails({ ...pounds, weight: '154' }).weight).toBeUndefined();
    expect(validateDetails({ ...pounds, weight: '66' }).weight).toBe('Enter a weight from 67 to 661 lb.');
    expect(validateDetails({ ...pounds, weight: '67' }).weight).toBeUndefined();
    expect(validateDetails({ ...pounds, weight: '661' }).weight).toBeUndefined();
    expect(validateDetails({ ...pounds, weight: '662' }).weight).toBeDefined();
  });

  test('training needs every answer, and sleep in range', () => {
    expect(validateTraining(emptyDraft)).toEqual({
      experience: 'Choose your experience level.',
      trainingDays: 'Choose how many days a week.',
      activityLevel: 'Choose an activity level.',
      sleepHours: 'Enter the hours you usually sleep, from 3 to 14.',
    });
    expect(validateTraining(COMPLETE)).toEqual({});
    expect(validateTraining({ ...COMPLETE, sleepHours: '2.9' }).sleepHours).toBeDefined();
    expect(validateTraining({ ...COMPLETE, sleepHours: '3' }).sleepHours).toBeUndefined();
    expect(validateTraining({ ...COMPLETE, sleepHours: '14' }).sleepHours).toBeUndefined();
    expect(validateTraining({ ...COMPLETE, sleepHours: '14.1' }).sleepHours).toBeDefined();
    expect(hasErrors(validateTraining({ ...COMPLETE, sleepHours: '7,5' }))).toBe(false);
  });
});

describe('the profile request body', () => {
  test('has exactly the backend fields, in centimetres and kilograms', () => {
    expect(buildProfilePayload(COMPLETE)).toEqual({
      first_name: 'Sam',
      age: 30,
      height_cm: 175,
      weight_kg: 70,
      gender: 'other',
      fitness_experience: 'beginner',
      goal: 'build_muscle',
      training_frequency_per_week: 3,
      training_location: 'gym',
      activity_level: 'moderate',
      sleep_hours: 7.5,
      // nothing chosen: said as it is, so the backend keeps that the person did not say
      equipment_ids: [],
      no_equipment: false,
    });
  });

  test('sends a last name only when there is one', () => {
    expect(buildProfilePayload({ ...COMPLETE, lastName: ' Lee ' }).last_name).toBe('Lee');
    expect('last_name' in buildProfilePayload({ ...COMPLETE, lastName: '  ' })).toBe(false);
  });

  test('converts what was typed in feet, inches and pounds', () => {
    const payload = buildProfilePayload({
      ...COMPLETE,
      heightUnit: 'ft',
      heightCm: '',
      heightFeet: '5',
      heightInches: '9',
      weightUnit: 'lb',
      weight: '154',
    });
    expect(payload.height_cm).toBe(175.3);
    expect(payload.weight_kg).toBe(69.9);
  });

  test('carries the equipment chosen, as catalog ids', () => {
    const payload = buildProfilePayload({ ...COMPLETE, equipmentIds: [4, 1, 7], noEquipment: false });

    expect(payload.equipment_ids).toEqual([4, 1, 7]);
    expect(payload.no_equipment).toBe(false);
  });

  test('sends each chosen piece once', () => {
    expect(buildProfilePayload({ ...COMPLETE, equipmentIds: [2, 2, 5, 2] }).equipment_ids).toEqual([2, 5]);
  });

  test('says "no equipment" explicitly, and then lists none', () => {
    const payload = buildProfilePayload({ ...COMPLETE, equipmentIds: [], noEquipment: true });

    expect(payload.no_equipment).toBe(true);
    expect(payload.equipment_ids).toEqual([]);
  });

  test('never says both: "no equipment" wins over a list that should not be there', () => {
    const payload = buildProfilePayload({ ...COMPLETE, equipmentIds: [1, 2], noEquipment: true });

    expect(payload.no_equipment).toBe(true);
    expect(payload.equipment_ids).toEqual([]);
  });

  test('sends the equipment ids and never the names', () => {
    const payload = buildProfilePayload({ ...COMPLETE, equipmentIds: [3] });

    expect(Object.keys(payload).filter((key) => key.includes('equipment')).sort()).toEqual([
      'equipment_ids',
      'no_equipment',
    ]);
  });

  test('refuses an incomplete draft instead of sending it', () => {
    expect(isProfileComplete(COMPLETE)).toBe(true);
    expect(isProfileComplete({ ...COMPLETE, goal: null })).toBe(false);
    expect(() => buildProfilePayload({ ...COMPLETE, goal: null })).toThrow('The profile is not complete.');
    expect(() => buildProfilePayload(emptyDraft)).toThrow('The profile is not complete.');
  });
});
