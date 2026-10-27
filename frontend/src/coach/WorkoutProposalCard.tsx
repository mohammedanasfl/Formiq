import { useState } from 'react';
import { Image, Pressable, useWindowDimensions, View } from 'react-native';

import { AppButton, AppIcon, AppText, DUMBBELL_LEVEL, Notice, type IconName } from '../components';
import type { ColorToken } from '../theme';
import { FixedTheme, layout, radii, spacing, useTheme } from '../theme';
import { SECTION_COLORS } from '../workouts/sectionColors';
import { framedImageStyleInBox } from '../workouts/framing';
import { dayLabel } from './days';
import type { PlanSection } from '../workouts/planDetails';
import { resolveWorkoutVisual } from '../workouts/workoutImages';
import type { ProposalPhase } from './chatState';
import type { CardSection, ProposalCardData } from './proposalCard';
import { visibleChangeIndexes } from './proposalChanges';

// How many Key Changes are listed before the rest are counted (a change of day is always listed: visibleChangeIndexes).
const MAX_CHANGE_LINES = 6;
const THUMB = { width: 104, height: 104 } as const;
// The narrowest a section's column may be before the three sections stack in rows, and the font scale beyond which
// they do: a column must hold "Main Workout" and "3 exercises" without breaking them.
const MIN_COLUMN_WIDTH = 108;
const MAX_COLUMN_FONT_SCALE = 1.2;
const SUBJECT_AT = 0.5;

export const APPLY_LABEL = { new: 'Apply This Workout', updated: 'Apply Updated Workout' } as const;
export const ASK_LABEL = 'Ask for More Changes';
export const DISMISS_LABEL = 'Dismiss';

type WorkoutProposalCardProps =
  // the coach is still working on it
  | { state: 'loading' }
  // the coach could not be reached, or could not answer
  // (`onRetry` is left out when asking again cannot help, as when the session has expired)
  | { state: 'generation-failed'; message: string; onRetry?: () => void }
  // a workout to review, apply, change or dismiss
  | {
      state: 'proposal';
      card: ProposalCardData;
      phase: ProposalPhase;
      onApply: () => void;
      onAskForChanges: () => void;
      onDismiss: () => void;
      // For a workout that was waiting from before this conversation: when it was proposed ("Proposed 12 min ago").
      proposedAgo?: string | null;
      // Set when asking for changes would not reach this workout (the coach changes the newest one that is waiting): why,
      // in words. "Ask for More Changes" is then left out and this is said in its place.
      askUnavailable?: string | null;
    };

// The one card every workout the coach shows is drawn on, whether it is new or a revision of a saved one: the same
// layout, spacing, type, picture rule and buttons; only the label, the content and the actions follow where the
// workout stands. A workout is never drawn as saved unless the backend confirmed it (the `applied` phase).
export function WorkoutProposalCard(props: WorkoutProposalCardProps) {
  const { colors } = useTheme();

  return (
    <View
      testID="proposal-card"
      style={{
        gap: spacing.md,
        padding: spacing.lg - layout.borderWidth.thin,
        borderWidth: layout.borderWidth.thin,
        borderRadius: radii.lg,
        borderColor: colors.border,
        backgroundColor: colors.surface,
      }}
    >
      {props.state === 'loading' ? (
        <LoadingBody />
      ) : props.state === 'generation-failed' ? (
        <FailedBody message={props.message} onRetry={props.onRetry} />
      ) : (
        <ProposalBody
          card={props.card}
          phase={props.phase}
          onApply={props.onApply}
          onAskForChanges={props.onAskForChanges}
          onDismiss={props.onDismiss}
          proposedAgo={props.proposedAgo ?? null}
          askUnavailable={props.askUnavailable ?? null}
        />
      )}
    </View>
  );
}

type PillTone = Extract<ColorToken, 'accent' | 'success' | 'error' | 'textMuted'>;

