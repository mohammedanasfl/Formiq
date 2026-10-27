import { useEffect, type ReactNode } from 'react';
import { ActivityIndicator, View } from 'react-native';

import { AppButton, AppText, Notice, OptionCard } from '../components';
import { spacing, useTheme } from '../theme';
import type { ProfileDraft } from './draft';
import { equipmentIcon } from './icons';
import type { EquipmentCatalog } from './useEquipmentCatalog';

type EquipmentOptionsProps = {
  // what is chosen, as the setup draft holds it
  choice: Pick<ProfileDraft, 'equipmentIds' | 'noEquipment'>;
  onChange: (patch: Pick<ProfileDraft, 'equipmentIds' | 'noEquipment'>) => void;
  catalog: EquipmentCatalog;
  // said under the error when the list cannot be loaded: what the person can do instead
  errorHint: ReactNode;
};

// The choice of equipment, shared by the setup step and the Profile tab's editor: the catalog's own list (GET
// /equipment) as "No equipment" and one chip per item, with its loading and error states. Choosing nothing is
// allowed, and "No equipment" excludes the chips. Nothing is stored by choosing here.
export function EquipmentOptions({ choice, onChange, catalog, errorHint }: EquipmentOptionsProps) {
  const { colors } = useTheme();
  const { status, load } = catalog;

  useEffect(() => {
    if (status === 'idle') void load();
  }, [status, load]);

  const toggle = (id: number) =>
    onChange({
      noEquipment: false,
      equipmentIds: choice.equipmentIds.includes(id)
        ? choice.equipmentIds.filter((selected) => selected !== id)
        : [...choice.equipmentIds, id],
    });

  return (
    <View style={{ gap: spacing.lg }}>
      {status === 'loading' || status === 'idle' ? (
        <View
          accessible
          accessibilityRole="progressbar"
          accessibilityLabel="Loading equipment"
          style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.md }}
        >
          <ActivityIndicator color={colors.accent} />
          <AppText color="textSecondary">Loading equipment…</AppText>
        </View>
      ) : null}

      {status === 'error' ? (
        <View style={{ gap: spacing.md }}>
          <Notice tone="error">{catalog.message}</Notice>
          <AppText color="textSecondary">{errorHint}</AppText>
          <AppButton variant="overlay" label="Try again" onPress={() => void load()} />
        </View>
      ) : null}

      {status === 'ready' ? (
        <View accessibilityLabel="Equipment" style={{ gap: spacing.md }}>
          <OptionCard
            role="checkbox"
            title="No equipment"
            description="Bodyweight only"
            selected={choice.noEquipment}
            onPress={() => onChange({ noEquipment: !choice.noEquipment, equipmentIds: [] })}
          />
          {catalog.items.length === 0 ? (
            <AppText color="textSecondary">Formiq has no equipment listed right now.</AppText>
          ) : null}
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm }}>
            {catalog.items.map((item) => (
              <OptionCard
                key={item.id}
                role="checkbox"
                variant="chip"
                icon={equipmentIcon(item.name)}
                title={item.name}
                selected={choice.equipmentIds.includes(item.id)}
                onPress={() => toggle(item.id)}
              />
            ))}
          </View>
          <AppText variant="caption" color="textMuted">
            The list is Formiq&apos;s exercise catalog: an item being listed doesn&apos;t mean there
            are exercises for it.
          </AppText>
        </View>
      ) : null}
    </View>
  );
}
