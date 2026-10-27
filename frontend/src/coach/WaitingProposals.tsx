import { View } from 'react-native';

import type { PendingProposal } from '../api';
import { AppButton, AppCard, AppText, Notice } from '../components';
import { spacing } from '../theme';
import { agoLabel, expiresLabel } from './days';
import { waitingDetails } from './waitingDetails';

// Several workouts are waiting for the person's approval from before this conversation, and none of them was made in
// it: they are listed so the person chooses which to look at. Nothing is chosen, applied or dismissed for them:
// "Review" only puts that workout's card in the conversation, where it is applied, changed or dismissed like any other.
export function WaitingProposals({
  entries,
  onReview,
  now = new Date(),
}: {
  entries: readonly PendingProposal[];
  onReview: (proposalId: string) => void;
  now?: Date;
}) {
  // what tells waiting workouts of one name apart (none for a workout with a name of its own)
  const details = waitingDetails(entries, now);
  return (
    <View testID="waiting-proposals" style={{ gap: spacing.md }}>
      {entries.length === 1 ? (
        <Notice title="1 workout is waiting for your approval">
          It was proposed earlier. Choose it to look it over: it is not applied or dismissed until you do.
        </Notice>
      ) : (
        <Notice title={`${entries.length} workouts are waiting for your approval`}>
          They were proposed earlier. Choose one to look it over: none is applied or dismissed until you do.
        </Notice>
      )}
      {entries.map((entry) => {
        const ago = agoLabel(entry.created_at, now);
        const expires = expiresLabel(entry.expires_at, now);
        const when = [ago ? `Proposed ${ago}` : null, expires ? `expires ${expires}` : null].filter(Boolean).join(' • ');
        const detail = details.get(entry.proposal_id);
        return (
          <AppCard key={entry.proposal_id} testID={`waiting-${entry.proposal_id}`} style={{ gap: spacing.sm }}>
            <View style={{ gap: spacing.xs }}>
              <AppText variant="label" color="accent">
                {entry.revision ? 'Updated Workout' : 'New Workout'}
              </AppText>
              <AppText variant="heading" accessibilityRole="header" style={{ fontSize: 17, lineHeight: 22 }}>
                {entry.name}
              </AppText>
              {detail ? (
                <AppText testID={`waiting-detail-${entry.proposal_id}`} variant="caption" color="textSecondary">
                  {detail}
                </AppText>
              ) : null}
              <AppText variant="caption" color="textSecondary">
                {[
                  entry.estimated_minutes > 0 ? `${entry.estimated_minutes} min` : null,
                  `${entry.exercises.length} ${entry.exercises.length === 1 ? 'exercise' : 'exercises'}`,
                ]
                  .filter(Boolean)
                  .join(' • ')}
              </AppText>
              {entry.revision ? (
                <AppText variant="caption" color="textSecondary">{`Replaces “${entry.revision.replaces_plan_name}”`}</AppText>
              ) : null}
              {when ? (
                <AppText testID={`waiting-when-${entry.proposal_id}`} variant="caption" color="textMuted">
                  {when}
                </AppText>
              ) : null}
            </View>
            <AppButton
              testID={`review-${entry.proposal_id}`}
              label="Review"
              leadingIcon="eye-outline"
              variant="secondary"
              compact
              accessibilityHint={`Opens “${entry.name}” to look over`}
              onPress={() => onReview(entry.proposal_id)}
            />
          </AppCard>
        );
      })}
    </View>
  );
}

// Looking for the workouts waiting for the person failed. Said in a small notice that does not block the conversation,
// with a button to look again (left out when asking again cannot help: an expired session). Never a made-up "none".
export function RecoveryNotice({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <View testID="recovery-failed" style={{ gap: spacing.sm }}>
      <Notice tone="error" title="Couldn't check your waiting workouts">
        {message}
      </Notice>
      {onRetry ? (
        <View style={{ alignSelf: 'flex-start' }}>
          <AppButton testID="recovery-retry" label="Try Again" leadingIcon="refresh" variant="secondary" compact onPress={onRetry} />
        </View>
      ) : null}
    </View>
  );
}