// The small label at the top of the card, with its icon.
function StatusPill({ icon, label, tone }: { icon: IconName; label: string; tone: PillTone }) {
  const { colors } = useTheme();
  const background =
    tone === 'error' ? `${colors.error}22` : tone === 'textMuted' ? colors.surfaceMuted : colors.primarySubtle;
  return (
    <View
      testID="proposal-status"
      accessibilityLiveRegion="polite"
      style={{
        alignSelf: 'flex-start',
        flexDirection: 'row',
        alignItems: 'center',
        gap: spacing.xs + 2,
        paddingVertical: spacing.xs + 1,
        paddingHorizontal: spacing.md,
        borderRadius: radii.pill,
        backgroundColor: background,
      }}
    >
      <AppIcon name={icon} size={16} color={tone} />
      <AppText variant="label" color={tone}>
        {label}
      </AppText>
    </View>
  );
}

function Skeleton({ width, height, radius = radii.sm }: { width: number | `${number}%`; height: number; radius?: number }) {
  const { colors } = useTheme();
  return <View style={{ width, height, borderRadius: radius, backgroundColor: colors.surfaceMuted }} />;
}

// The card's shape with nothing in it yet: where the picture, the title and the sections will be.
function LoadingBody() {
  return (
    <View testID="proposal-loading" accessible accessibilityLabel="Preparing your workout" accessibilityLiveRegion="polite" style={{ gap: spacing.md }}>
      <StatusPill icon="creation" label="Preparing your workout" tone="textMuted" />
      <View accessibilityElementsHidden importantForAccessibility="no-hide-descendants" style={{ gap: spacing.md }}>
        <View style={{ flexDirection: 'row', gap: spacing.md }}>
          <Skeleton width={THUMB.width} height={THUMB.height} radius={radii.md} />
          <View style={{ flex: 1, gap: spacing.sm, paddingTop: spacing.xs }}>
            <Skeleton width="85%" height={20} />
            <Skeleton width="60%" height={14} />
            <Skeleton width="75%" height={14} />
          </View>
        </View>
        <View style={{ flexDirection: 'row', gap: spacing.md }}>
          {[0, 1, 2].map((slot) => (
            <View key={slot} style={{ flex: 1, gap: spacing.sm }}>
              <Skeleton width="70%" height={14} />
              <Skeleton width="50%" height={12} />
            </View>
          ))}
        </View>
      </View>
    </View>
  );
}

function FailedBody({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <View testID="proposal-generation-failed" style={{ gap: spacing.md }}>
      <StatusPill icon="alert-circle-outline" label="Couldn't create the workout" tone="error" />
      <AppText color="textSecondary" accessibilityRole="alert" accessibilityLiveRegion="polite">
        {message}
      </AppText>
      {onRetry ? <AppButton label="Try Again" leadingIcon="refresh" variant="secondary" onPress={onRetry} /> : null}
    </View>
  );
}

function pillFor(card: ProposalCardData, phase: ProposalPhase): { icon: IconName; label: string; tone: PillTone } {
  if (phase.kind === 'applied') return { icon: 'check-circle', label: 'Applied', tone: 'success' };
  if (phase.kind === 'rejected') return { icon: 'close-circle-outline', label: 'Dismissed', tone: 'textMuted' };
  if (phase.kind === 'expired') return { icon: 'timer-off-outline', label: 'No longer waiting', tone: 'textMuted' };
  if (phase.kind === 'superseded') return { icon: 'history', label: 'Older version', tone: 'textMuted' };
  return { icon: 'creation', label: card.kind === 'new' ? 'New Workout' : 'Updated Workout', tone: 'accent' };
}

