import { View } from 'react-native';

import { AppIcon, type IconName } from '../../components';
import { layout, radii, spacing, useTheme, type ColorToken } from '../../theme';

const SIZE = spacing.xxxl * 4;
const CORE = spacing.xxxl * 2;
const CHIP = spacing.xxxl - spacing.sm;

type Orbit = { icon: IconName; color: ColorToken; position: { top?: number; bottom?: number; left?: number; right?: number } };

const ORBITS: Orbit[] = [
  { icon: 'fire', color: 'warm', position: { top: spacing.sm, left: spacing.sm } },
  { icon: 'heart-pulse', color: 'warm', position: { top: spacing.sm, right: spacing.sm } },
  { icon: 'kettlebell', color: 'accent', position: { bottom: spacing.sm, left: spacing.sm } },
  { icon: 'arm-flex', color: 'accent', position: { bottom: spacing.sm, right: spacing.sm } },
];

// The welcome picture: a dumbbell in the middle of two rings, with the four things Formiq cares about
// around it. Drawn from icons and theme colors, so it follows dark and light. It is decoration only.
export function WelcomeHero() {
  const { colors } = useTheme();
  const ring = {
    position: 'absolute' as const,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
    borderRadius: radii.pill,
    borderWidth: layout.borderWidth.thin,
    borderColor: colors.border,
  };

  return (
    <View
      testID="welcome-hero"
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      style={{ width: SIZE, height: SIZE, alignItems: 'center', justifyContent: 'center' }}
    >
      <View style={[ring, { width: SIZE, height: SIZE }]} />
      <View
        style={[
          ring,
          { width: SIZE * 0.72, height: SIZE * 0.72, backgroundColor: colors.primarySubtle, borderColor: colors.accent },
        ]}
      />
      <View
        style={{
          width: CORE,
          height: CORE,
          alignItems: 'center',
          justifyContent: 'center',
          borderRadius: radii.pill,
          backgroundColor: colors.primary,
        }}
      >
        <AppIcon name="dumbbell" size={CORE / 2} color="textOnPrimary" />
      </View>
      {ORBITS.map((orbit) => (
        <View
          key={orbit.icon}
          style={[
            ring,
            {
              width: CHIP,
              height: CHIP,
              backgroundColor: colors.surface,
              ...orbit.position,
            },
          ]}
        >
          <AppIcon name={orbit.icon} size={CHIP / 2} color={orbit.color} />
        </View>
      ))}
    </View>
  );
}
