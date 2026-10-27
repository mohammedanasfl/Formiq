import { useEffect, useMemo, useRef, useState } from 'react';
import { Keyboard, KeyboardAvoidingView, ScrollView, View, type ScrollViewInstance } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import type { WorkoutPlan } from '../api';
import { Notice } from '../components';
import type { CoachContext } from '../shell/routes';
import { spacing, useTheme } from '../theme';
import { canAskForChanges, isApplicable, newestWaiting, type ChatItem, type ChatTarget } from './chatState';
import { ChatComposer } from './ChatComposer';
import { CoachHeader } from './CoachHeader';
import { CoachMenu, type CoachMenuItem } from './CoachMenu';
import { FailureBubble } from './FailureBubble';
import type { CoachGateway } from './gateway';
import { agoLabel } from './days';
import { MessageBubble, TypingBubble } from './MessageBubble';
import { proposalCardData } from './proposalCard';
import { SuggestedReplies } from './SuggestedReplies';
import { useCoachChat, type CoachOpeningFor } from './useCoachChat';
import { RecoveryNotice, WaitingProposals } from './WaitingProposals';
import { WorkoutProposalCard } from './WorkoutProposalCard';

type CoachScreenProps = {
  // Everything the coach does, asked through this: the backend's (src/coach/apiGateway.ts) in the app, the made-up
  // gateway of mock mode in a preview (src/mock/MockCoachScreen.tsx). The screen does not know which.
  gateway: CoachGateway;
  // what a conversation opens with, for the workout it was opened from or for none; it starts over to the latter
  openingFor: CoachOpeningFor;
  // back to Home, the way the Android back button goes from any tab
  onBack: () => void;
  // set when the screen was opened from a workout ("Edit with AI"): the conversation is about that workout
  coachContext?: CoachContext | null;
  // more items for the overflow menu, after "Start over": the mock screen's preview and failure switches
  menuItems?: readonly CoachMenuItem[];
  // Whether the screen is the one on show. The shell keeps it mounted under the other tabs so the conversation (and
  // a workout being applied) is not lost when the person looks at Home; it is told when it is hidden.
  active?: boolean;
  // after the backend confirmed a workout was saved: the plan it answered with
  onApplied?: (plan: WorkoutPlan) => void;
};

const ASK_PLACEHOLDER = 'What would you like to change?';

