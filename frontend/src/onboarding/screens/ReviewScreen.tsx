import type { ReactNode } from 'react';
import { View } from 'react-native';

import { AppText, LinkButton, Notice } from '../../components';
import { layout, spacing, useTheme } from '../../theme';
import type { ProfileDraft } from '../draft';
import { StepFrame } from '../StepFrame';
import { stepProgress, type ProfileStep } from '../steps';
import { summarise, type SummaryRow } from '../summary';

type ReviewScreenProps = {
  draft: ProfileDraft;
  // the names of the equipment chosen, as the catalog calls them
  equipmentNames: string[];
  saving: boolean;
  // why the last save failed, if it did
  error: string | null;
  onSave: () => void;
  onBack: () => void;
  onEdit: (step: ProfileStep) => void;
};

export function ReviewScreen({
  draft,
  equipmentNames,
  saving,
  error,
  onSave,
  onBack,
  onEdit,
}: ReviewScreenProps) {
  const sections = summarise(draft);
  const equipment = draft.noEquipment
    ? 'No equipment'
    : equipmentNames.length > 0
      ? equipmentNames.join(', ')
      : 'Not chosen';

  return (
    <StepFrame
      step={stepProgress('review')}
      title="Review profile"
      subtitle="Check your answers, then save."
      primary={{
        label: saving ? 'Saving…' : error ? 'Try again' : 'Save profile',
        onPress: onSave,
        loading: saving,
        arrow: true,
      }}
      onBack={onBack}
      backDisabled={saving}
      footerMessage={error ? <Notice tone="error">{error}</Notice> : null}
    >
      <View style={{ gap: spacing.lg }}>
        <Notice title="Not saved yet">
          Nothing is stored in your Formiq account until you tap Save profile.
        </Notice>

        <View>
          {sections.map((section, index) => (
            <Section
              key={section.step}
              first={index === 0}
              title={section.title}
              onEdit={() => onEdit(section.step)}
            >
              {section.rows.map((row) => (
                <Row key={row.label} row={row} bare={section.rows.length === 1} />
              ))}
            </Section>
          ))}

          <Section title="Equipment" onEdit={() => onEdit('equipment')}>
            <Row row={{ label: 'Equipment', value: equipment }} bare />
          </Section>
        </View>
      </View>
    </StepFrame>
  );
}

type SectionProps = {
  title: string;
  onEdit: () => void;
  first?: boolean;
  children: ReactNode;
};

// A heading with its Edit link, and the answers under it. Sections are told apart by a line and
// space, not boxed one by one.
function Section({ title, onEdit, first = false, children }: SectionProps) {
  const { colors } = useTheme();

  return (
    <View
      style={{
        gap: spacing.xs,
        paddingBottom: spacing.md,
        ...(first
          ? null
          : { paddingTop: spacing.md, borderTopWidth: layout.borderWidth.thin, borderTopColor: colors.border }),
      }}
    >
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.sm }}>
        <AppText variant="heading" accessibilityRole="header" style={{ flexShrink: 1 }}>
          {title}
        </AppText>
        {/* the link has room around its word for the touch: pulled out so the word ends where the answers do */}
        <View style={{ marginRight: -spacing.sm }}>
          <LinkButton label="Edit" accessibilityLabel={`Edit ${title.toLowerCase()}`} onPress={onEdit} />
        </View>
      </View>
      {children}
    </View>
  );
}

// One answer. In a section of a single answer the heading already names it, so only the value shows.
function Row({ row, bare = false }: { row: SummaryRow; bare?: boolean }) {
  if (bare) {
    return <AppText variant="button">{row.value}</AppText>;
  }

  return (
    <View
      accessible
      accessibilityLabel={`${row.label}: ${row.value}`}
      style={{ flexDirection: 'row', justifyContent: 'space-between', gap: spacing.lg, paddingVertical: spacing.xs }}
    >
      {/* secondary rather than muted: the photo's glow shows behind the labels */}
      <AppText color="textSecondary">{row.label}</AppText>
      <AppText variant="button" style={{ flexShrink: 1, textAlign: 'right' }}>
        {row.value}
      </AppText>
    </View>
  );
}