function ProposalBody({
  card,
  phase,
  onApply,
  onAskForChanges,
  onDismiss,
  proposedAgo,
  askUnavailable,
}: {
  card: ProposalCardData;
  phase: ProposalPhase;
  onApply: () => void;
  onAskForChanges: () => void;
  onDismiss: () => void;
  proposedAgo: string | null;
  askUnavailable: string | null;
}) {
  const { colors } = useTheme();
  const [open, setOpen] = useState<PlanSection | null>(null);
  const [width, setWidth] = useState(0);
  const { fontScale } = useWindowDimensions();
  const stacked = width > 0 && (width / Math.max(1, card.sections.length) < MIN_COLUMN_WIDTH || fontScale > MAX_COLUMN_FONT_SCALE);
  const pill = pillFor(card, phase);
  const applying = phase.kind === 'applying';
  const rejecting = phase.kind === 'rejecting';
  const applied = phase.kind === 'applied';
  const rejected = phase.kind === 'rejected';
  const expired = phase.kind === 'expired';
  const superseded = phase.kind === 'superseded';
  const failed = phase.kind === 'apply-failed' ? phase.failure : null;
  const dismissFailed = phase.kind === 'reject-failed' ? phase.failure : null;
  // still on offer: it can be applied or dismissed (and, mid-way, the button of what is going on shows it)
  const canApply = phase.kind === 'ready' || (failed?.retryable ?? false) || (dismissFailed?.retryable ?? false);
  const midway = applying || rejecting;
  // nothing more is offered: only what happened is said
  const closed = superseded || rejected || expired;
  const replacedName = card.replaces?.name;

  return (
    <>
      <StatusPill {...pill} />
      {proposedAgo ? (
        <AppText testID="proposal-recovered" variant="caption" color="textMuted">
          {proposedAgo}
        </AppText>
      ) : null}
      <Hero card={card} />
      <View onLayout={(event) => setWidth(event.nativeEvent.layout.width)} style={{ gap: spacing.sm }}>
        <View style={{ height: layout.borderWidth.thin, backgroundColor: colors.divider }} />
        <Sections card={card} open={open} onToggle={(id) => setOpen((current) => (current === id ? null : id))} stacked={stacked} />
      </View>
      {card.kind === 'updated' ? <KeyChanges card={card} /> : null}
      {card.coverageNotes.length > 0 ? (
        <Notice testID="coverage-note" title="Not a complete workout">
          {card.coverageNotes.join(' ')}
        </Notice>
      ) : null}
      {card.offTarget !== null && !applied && !closed ? (
        <Notice testID="off-target-note" title="A different workout">
          {`This replaces “${replacedName}”, not “${card.offTarget}”, which you opened the coach from.`}
        </Notice>
      ) : null}
      {failed ? (
        <Notice testID="apply-error" tone="error" title="Couldn't apply this workout">
          {failed.message}
        </Notice>
      ) : null}
      {dismissFailed ? (
        <Notice testID="dismiss-error" tone="error" title="Couldn't dismiss this workout">
          {dismissFailed.message}
        </Notice>
      ) : null}
      {closed ? (
        <AppText testID="proposal-note" variant="caption" color="textMuted" accessibilityLiveRegion="polite">
          {closedNote(phase, replacedName)}
        </AppText>
      ) : (
        <View style={{ gap: spacing.sm }}>
          <AppButton
            testID="apply-button"
            label={applying ? 'Applying…' : applied ? 'Applied' : failed?.retryable ? 'Try Again' : APPLY_LABEL[card.kind]}
            leadingIcon={applied ? 'check-circle' : applying ? undefined : failed?.retryable ? 'refresh' : 'check-circle-outline'}
            loading={applying}
            disabled={(!canApply && !applying) || rejecting}
            onPress={onApply}
          />
          {applied || askUnavailable ? null : (
            <AppButton
              testID="ask-button"
              label={ASK_LABEL}
              leadingIcon="pencil-outline"
              variant="secondary"
              disabled={midway}
              onPress={onAskForChanges}
              style={{ borderColor: midway ? colors.disabledBackground : colors.accent }}
            />
          )}
          {applied || !(canApply || midway) ? null : (
            <AppButton
              testID="dismiss-button"
              label={rejecting ? 'Dismissing…' : dismissFailed?.retryable ? 'Dismiss Again' : DISMISS_LABEL}
              leadingIcon={rejecting ? undefined : dismissFailed?.retryable ? 'refresh' : 'close-circle-outline'}
              loading={rejecting}
              variant="secondary"
              disabled={applying}
              onPress={onDismiss}
            />
          )}
          {askUnavailable && !applied ? (
            <AppText testID="ask-unavailable" variant="caption" color="textMuted">
              {askUnavailable}
            </AppText>
          ) : null}
          <AppText testID="proposal-caption" variant="caption" color="textMuted" accessibilityLiveRegion="polite">
            {applied
              ? savedCaption(phase, replacedName)
              : replacedName
                ? `Applying replaces “${replacedName}”. Until then it stays as it is.`
                : "Not saved yet. It's added to your plan when you apply it."}
          </AppText>
        </View>
      )}
    </>
  );
}

