import { useMemo } from 'react';
import { ScrollView, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { AppText } from '../components';
import type { ProposalPhase } from '../coach/chatState';
import { proposalCardData } from '../coach/proposalCard';
import { RecoveryNotice, WaitingProposals } from '../coach/WaitingProposals';
import { WorkoutProposalCard } from '../coach/WorkoutProposalCard';
import { localDateKey } from '../home/format';
import { BackButton } from '../onboarding/BackButton';
import { spacing, useTheme } from '../theme';
import {
  mockIncompleteProposal,
  mockPendingProposal,
  mockProposal,
  mockUncomparedProposal,
  mockWeightDropProposal,
} from './coachProposalsMock';

type CoachCardPreviewScreenProps = {
  onBack: () => void;
};

// Every state of the workout card, one under the other, drawn from the mock proposals with nothing sent to anyone:
// the page to look at the card without driving the conversation to each state, or waiting out the pause of the
// ones that pass (loading, applying, dismissing). Its buttons do nothing here: the page says so. In the conversation
// itself the same card is live.
export function CoachCardPreviewScreen({ onBack }: CoachCardPreviewScreenProps) {
  const { colors, scheme } = useTheme();
  const insets = useSafeAreaInsets();
  const side = { paddingLeft: insets.left + spacing.lg, paddingRight: insets.right + spacing.lg };

  const { cards, waiting } = useMemo(() => {
    const now = new Date();
    const fresh = proposalCardData(mockProposal('new', now, 1), now);
    const updated = proposalCardData(mockProposal('edit', now, 2), now);
    const refined = proposalCardData(mockProposal('edit-refined', now, 3), now);
    const weighted = proposalCardData(mockWeightDropProposal(now, 6), now);
    const unread = proposalCardData(mockUncomparedProposal(now, 4), now);
    const incomplete = proposalCardData(mockIncompleteProposal(now, 5), now);
    return {
      cards: { fresh, updated, refined, weighted, unread, incomplete },
      waiting: [mockPendingProposal('edit', now, 7, 5), mockPendingProposal('new', now, 8, 12)],
    };
  }, []);

  const none = () => undefined;
  const proposal = (
    label: string,
    card: (typeof cards)[keyof typeof cards],
    phase: ProposalPhase,
    extra: { proposedAgo?: string; askUnavailable?: string } = {},
  ) => ({
    label,
    node: <WorkoutProposalCard state="proposal" card={card} phase={phase} onApply={none} onAskForChanges={none} onDismiss={none} {...extra} />,
  });

  const today = localDateKey(new Date());
  const states = [
    proposal('New workout', cards.fresh, { kind: 'ready' }),
    proposal('Updated workout, with Key Changes', cards.updated, { kind: 'ready' }),
    proposal('Updated workout, after "easier on my knees"', cards.refined, { kind: 'ready' }),
    proposal('Updated workout, dropping a weight', cards.weighted, { kind: 'ready' }),
    proposal('Updated workout, the backend could not compare', cards.unread, { kind: 'ready' }),
    { label: 'Loading proposal', node: <WorkoutProposalCard state="loading" /> },
    proposal('Applying', cards.updated, { kind: 'applying' }),
    proposal('Applied', cards.updated, { kind: 'applied', planId: 100, name: cards.updated.title, scheduledDate: today }),
    proposal('Applied, new workout', cards.fresh, { kind: 'applied', planId: 101, name: cards.fresh.title, scheduledDate: today }),
    proposal('Apply failed, can try again', cards.fresh, {
      kind: 'apply-failed',
      failure: { message: "Can't reach Formiq. Check your connection and try again.", retryable: true },
    }),
    proposal('Apply failed, needs a new proposal', cards.updated, {
      kind: 'apply-failed',
      failure: { message: 'This proposal has expired. Ask the coach for a new one.', retryable: false },
    }),
    proposal('Dismissing', cards.fresh, { kind: 'rejecting' }),
    proposal('Dismissed', cards.fresh, { kind: 'rejected' }),
    proposal('Dismissed, an updated workout', cards.updated, { kind: 'rejected' }),
    proposal('Dismiss failed, can try again', cards.fresh, {
      kind: 'reject-failed',
      failure: { message: "Can't reach Formiq. Check your connection and try again.", retryable: true },
    }),
    proposal('Dismiss failed, already applied or changed', cards.updated, {
      kind: 'reject-failed',
      failure: { message: 'This workout was already applied or changed. Check your plans.', retryable: false },
    }),
    proposal('No longer waiting (expired)', cards.fresh, { kind: 'expired' }),
    proposal('Waiting from before, the newest', cards.updated, { kind: 'ready' }, { proposedAgo: 'Proposed 5 min ago' }),
    proposal(
      'Waiting from before, an older one',
      cards.fresh,
      { kind: 'ready' },
      {
        proposedAgo: 'Proposed 12 min ago',
        askUnavailable: `The coach changes your newest waiting workout, “${cards.updated.title}”. This older one can only be applied or dismissed.`,
      },
    ),
    {
      label: 'Several workouts waiting, to choose from',
      node: <WaitingProposals entries={waiting} onReview={none} />,
    },
    {
      label: 'Looking for waiting workouts failed',
      node: <RecoveryNotice message="Can't reach Formiq. Couldn't check for workouts waiting for your approval." onRetry={none} />,
    },
    {
      label: 'Proposal generation failed',
      node: <WorkoutProposalCard state="generation-failed" message="Can't reach Formiq. Check your connection and try again." onRetry={none} />,
    },
    proposal('Older version', cards.fresh, { kind: 'superseded', reason: 'newer-version' }),
    proposal('Workout the catalog could not fully cover', cards.incomplete, { kind: 'ready' }),
  ];

  return (
    <View testID="coach-card-preview" style={{ flex: 1, backgroundColor: colors.background }}>
      <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
      <View style={{ flex: 1, paddingTop: insets.top }}>
        <View style={side}>
          <BackButton onPress={onBack} />
        </View>
        <ScrollView contentContainerStyle={{ gap: spacing.xl, paddingTop: spacing.sm, paddingBottom: spacing.xxl, ...side }}>
          <View style={{ gap: spacing.sm }}>
            <AppText variant="title" accessibilityRole="header">
              Workout card states
            </AppText>
            <AppText color="textSecondary">
              Every state of the card the coach shows a workout in, from made-up proposals. Nothing here is sent or saved,
              and the buttons do nothing on this page.
            </AppText>
          </View>
          {states.map(({ label, node }) => (
            <View key={label} testID="preview-state" style={{ gap: spacing.sm }}>
              <AppText variant="label" color="textMuted">
                {label}
              </AppText>
              {node}
            </View>
          ))}
        </ScrollView>
      </View>
    </View>
  );
}
