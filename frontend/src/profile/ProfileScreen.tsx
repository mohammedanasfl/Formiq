import { ActivityIndicator, View } from 'react-native';

import type { SavedEquipment } from '../api';
import {
  AppButton,
  AppCard,
  AppText,
  ChoiceChips,
  ListRow,
  Notice,
  SectionHeader,
  TabScreen,
  Toast,
  useToast,
} from '../components';
import { radii, spacing, useTheme, type ThemeScheme } from '../theme';
import type { SavedEquipmentState } from './useSavedEquipment';

// What "Edit profile" says. It is mock-only: the app can create a profile (the setup steps after signing up) and
// change its equipment (the Equipment card's own Edit), but has no screen to change the rest yet, so nothing is
// opened or saved.
export const EDIT_PROFILE_NOTICE = "Editing your profile isn't built yet.";
// Said under the theme choice: it changes the app now, and is not kept once the app is closed.
export const THEME_NOTE = 'Changes the app now. Formiq does not remember it after you close the app yet.';

const AVATAR_SIZE = spacing.xxxl + spacing.lg;
const SCHEME_OPTIONS: readonly { value: ThemeScheme; label: string }[] = [
  { value: 'dark', label: 'Dark' },
  { value: 'light', label: 'Light' },
];

// What the equipment card says of what the backend keeps: the pieces the person chose, that they have none, or
// that they never said (a profile made before equipment was kept, or a step they skipped).
export function equipmentSummary(saved: SavedEquipment | null): string {
  if (saved?.noEquipment) return 'No equipment (bodyweight only)';
  if (saved && saved.equipment.length > 0) return saved.equipment.map((item) => item.name).join(', ');
  return 'Not chosen';
}

type ProfileScreenProps = {
  // First name, for the avatar and the heading. MOCK until the profile is read from the backend: the app has
  // no "who am I" route, and Home's greeting uses the same made-up name (src/mock/homeMock.ts).
  name: string;
  // The equipment saved with the profile, as the backend has it (useSavedEquipment), and asking again after a failure.
  equipment: SavedEquipmentState;
  onRetryEquipment: () => void;
  // opens the equipment editor, starting from what is saved; the card offers it only when there is a saved answer to start from
  onEditEquipment: (saved: SavedEquipment) => void;
  onSignOut: () => void;
};

// The Profile tab: who is signed in, the one profile action the app has (a notice that editing is not built), the
// equipment saved with the profile (read from the backend, never from the setup the person went through, and changed
// from its own editor), the light or dark theme, which really changes the app, and Log out, which really signs out.
export function ProfileScreen({ name, equipment, onRetryEquipment, onEditEquipment, onSignOut }: ProfileScreenProps) {
  const { colors, scheme, setScheme } = useTheme();
  const { message, show } = useToast();
  const editable = equipment.kind === 'ready' ? equipment.saved : null;

  return (
    <View testID="profile-screen" style={{ flex: 1 }}>
      <TabScreen>
        <View style={{ gap: spacing.xl }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.lg }}>
            <View
              testID="profile-avatar"
              accessibilityElementsHidden
              importantForAccessibility="no-hide-descendants"
              style={{
                width: AVATAR_SIZE,
                height: AVATAR_SIZE,
                alignItems: 'center',
                justifyContent: 'center',
                borderRadius: radii.pill,
                backgroundColor: colors.primary,
              }}
            >
              <AppText variant="title" color="textOnPrimary">
                {name.charAt(0).toUpperCase()}
              </AppText>
            </View>
            <View style={{ flex: 1 }}>
              <AppText variant="title" accessibilityRole="header" numberOfLines={1}>
                {name}
              </AppText>
            </View>
          </View>

          <View style={{ gap: spacing.md }}>
            <SectionHeader title="Profile" />
            <ListRow
              testID="profile-edit"
              title="Edit profile"
              subtitle="Update your details and goals"
              onPress={() => show(EDIT_PROFILE_NOTICE)}
            />
          </View>

          <View style={{ gap: spacing.md }}>
            <SectionHeader
              title="Equipment"
              // only over an answer the backend gave for a profile: with none there is nothing to change, and while it is
              // being read or could not be, what the editor would start from is not known
              actionLabel={editable ? 'Edit' : undefined}
              actionAccessibilityLabel="Edit equipment"
              onAction={editable ? () => onEditEquipment(editable) : undefined}
            />
            <EquipmentCard state={equipment} onRetry={onRetryEquipment} />
          </View>

          <View style={{ gap: spacing.md }}>
            <SectionHeader title="Appearance" />
            <ChoiceChips label="Theme" options={SCHEME_OPTIONS} value={scheme} onChange={setScheme} helperText={THEME_NOTE} />
          </View>

          <View style={{ gap: spacing.md }}>
            <SectionHeader title="Account" />
            <AppButton variant="secondary" label="Log out" onPress={onSignOut} />
          </View>
        </View>
      </TabScreen>
      <Toast message={message} />
    </View>
  );
}

// The saved equipment, or why it cannot be shown: being read, or the backend's answer could not be had.
function EquipmentCard({ state, onRetry }: { state: SavedEquipmentState; onRetry: () => void }) {
  const { colors } = useTheme();

  if (state.kind === 'loading') {
    return (
      <View
        accessible
        accessibilityRole="progressbar"
        accessibilityLabel="Loading your equipment"
        style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.md }}
      >
        <ActivityIndicator color={colors.accent} />
        <AppText color="textSecondary">Loading your equipment…</AppText>
      </View>
    );
  }
  if (state.kind === 'error') {
    return (
      <View style={{ gap: spacing.md }}>
        <Notice tone="error">{state.message}</Notice>
        {state.retryable ? <AppButton variant="secondary" label="Try again" onPress={onRetry} /> : null}
      </View>
    );
  }
  const summary = equipmentSummary(state.saved);
  const chosen = state.saved !== null && (state.saved.noEquipment || state.saved.equipment.length > 0);
  return (
    <AppCard testID="profile-equipment" accessible accessibilityLabel={`Equipment: ${summary}`}>
      <AppText color={chosen ? 'textPrimary' : 'textMuted'}>{summary}</AppText>
    </AppCard>
  );
}