// What is said in place of the buttons once nothing more is offered. A dismissed workout says it saved nothing; one the
// backend no longer has says so without claiming it was dismissed.
function closedNote(phase: ProposalPhase, replacedName: string | undefined): string {
  switch (phase.kind) {
    case 'rejected':
      return replacedName
        ? `Dismissed. Nothing was saved, and “${replacedName}” is as it was.`
        : 'Dismissed. Nothing was saved.';
    case 'expired':
      return 'This workout is no longer waiting: it expired. Ask the coach for a new one.';
    case 'superseded':
      return phase.reason === 'newer-version'
        ? 'The coach made a newer version of this workout. Use the one below.'
        : 'Another version of this workout was applied, so this one can no longer be.';
    default:
      return '';
  }
}

// What the backend confirmed, in its own words: the name and day of the plan it saved, and the one it replaced.
function savedCaption(phase: Extract<ProposalPhase, { kind: 'applied' }>, replacedName: string | undefined): string {
  const label = phase.scheduledDate ? dayLabel(phase.scheduledDate, new Date()) : null;
  const when = label ? ` for ${label === 'Today' || label === 'Tomorrow' ? label.toLowerCase() : label}` : '';
  return replacedName
    ? `Replaced “${replacedName}” with “${phase.name}”${when}.`
    : `Added “${phase.name}” to your plan${when}.`;
}

// The picture of the workout's kind with its focus over it, and beside it the title, what the proposal says about
// it (focus and day) and its length and number of exercises. No difficulty and no description: the proposal has
// neither.
function Hero({ card }: { card: ProposalCardData }) {
  const { colors } = useTheme();
  const visual = resolveWorkoutVisual({ categories: card.categories });
  return (
    <View style={{ flexDirection: 'row', gap: spacing.md }}>
      <View
        testID="proposal-photo"
        accessibilityElementsHidden
        importantForAccessibility="no-hide-descendants"
        style={{ width: THUMB.width, height: THUMB.height, borderRadius: radii.md, overflow: 'hidden', backgroundColor: colors.surfaceMuted }}
      >
        <Image source={visual.source} resizeMode="cover" style={framedImageStyleInBox(visual.framing, THUMB, SUBJECT_AT)} />
        {visual.isFallback ? null : (
          <FixedTheme scheme="dark">
            <View
              style={{
                position: 'absolute',
                left: spacing.sm - 2,
                bottom: spacing.sm - 2,
                paddingVertical: 3,
                paddingHorizontal: spacing.sm,
                borderRadius: radii.pill,
                backgroundColor: 'rgba(8, 10, 12, 0.68)',
              }}
            >
              <AppText variant="caption" style={{ fontSize: 11.5, lineHeight: 15, fontWeight: '600' }}>
                {card.focusLabel}
              </AppText>
            </View>
          </FixedTheme>
        )}
      </View>
      <View style={{ flex: 1, gap: spacing.xs + 2 }}>
        <AppText variant="heading" accessibilityRole="header" style={{ fontSize: 17, lineHeight: 22 }}>
          {card.title}
        </AppText>
        {card.subtitle ? (
          <AppText variant="caption" color="textMuted">
            {card.subtitle}
          </AppText>
        ) : null}
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', columnGap: spacing.md, rowGap: spacing.xs }}>
          {card.minutes ? <Metric icon="clock-outline" text={`${card.minutes} min`} /> : null}
          <Metric icon="dumbbell" rotate={DUMBBELL_LEVEL} text={card.exerciseCountLabel} />
        </View>
      </View>
    </View>
  );
}

