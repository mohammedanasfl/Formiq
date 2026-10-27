import { useEffect, useRef, useState } from 'react';
import { ScrollView, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import type { SavedEquipment, Session } from '../api';
import { AppButton, AppText, Notice } from '../components';
import { BackButton } from '../onboarding/BackButton';
import { EquipmentOptions } from '../onboarding/EquipmentOptions';
import { useEquipmentCatalog } from '../onboarding/useEquipmentCatalog';
import { spacing, useTheme } from '../theme';
import { equipmentChange, selectionFromSaved, type EquipmentSelection } from './equipmentEdit';
import { useSaveEquipment } from './useSaveEquipment';

type EquipmentEditScreenProps = {
  session: Session;
  // what the backend has saved, as the Profile tab showed it when this was opened: the choice starts from it
  saved: SavedEquipment;
  // called with the backend's answer once it has saved the choice: the Profile tab shows exactly this
  onSaved: (saved: SavedEquipment) => void;
  // leave the editor, whether the choice was saved, changed nothing, or was given up
  onClose: () => void;
};

// Changes the equipment saved with the profile, from the Profile tab. The choice starts from what is saved and is
// local until Save: the backend decides, and only its answer reaches the Profile tab (`onSaved`), so equipment is
// never shown as saved when the save failed. A failed save keeps the editor open with what was chosen, says why, and
// can be tried again; Cancel and Back leave with nothing changed. Choosing exactly what is saved changes nothing and
// asks nothing of the backend.
export function EquipmentEditScreen({ session, saved, onSaved, onClose }: EquipmentEditScreenProps) {
  const { colors, scheme } = useTheme();
  const insets = useSafeAreaInsets();
  const catalog = useEquipmentCatalog();
  const [selection, setSelection] = useState<EquipmentSelection>(() => selectionFromSaved(saved));
  const { state, save } = useSaveEquipment(session, onSaved);
  const saving = state.kind === 'saving';
  const expired = state.kind === 'error' && !state.retryable;

  // the backend saved it: the work here is done, and the screen is left once, however often it is drawn again
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    if (state.kind === 'saved') close.current();
  }, [state.kind]);

  const onSave = () => {
    const change = equipmentChange(saved, selection, catalog.status === 'ready' ? catalog.items : null);
    if (change === null) onClose();
    else save(change);
  };

  const sidePadding = { paddingLeft: insets.left + spacing.lg, paddingRight: insets.right + spacing.lg };

  return (
    <View testID="equipment-edit-screen" style={{ flex: 1, backgroundColor: colors.background }}>
      <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
      <View style={{ flex: 1, paddingTop: insets.top, paddingBottom: insets.bottom }}>
        <View style={sidePadding}>
          <BackButton disabled={saving} onPress={onClose} />
        </View>
        <ScrollView
          style={{ flex: 1 }}
          contentContainerStyle={{ paddingTop: spacing.sm, paddingBottom: spacing.xl, ...sidePadding }}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          <View style={{ gap: spacing.xl }}>
            <View style={{ gap: spacing.xs }}>
              <AppText variant="title" accessibilityRole="header">
                Edit equipment
              </AppText>
              <AppText color="textSecondary">
                Select the equipment you have access to. The coach starts from it when it suggests workouts.
              </AppText>
            </View>
            <EquipmentOptions
              choice={selection}
              onChange={setSelection}
              catalog={catalog}
              errorHint="Your saved equipment stays as it is until you can choose again."
            />
          </View>
        </ScrollView>
        <View testID="equipment-edit-footer" style={{ gap: spacing.sm, paddingVertical: spacing.lg, ...sidePadding }}>
          {state.kind === 'error' ? <Notice tone="error">{state.message}</Notice> : null}
          <AppButton
            label={saving ? 'Saving…' : 'Save'}
            loading={saving}
            disabled={expired}
            onPress={onSave}
          />
          <AppButton variant="secondary" label="Cancel" disabled={saving} onPress={onClose} />
        </View>
      </View>
    </View>
  );
}