// The AI Coach tab: a conversation with the coach. A header (Back, the coach's name, an overflow menu), the
// messages on a scrolling page that stays at the newest one, the workouts the coach proposes as cards the person
// can apply or ask to change, the coach's suggested replies, and a composer at the foot that rides above the
// keyboard. The tab bar stays below it.
//
// It only presents: the coach proposes, and only the person's own "apply", approved by the backend, saves a workout.
// Nothing here is saved by being shown, and a card says "Applied" only after the backend said so, and "Dismissed" only
// after the backend said that. Workouts that were waiting for the person from before the conversation are fetched when the
// screen is shown and offered, never applied, dismissed or chosen for them.
export function CoachScreen({ gateway, openingFor, onBack, coachContext, menuItems = [], active = true, onApplied }: CoachScreenProps) {
  const { colors, scheme } = useTheme();
  const insets = useSafeAreaInsets();
  const chat = useCoachChat(gateway, openingFor, coachContext ?? null, { onApplied, active });
  const [menuOpen, setMenuOpen] = useState(false);
  // "Ask for More Changes" was pressed: the field is focused and asks what to change, until a message is sent
  const [asking, setAsking] = useState(false);
  const [focusSignal, setFocusSignal] = useState(0);
  const scroll = useRef<ScrollViewInstance>(null);
  const side = { paddingLeft: insets.left + spacing.lg, paddingRight: insets.right + spacing.lg };
  const busy = chat.waiting || chat.applying || chat.rejecting;
  // a workout being applied or dismissed cannot be called back, so the conversation stays until the backend has answered
  const midway = chat.applying || chat.rejecting;

  // Where each item starts and ends on the page, and how tall the window on it is, as the list lays out.
  const positions = useRef<{ tops: Record<string, number>; bottoms: Record<string, number>; viewport: number }>({
    tops: {},
    bottoms: {},
    viewport: 0,
  });

  // The newest item the list has gone to, so a change to it later (a card going from applying to applied, which
  // makes it shorter) does not take the person back to it while they are reading. It is told by what the item IS as well
  // as by its id: the coach's typing dots turn into a failure bubble (or back, on Try Again) under the same id, and that
  // is a new thing to bring into view, with its Try Again button.
  const scrolledFor = useRef<string | null>(null);
  const newestKey = (item: ChatItem) => `${item.kind}:${item.id}`;

  // The newest thing stays in view: when a new one arrives (a message, the typing dots, a card), and when the
  // window on the list changes (the keyboard opening or closing). A message or the dots are shown by going to the
  // end. A workout card is taller than the room above the keyboard, so going to its end would hide its label,
  // picture and title: the list goes to where the coach's reply to it begins instead (as far as the end allows),
  // so the person reads the reply and the top of the card, and scrolls on for the buttons. When only the window
  // changed, a card is left where the person is reading it.
  const showNewest = (reason: 'grew' | 'resized') => {
    const { tops, bottoms, viewport } = positions.current;
    const last = chat.items[chat.items.length - 1];
    const before = chat.items[chat.items.length - 2];
    if (!last || (reason === 'grew' && scrolledFor.current === newestKey(last))) return;
    if (last.kind !== 'proposal') {
      scrolledFor.current = newestKey(last);
      scroll.current?.scrollToEnd({ animated: true });
      return;
    }
    if (reason === 'resized') return;
    const first = before?.kind === 'message' && before.role === 'assistant' ? before : last;
    // the card has not been laid out yet: it will report itself, and this runs again
    if (tops[first.id] === undefined || bottoms[last.id] === undefined) return;
    scrolledFor.current = newestKey(last);
    const end = Math.max(0, bottoms[last.id] + spacing.lg - viewport);
    scroll.current?.scrollTo({ y: Math.max(0, Math.min(end, tops[first.id] - spacing.md)), animated: true });
  };

  // Hidden under another tab: the keyboard goes with it. Back on show: the newest message is brought into view again.
  useEffect(() => {
    if (!active) Keyboard.dismiss();
    else scrolledFor.current = null;
  }, [active]);

  // "Ask for More Changes" on a card: what is written next is about it, so the conversation is about the saved workout
  // it replaces (if it replaces one) and the coach is held to that one
  const askForChanges = (id: string) => {
    chat.refine(id);
    setAsking(true);
    setFocusSignal((signal) => signal + 1);
  };

  const menu: CoachMenuItem[] = [
    {
      id: 'start-over',
      label: 'Start over',
      icon: 'restart',
      disabled: midway,
      hint: chat.applying
        ? 'Not while a workout is being applied'
        : chat.rejecting
          ? 'Not while a workout is being dismissed'
          : 'Clears this conversation and starts a new one',
      onPress: () => {
        if (chat.reset()) {
          setAsking(false);
          scrolledFor.current = null;
        }
      },
    },
    ...menuItems,
  ];

  return (
    <View testID="coach-screen" style={{ flex: 1, backgroundColor: colors.background }}>
      <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
      <View style={{ flex: 1, paddingTop: insets.top }}>
        <CoachHeader onBack={onBack} onOpenMenu={() => setMenuOpen(true)} style={side} />
        {/* lifts the replies and the composer over the keyboard; the tab bar under this view stays below it */}
        <KeyboardAvoidingView testID="coach-keyboard-avoider" style={{ flex: 1 }} behavior="padding">
          <ScrollView
            ref={scroll}
            testID="coach-messages"
            style={{ flex: 1 }}
            contentContainerStyle={{ gap: spacing.md, paddingTop: spacing.lg, paddingBottom: spacing.lg, ...side }}
            // a chip or the send button works with the keyboard up, and dragging the list puts it away
            keyboardShouldPersistTaps="handled"
            keyboardDismissMode="on-drag"
            showsVerticalScrollIndicator={false}
            onContentSizeChange={() => showNewest('grew')}
            onLayout={(event) => {
              positions.current.viewport = event.nativeEvent.layout.height;
              showNewest('resized');
            }}
          >
            {chat.launch && (chat.target === null || chat.target.planId === chat.launch.workoutId) ? (
              // what the coach was opened from: shown so the hand-over is visible, and so it is clear that nothing
              // was edited or saved on the way (it goes once a revision of that workout was applied)
              <Notice testID="coach-context" title={`Opened from ${chat.launch.title}`}>
                Nothing was changed or saved: the workout stays as it is until you approve a revised proposal.
              </Notice>
            ) : null}
            {chat.recoveryFailure ? (
              // looking for the workouts waiting for the person failed: said, without blocking the conversation
              <RecoveryNotice message={chat.recoveryFailure.message} onRetry={chat.recoveryFailure.retryable ? () => void chat.recover() : undefined} />
            ) : null}
            {chat.items.map((item) => (
              <View
                key={item.id}
                onLayout={(event) => {
                  const { y, height } = event.nativeEvent.layout;
                  positions.current.tops[item.id] = y;
                  positions.current.bottoms[item.id] = y + height;
                  if (item.id === chat.items[chat.items.length - 1]?.id) showNewest('grew');
                }}
              >
                <ConversationItem
                  item={item}
                  items={chat.items}
                  target={chat.target}
                  onApply={() => void chat.apply(item.id)}
                  onDismiss={() => void chat.reject(item.id)}
                  onAskForChanges={() => askForChanges(item.id)}
                  onRetry={chat.retry}
                  onReview={chat.review}
                />
              </View>
            ))}
          </ScrollView>
          {chat.suggestions.length > 0 ? (
            <SuggestedReplies
              replies={chat.suggestions}
              onSelect={(reply) => {
                // a suggested change to the card shown is a message about it
                if (chat.send(reply.label, { expectsWorkout: reply.expectsWorkout, about: chat.refined ?? undefined })) setAsking(false);
              }}
              style={{ paddingBottom: spacing.md, ...side }}
            />
          ) : null}
          <ChatComposer
            onSend={(text) => {
              const sent = chat.send(text);
              if (sent) setAsking(false);
              return sent;
            }}
            busy={busy}
            placeholder={asking ? ASK_PLACEHOLDER : undefined}
            focusSignal={focusSignal}
            style={side}
          />
        </KeyboardAvoidingView>
      </View>
      <CoachMenu visible={menuOpen} items={menu} onClose={() => setMenuOpen(false)} />
    </View>
  );
}