function Metric({ icon, text, rotate }: { icon: IconName; text: string; rotate?: number }) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.xs + 1 }}>
      <AppIcon name={icon} size={16} color="textMuted" rotate={rotate} />
      <AppText variant="label" color="textSecondary" style={{ fontWeight: '500' }}>
        {text}
      </AppText>
    </View>
  );
}

// The sections as three columns, or as rows when there is no room for columns. Pressing one lists its exercises
// under the row; one open at a time.
function Sections({ card, open, onToggle, stacked }: { card: ProposalCardData; open: PlanSection | null; onToggle: (id: PlanSection) => void; stacked: boolean }) {
  const openSection = card.sections.find((section) => section.id === open) ?? null;
  return (
    <View style={{ gap: spacing.sm }}>
      <View testID="proposal-sections" style={{ flexDirection: stacked ? 'column' : 'row' }}>
        {card.sections.map((section, index) => (
          <SectionHeader key={section.id} section={section} first={index === 0} open={open === section.id} stacked={stacked} onPress={() => onToggle(section.id)} />
        ))}
      </View>
      {openSection ? <SectionExercises section={openSection} /> : null}
    </View>
  );
}

function SectionHeader({ section, first, open, stacked, onPress }: { section: CardSection; first: boolean; open: boolean; stacked: boolean; onPress: () => void }) {
  const { colors, scheme } = useTheme();
  const dot = SECTION_COLORS[section.id][scheme].accent;
  const count = `${section.exercises.length} ${section.exercises.length === 1 ? 'exercise' : 'exercises'}`;
  const minutes = section.minutes ? `${section.minutes} min` : null;
  const chevron = <AppIcon name={open ? 'chevron-up' : 'chevron-down'} size={18} color="textMuted" />;

  return (
    <Pressable
      testID={`proposal-section-${section.id}`}
      accessibilityRole="button"
      accessibilityLabel={`${section.title}, ${count}${minutes ? `, ${minutes}` : ''}`}
      accessibilityState={{ expanded: open }}
      onPress={onPress}
      style={({ pressed }) => ({
        flex: stacked ? undefined : 1,
        minHeight: layout.touchTarget,
        justifyContent: 'center',
        paddingVertical: spacing.sm,
        paddingLeft: stacked || first ? 0 : spacing.md,
        paddingRight: stacked ? 0 : spacing.xs,
        borderLeftWidth: stacked || first ? 0 : layout.borderWidth.thin,
        borderLeftColor: colors.divider,
        opacity: pressed ? 0.7 : 1,
      })}
    >
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm }}>
        <View style={{ width: 9, height: 9, borderRadius: 5, backgroundColor: dot }} />
        <AppText variant="label" style={{ flexShrink: 1 }}>
          {section.title}
        </AppText>
        {stacked ? (
          <>
            <AppText variant="caption" color="textMuted" style={{ flex: 1 }}>
              {[count, minutes].filter(Boolean).join(' • ')}
            </AppText>
            {chevron}
          </>
        ) : null}
      </View>
      {stacked ? null : (
        <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingLeft: 9 + spacing.sm }}>
          <View>
            <AppText variant="caption" color="textMuted">
              {count}
            </AppText>
            {minutes ? (
              <AppText variant="caption" color="textMuted">
                {minutes}
              </AppText>
            ) : null}
          </View>
          {chevron}
        </View>
      )}
    </Pressable>
  );
}

// One section's exercises, tinted in the section's own color (the workout screen's), with what each asks for. An
// exercise that is new, or prescribed differently, against the workout this one replaces says so.
function SectionExercises({ section }: { section: CardSection }) {
  const { scheme } = useTheme();
  const palette = SECTION_COLORS[section.id][scheme];
  return (
    <View
      testID={`proposal-exercises-${section.id}`}
      style={{ gap: spacing.md, padding: spacing.md, borderRadius: radii.md, borderWidth: layout.borderWidth.thin, borderColor: palette.border, backgroundColor: palette.rows }}
    >
      {section.exercises.map((exercise) => (
        <View key={exercise.key} style={{ gap: 2 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm }}>
            <AppText variant="label" style={{ flexShrink: 1 }}>
              {exercise.name}
            </AppText>
            {exercise.mark ? (
              <View style={{ paddingVertical: 1, paddingHorizontal: spacing.sm, borderRadius: radii.pill, backgroundColor: palette.tagBackground }}>
                <AppText variant="caption" style={{ color: palette.tagText, fontSize: 11.5, lineHeight: 16, fontWeight: '600' }}>
                  {exercise.mark === 'new' ? 'New' : 'Changed'}
                </AppText>
              </View>
            ) : null}
          </View>
          <AppText variant="caption" color="textSecondary">
            {exercise.prescription}
          </AppText>
          <AppText variant="caption" color="textMuted">
            {exercise.equipment}
          </AppText>
        </View>
      ))}
    </View>
  );
}

// What differs from the workout this one would replace, as the backend compared the two: nothing is listed that
// the backend did not find. When it could not compare, the card says so and lists nothing, apart from the exercises
// the backend itself says the proposal keeps.
function KeyChanges({ card }: { card: ProposalCardData }) {
  const { colors } = useTheme();
  const lines = card.keyChangeLines;
  // `keyChanges` and `keyChangeLines` are one list, one line per change (proposalCard.ts)
  const shown = visibleChangeIndexes(card.keyChanges, MAX_CHANGE_LINES)
    .map((index) => lines[index])
    .filter((line): line is string => typeof line === 'string');
  const kept = card.replaces?.keptExercises ?? [];

  return (
    <View
      testID="key-changes"
      style={{
        gap: spacing.xs + 2,
        padding: spacing.md,
        borderRadius: radii.md,
        borderWidth: layout.borderWidth.thin,
        borderColor: `${colors.accent}55`,
        backgroundColor: colors.primarySubtle,
      }}
    >
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm }}>
        <AppIcon name="creation" size={16} color="accent" />
        <AppText variant="label" color="accent" accessibilityRole="header">
          Key Changes
        </AppText>
      </View>
      {card.comparison === 'unavailable' ? (
        <AppText testID="key-changes-unavailable" variant="caption" color="textSecondary">
          {`Formiq couldn't compare this with “${card.replaces?.name}”, so the changes aren't listed.`}
        </AppText>
      ) : shown.length === 0 ? (
        <AppText variant="caption" color="textSecondary">
          No exercise changes found.
        </AppText>
      ) : (
        shown.map((line) => (
          <View key={line} style={{ flexDirection: 'row', gap: spacing.sm }}>
            <AppText variant="caption" color="textSecondary">
              •
            </AppText>
            <AppText variant="caption" color="textSecondary" style={{ flex: 1 }}>
              {line}
            </AppText>
          </View>
        ))
      )}
      {lines.length > shown.length ? (
        <AppText variant="caption" color="textMuted">{`and ${lines.length - shown.length} more`}</AppText>
      ) : null}
      {kept.length > 0 ? (
        <AppText variant="caption" color="textMuted">{`Kept from your workout: ${kept.join(', ')}.`}</AppText>
      ) : null}
    </View>
  );
}