type ConversationItemProps = {
  item: ChatItem;
  // the whole conversation, for what a card must know of the others (which waiting workout is the newest)
  items: readonly ChatItem[];
  // the saved workout the conversation is about, if it is about one
  target: ChatTarget | null;
  onApply: () => void;
  onDismiss: () => void;
  onAskForChanges: () => void;
  onRetry: () => void;
  onReview: (proposalId: string) => void;
};

// One thing on the page: a message, a workout card, the workouts waiting from before to choose from, or the coach
// working on one or failing to.
function ConversationItem({ item, items, target, onApply, onDismiss, onAskForChanges, onRetry, onReview }: ConversationItemProps) {
  switch (item.kind) {
    case 'message':
      return <MessageBubble message={item} />;
    case 'proposal':
      return <ProposalItem item={item} items={items} target={target} onApply={onApply} onDismiss={onDismiss} onAskForChanges={onAskForChanges} />;
    case 'choice':
      return <WaitingProposals entries={item.entries} onReview={onReview} />;
    case 'pending':
      return item.expectsWorkout ? <WorkoutProposalCard state="loading" /> : <TypingBubble />;
    case 'failed':
      return item.expectsWorkout ? (
        <WorkoutProposalCard state="generation-failed" message={item.message} onRetry={item.retryable ? onRetry : undefined} />
      ) : (
        <FailureBubble message={item.message} onRetry={item.retryable ? onRetry : undefined} />
      );
  }
}

function ProposalItem({
  item,
  items,
  target,
  onApply,
  onDismiss,
  onAskForChanges,
}: {
  item: Extract<ChatItem, { kind: 'proposal' }>;
  items: readonly ChatItem[];
  target: ChatTarget | null;
  onApply: () => void;
  onDismiss: () => void;
  onAskForChanges: () => void;
}) {
  // only a saved plan has an id a proposal's revision can be checked against
  const targetId = target?.planId ?? null;
  const targetTitle = target?.title ?? '';
  // "Today" and "Tomorrow" mean what they did when the proposal arrived
  const card = useMemo(
    () => proposalCardData(item.proposal, new Date(), targetId === null ? null : { planId: targetId, title: targetTitle }),
    [item.proposal, targetId, targetTitle],
  );
  // The coach changes the newest waiting version of the workout the conversation is about. A card for an older version,
  // or for a workout that is not the one being edited, says why changes cannot be asked for here, rather than asking
  // for them and changing another workout.
  const newest = newestWaiting(items, item.proposal);
  const applicable = isApplicable(item.phase);
  const notTheTarget = applicable && target !== null && (item.proposal.revision?.replaces_plan_id ?? null) !== target.planId;
  const askUnavailable = !applicable
    ? null
    : notTheTarget
      ? `This isn't a change to “${target.title}”, which you're editing, so the coach can't change it here. It can only be applied or dismissed.`
      : !canAskForChanges(items, item, target) && newest
        ? `The coach changes your newest waiting workout, “${newest.name}”. This older one can only be applied or dismissed.`
        : null;
  const proposedAgo = item.recovered ? `Proposed ${agoLabel(item.recovered.createdAt, new Date()) ?? 'earlier'}` : null;
  return (
    <WorkoutProposalCard
      state="proposal"
      card={card}
      phase={item.phase}
      onApply={onApply}
      onAskForChanges={onAskForChanges}
      onDismiss={onDismiss}
      proposedAgo={proposedAgo}
      askUnavailable={askUnavailable}
    />
  );
}
