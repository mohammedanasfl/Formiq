import { Dimensions } from 'react-native';
import { fireEvent, screen, within } from '@testing-library/react-native';

import type { ProposalPhase } from '../src/coach/chatState';
import { proposalCardData, type ProposalCardData } from '../src/coach/proposalCard';
import { keyChangeText, type KeyChange } from '../src/coach/proposalChanges';
import { APPLY_LABEL, ASK_LABEL, DISMISS_LABEL, WorkoutProposalCard } from '../src/coach/WorkoutProposalCard';
import { localDateKey } from '../src/home/format';
import { mockIncompleteProposal, mockProposal, mockUncomparedProposal, mockWeightDropProposal } from '../src/mock/coachProposalsMock';
import { themes, type ThemeScheme } from '../src/theme';
import { renderWithTheme } from '../test-utils/renderWithTheme';

const dark = themes.dark.colors;
const light = themes.light.colors;
const NOW = new Date(2026, 9, 22, 9, 0, 0);

// a day far from any "today", so the caption names it
const applied = (planId: number, scheduledDate: string | null = '2030-03-05'): ProposalPhase => ({ kind: 'applied', planId, name: 'Core Stability & Abs', scheduledDate });
const NEW: ProposalCardData = proposalCardData(mockProposal('new', NOW, 1), NOW);
const UPDATED: ProposalCardData = proposalCardData(mockProposal('edit', NOW, 2), NOW);
// the backend could not compare it with the saved workout
const UNREAD: ProposalCardData = proposalCardData(mockUncomparedProposal(NOW, 2), NOW);
const REFINED: ProposalCardData = proposalCardData(mockProposal('edit-refined', NOW, 3), NOW);
const WEIGHTED: ProposalCardData = proposalCardData(mockWeightDropProposal(NOW, 5), NOW);
const INCOMPLETE: ProposalCardData = proposalCardData(mockIncompleteProposal(NOW, 4), NOW);

const READY: ProposalPhase = { kind: 'ready' };
const RETRYABLE = { kind: 'apply-failed', failure: { message: "Can't reach Formiq. Check your connection and try again.", retryable: true } } as const;
const FINAL = { kind: 'apply-failed', failure: { message: 'This proposal has expired. Ask the coach for a new one.', retryable: false } } as const;

// A phone about 411 dp wide: with a font scale of 1 the three sections fit as columns. (The test renderer's own
// window has a font scale of 2, which is large enough to stack them.)
beforeEach(() => {
  Dimensions.set({ window: { width: 411, height: 890, scale: 2.6, fontScale: 1 }, screen: { width: 411, height: 890, scale: 2.6, fontScale: 1 } });
});

async function renderCard(
  card: ProposalCardData,
  phase: ProposalPhase = READY,
  scheme: ThemeScheme = 'dark',
  extra: { proposedAgo?: string | null; askUnavailable?: string | null } = {},
) {
  const onApply = jest.fn();
  const onAskForChanges = jest.fn();
  const onDismiss = jest.fn();
  const view = await renderWithTheme(
    <WorkoutProposalCard state="proposal" card={card} phase={phase} onApply={onApply} onAskForChanges={onAskForChanges} onDismiss={onDismiss} {...extra} />,
    scheme,
  );
  return { ...view, onApply, onAskForChanges, onDismiss };
}

const button = (name: string) => screen.getByRole('button', { name });
const status = () => within(screen.getByTestId('proposal-status'));

describe('a new workout', () => {
  test('is labelled New Workout and shows the title, what the proposal says of it, its length and its exercises', async () => {
    await renderCard(NEW);

    status().getByText('New Workout');
    screen.getByRole('header', { name: 'Upper Body Strength' });
    screen.getByText('Upper body focus • Today');
    screen.getByText('24 min');
    screen.getByText('8 exercises');
  });

  test('has a picture of its kind with its focus over it', async () => {
    await renderCard(NEW);

    const photo = screen.getByTestId('proposal-photo', { includeHiddenElements: true });
    expect(within(photo).getByText('Upper body', { includeHiddenElements: true })).toBeOnTheScreen();
  });

  test('has the three sections, each with its exercises and minutes', async () => {
    await renderCard(NEW);

    button('Warm-up, 2 exercises, 2 min');
    button('Main Workout, 4 exercises, 21 min');
    button('Cool-down, 2 exercises, 1 min');
  });

  test('has no Key Changes: there is nothing it replaces', async () => {
    await renderCard(NEW);

    expect(screen.queryByTestId('key-changes')).toBeNull();
    expect(screen.queryByText('Key Changes')).toBeNull();
  });

  test('has the three actions, and says it is not saved yet', async () => {
    await renderCard(NEW);

    expect(button('Apply This Workout')).toBeEnabled();
    expect(button('Ask for More Changes')).toBeEnabled();
    expect(button('Dismiss')).toBeEnabled();
    expect(screen.getByTestId('proposal-caption')).toHaveTextContent("Not saved yet. It's added to your plan when you apply it.");
  });

  test('shows no difficulty and no description: the proposal has neither', async () => {
    await renderCard(NEW);

    expect(screen.queryByText(/moderate|beginner|intermediate|advanced|difficulty/i)).toBeNull();
  });

  test('Apply applies, Ask for More Changes asks for changes and Dismiss dismisses, and none does another\'s job', async () => {
    const { onApply, onAskForChanges, onDismiss } = await renderCard(NEW);

    await fireEvent.press(button('Apply This Workout'));
    expect(onApply).toHaveBeenCalledTimes(1);
    expect(onAskForChanges).not.toHaveBeenCalled();
    expect(onDismiss).not.toHaveBeenCalled();

    await fireEvent.press(button('Ask for More Changes'));
    expect(onAskForChanges).toHaveBeenCalledTimes(1);
    expect(onApply).toHaveBeenCalledTimes(1);

    await fireEvent.press(button('Dismiss'));
    expect(onDismiss).toHaveBeenCalledTimes(1);
    expect(onApply).toHaveBeenCalledTimes(1);
    expect(onAskForChanges).toHaveBeenCalledTimes(1);
  });
});

test('the labels of the three actions are the ones the card names', () => {
  expect([APPLY_LABEL.new, APPLY_LABEL.updated, ASK_LABEL, DISMISS_LABEL]).toEqual(['Apply This Workout', 'Apply Updated Workout', 'Ask for More Changes', 'Dismiss']);
});

describe('an updated workout', () => {
  test('is labelled Updated Workout and offers Apply Updated Workout', async () => {
    await renderCard(UPDATED);

    status().getByText('Updated Workout');
    expect(button('Apply Updated Workout')).toBeEnabled();
    expect(screen.queryByRole('button', { name: 'Apply This Workout' })).toBeNull();
    expect(button('Ask for More Changes')).toBeEnabled();
  });

  test('has the same layout as a new one: the same pieces, only the label, the content and the action differ', async () => {
    const view = await renderCard(NEW);
    const layoutOf = () => [
      screen.getByTestId('proposal-photo', { includeHiddenElements: true }),
      screen.getByTestId('proposal-sections'),
      screen.getByTestId('apply-button'),
      screen.getByTestId('ask-button'),
      screen.getByTestId('dismiss-button'),
      screen.getByTestId('proposal-caption'),
    ].map((node) => node.type);
    const newLayout = layoutOf();
    await view.unmount();

    await renderCard(UPDATED);

    expect(layoutOf()).toEqual(newLayout);
    expect(APPLY_LABEL).toEqual({ new: 'Apply This Workout', updated: 'Apply Updated Workout' });
    expect(ASK_LABEL).toBe('Ask for More Changes');
  });

  test("lists the key changes the backend found by comparing it with the saved workout, and what it keeps", async () => {
    await renderCard(UPDATED);

    const changes = within(screen.getByTestId('key-changes'));
    changes.getByRole('header', { name: 'Key Changes' });
    changes.getByText('Replaced Bicycle Crunches with Dead Bug');
    changes.getByText('Replaced Leg Raises with Side Plank');
    changes.getByText('Plank: 30 s → 40 s');
    changes.getByText('Kept from your workout: Plank.');
  });

  test('says the duration stayed, because the backend said how long the saved workout takes and it is the same', async () => {
    await renderCard(UPDATED);

    within(screen.getByTestId('key-changes')).getByText('Kept the same duration (18 min)');
  });

  test('says a weight the saved workout has and this one drops', async () => {
    await renderCard(WEIGHTED);

    within(screen.getByTestId('key-changes')).getByText('Goblet Squat: 20 kg → no weight');
  });

  test('lists the key changes of the latest version against the original', async () => {
    await renderCard(REFINED);

    const changes = within(screen.getByTestId('key-changes'));
    changes.getByText('Replaced Mountain Climbers with Cat-Cow Stretch in the warm-up');
    changes.getByText('Replaced Lunges with Glute Bridge in the warm-up');
    changes.getByText('Replaced Bicycle Crunches with Dead Bug');
    changes.getByText('Replaced Leg Raises with Reverse Crunch');
    expect(changes.queryByText(/Plank:/)).toBeNull();
  });

  test('says the saved workout stays as it is until this one is applied', async () => {
    await renderCard(UPDATED);

    expect(screen.getByTestId('proposal-caption')).toHaveTextContent('Applying replaces “Core & Abs Focus”. Until then it stays as it is.');
  });

  test('says so, and lists nothing, when the backend could not compare it with the saved workout', async () => {
    await renderCard(UNREAD);

    const changes = within(screen.getByTestId('key-changes'));
    expect(screen.getByTestId('key-changes-unavailable')).toHaveTextContent("Formiq couldn't compare this with “Core & Abs Focus”, so the changes aren't listed.");
    expect(changes.queryByText(/Replaced|Added|Removed|duration/)).toBeNull();
    // what the backend itself says it keeps is still said
    changes.getByText('Kept from your workout: Plank.');
    expect(button('Apply Updated Workout')).toBeEnabled();
  });

  test('says when nothing differs, and does not make a change up', async () => {
    const same = { ...UPDATED, keyChanges: [], keyChangeLines: [] };

    await renderCard(same);

    within(screen.getByTestId('key-changes')).getByText('No exercise changes found.');
  });

  // a proposal whose exercises are all as the saved workout has them (the backend says identical: true), with the day or the name flagged
  const sameExercises = (overrides: Partial<NonNullable<ReturnType<typeof mockProposal>['changes']>>, proposal: Partial<ReturnType<typeof mockProposal>> = {}) => {
    const edit = mockProposal('edit', NOW, 2);
    return proposalCardData(
      {
        ...edit,
        ...proposal,
        changes: { ...edit.changes!, added: [], removed: [], changed: [], unchanged: edit.exercises.map((exercise) => exercise.exercise_name), name_changed: false, scheduled_date_changed: false, identical: true, ...overrides },
      },
      NOW,
    );
  };

  test('a proposal that only moves the day shows the move and does not say nothing changed', async () => {
    await renderCard(sameExercises({ scheduled_date_changed: true, compared_with_scheduled_date: '2026-10-21' }, { name: 'Core & Abs Focus', scheduled_date: '2026-10-23' }));

    const changes = within(screen.getByTestId('key-changes'));
    changes.getByText('Moved from Wed, 21 Oct to Fri, 23 Oct');
    expect(changes.queryByText(/No exercise changes|no changes|identical|nothing changed/i)).toBeNull();
    // and it is still an updated workout that can be applied
    status().getByText('Updated Workout');
    expect(button('Apply Updated Workout')).toBeEnabled();
  });

  test('a proposal that only moves the day, with the length not known, still shows the move (the list is not empty)', async () => {
    const edit = mockProposal('edit', NOW, 2);
    const unknownLength = { ...edit, revision: edit.revision && { ...edit.revision, replaces_plan_estimated_minutes: null } };
    await renderCard(
      proposalCardData(
        {
          ...unknownLength,
          name: 'Core & Abs Focus',
          scheduled_date: '2026-10-23',
          changes: { ...edit.changes!, added: [], removed: [], changed: [], unchanged: [], name_changed: false, scheduled_date_changed: true, compared_with_scheduled_date: '2026-10-21', identical: true },
        },
        NOW,
      ),
    );

    const changes = within(screen.getByTestId('key-changes'));
    changes.getByText('Moved from Wed, 21 Oct to Fri, 23 Oct');
    expect(changes.queryByText('No exercise changes found.')).toBeNull();
  });

  test('a proposal that only renames the workout shows the rename', async () => {
    await renderCard(sameExercises({ name_changed: true }));

    const changes = within(screen.getByTestId('key-changes'));
    changes.getByText('Renamed from “Core & Abs Focus” to “Core Stability & Abs”');
    expect(changes.queryByText('No exercise changes found.')).toBeNull();
  });

  test('a change of weight alone is listed with the real before and after, and the weight is on the exercise\'s row', async () => {
    const edit = mockProposal('edit', NOW, 2);
    const plank = edit.exercises.find((exercise) => exercise.exercise_name === 'Plank')!;
    const before = { sets: 3, reps: null, duration_seconds: 40, rest_seconds: 45, weight_kg: 15, summary: '3 sets of 40 s at 15 kg, 45 s rest' };
    const after = { ...before, weight_kg: 20, summary: '3 sets of 40 s at 20 kg, 45 s rest' };
    await renderCard(
      proposalCardData(
        {
          ...edit,
          exercises: edit.exercises.map((exercise) => (exercise === plank ? { ...exercise, weight_kg: 20 } : exercise)),
          changes: {
            ...edit.changes!,
            added: [],
            removed: [],
            changed: [{ section: 'MAIN_WORKOUT', exercise_name: 'Plank', before, after }],
            unchanged: edit.exercises.filter((exercise) => exercise !== plank).map((exercise) => exercise.exercise_name),
            name_changed: false,
            identical: false,
          },
        },
        NOW,
      ),
    );

    within(screen.getByTestId('key-changes')).getByText('Plank: 15 kg → 20 kg');
    await fireEvent.press(screen.getByTestId('proposal-section-MAIN_WORKOUT'));
    const main = within(screen.getByTestId('proposal-exercises-MAIN_WORKOUT'));
    main.getByText('3 sets • 40 seconds • 20 kg • 45 s rest');
    expect(main.getAllByText('Changed')).toHaveLength(1);
  });

  test('says when nothing differs (no exercise, no name, no day), and does not make a change up', async () => {
    const same = sameExercises({ identical: false });
    const nothing = { ...same, keyChanges: [], keyChangeLines: [] };

    await renderCard(nothing);

    within(screen.getByTestId('key-changes')).getByText('No exercise changes found.');
  });

  // the card's lists are one list: a line for each change (proposalCard.ts)
  const withChanges = (keyChanges: KeyChange[]): ProposalCardData => ({ ...UPDATED, keyChanges, keyChangeLines: keyChanges.map(keyChangeText) });
  const addedExercise = (index: number): KeyChange => ({ kind: 'added', section: 'MAIN_WORKOUT', name: `Exercise ${index}` });

  test('lists the first few changes and counts the rest', async () => {
    await renderCard(withChanges(Array.from({ length: 9 }, (_, index) => addedExercise(index + 1))));

    const changes = within(screen.getByTestId('key-changes'));
    changes.getByText('Added Exercise 6 to the main workout');
    expect(changes.queryByText('Added Exercise 7 to the main workout')).toBeNull();
    changes.getByText('and 3 more');
  });

  test('a change of day is listed even when there are more changes than room (Phase 2.6)', async () => {
    const day: KeyChange = { kind: 'date', before: '2026-10-21', after: '2026-10-23' };
    await renderCard(withChanges([...Array.from({ length: 8 }, (_, index) => addedExercise(index + 1)), day]));

    const changes = within(screen.getByTestId('key-changes'));
    changes.getByText('Moved from Wed, 21 Oct to Fri, 23 Oct');
    changes.getByText('Added Exercise 5 to the main workout');
    // the day took the sixth place: the sixth exercise is counted with the rest
    expect(changes.queryByText('Added Exercise 6 to the main workout')).toBeNull();
    changes.getByText('and 3 more');
  });

  test('with room for every change, the day is listed in its place and nothing is counted', async () => {
    const day: KeyChange = { kind: 'date', before: '2026-10-21', after: '2026-10-23' };
    await renderCard(withChanges([addedExercise(1), addedExercise(2), day]));

    const changes = within(screen.getByTestId('key-changes'));
    changes.getByText('Moved from Wed, 21 Oct to Fri, 23 Oct');
    expect(changes.queryByText(/more$/)).toBeNull();
  });

  test('a name that only decorates the saved one is not listed, and a different one is', async () => {
    await renderCard(sameExercises({ name_changed: true }, { name: 'Core & Abs Focus (Harder)' }));
    within(screen.getByTestId('key-changes')).getByText('Kept the same duration (18 min)');
    expect(screen.queryByText(/Renamed from/)).toBeNull();
  });
});

describe('the sections open on their exercises', () => {
  test('are closed to begin with, and open one at a time, each marked open for a screen reader', async () => {
    await renderCard(UPDATED);
    expect(screen.queryByTestId('proposal-exercises-MAIN_WORKOUT')).toBeNull();
    expect(screen.getByTestId('proposal-section-MAIN_WORKOUT')).toHaveProp('accessibilityState', expect.objectContaining({ expanded: false }));

    await fireEvent.press(screen.getByTestId('proposal-section-MAIN_WORKOUT'));
    expect(screen.getByTestId('proposal-section-MAIN_WORKOUT')).toHaveProp('accessibilityState', expect.objectContaining({ expanded: true }));
    const main = within(screen.getByTestId('proposal-exercises-MAIN_WORKOUT'));
    main.getByText('Plank');
    main.getByText('3 sets • 40 seconds • 45 s rest');

    await fireEvent.press(screen.getByTestId('proposal-section-WARM_UP'));
    expect(screen.queryByTestId('proposal-exercises-MAIN_WORKOUT')).toBeNull();
    within(screen.getByTestId('proposal-exercises-WARM_UP')).getByText('Mountain Climbers');

    await fireEvent.press(screen.getByTestId('proposal-section-WARM_UP'));
    expect(screen.queryByTestId('proposal-exercises-WARM_UP')).toBeNull();
  });

  test('mark an exercise that is new, or prescribed differently, against the saved workout', async () => {
    await renderCard(UPDATED);
    await fireEvent.press(screen.getByTestId('proposal-section-MAIN_WORKOUT'));

    const main = within(screen.getByTestId('proposal-exercises-MAIN_WORKOUT'));
    expect(main.getAllByText('New')).toHaveLength(2);
    expect(main.getAllByText('Changed')).toHaveLength(1);
  });

  test('show an exercise\'s weight in kilograms in its row, and leave the row as it was when it has none', async () => {
    const proposal = mockProposal('new', NOW, 1);
    const weighted = {
      ...proposal,
      exercises: proposal.exercises.map((exercise) => (exercise.exercise_name === 'Dumbbell Shoulder Press' ? { ...exercise, weight_kg: 20 } : exercise)),
    };
    await renderCard(proposalCardData(weighted, NOW));
    await fireEvent.press(screen.getByTestId('proposal-section-MAIN_WORKOUT'));

    const main = within(screen.getByTestId('proposal-exercises-MAIN_WORKOUT'));
    main.getByText('3 sets • 10 reps • 20 kg • 60 s rest');
    // the others have no weight: their rows say what they always did, and no "kg" is anywhere else
    expect(main.getAllByText('3 sets • 12 reps • 60 s rest')).toHaveLength(3);
    expect(main.getAllByText(/ kg/)).toHaveLength(1);
  });

  test('mark nothing on a new workout, and show each exercise\'s equipment or Bodyweight', async () => {
    await renderCard(NEW);
    await fireEvent.press(screen.getByTestId('proposal-section-MAIN_WORKOUT'));

    const main = within(screen.getByTestId('proposal-exercises-MAIN_WORKOUT'));
    expect(main.queryByText('New')).toBeNull();
    expect(main.queryByText('Changed')).toBeNull();
    expect(main.getAllByText('Dumbbell')).toHaveLength(3);
    expect(main.getAllByText('Bodyweight')).toHaveLength(1);
  });

  test('fit as columns on a wide card, and stack as rows on a narrow one', async () => {
    await renderCard(NEW);
    const sections = screen.getByTestId('proposal-sections');
    // the card's inner width as laid out: three columns need about 108 dp each
    const resize = (width: number) => {
      let node = sections.parent;
      while (node && !node.props.onLayout) node = node.parent;
      return fireEvent(node!, 'layout', { nativeEvent: { layout: { x: 0, y: 0, width, height: 200 } } });
    };

    await resize(351);
    expect(screen.getByTestId('proposal-sections')).toHaveStyle({ flexDirection: 'row' });

    await resize(300);
    expect(screen.getByTestId('proposal-sections')).toHaveStyle({ flexDirection: 'column' });
  });

  test('stack as rows whatever the width when the text is set large', async () => {
    Dimensions.set({ window: { width: 411, height: 890, scale: 2.6, fontScale: 1.5 }, screen: { width: 411, height: 890, scale: 2.6, fontScale: 1.5 } });
    await renderCard(NEW);
    let node = screen.getByTestId('proposal-sections').parent;
    while (node && !node.props.onLayout) node = node.parent;

    await fireEvent(node!, 'layout', { nativeEvent: { layout: { x: 0, y: 0, width: 400, height: 200 } } });

    expect(screen.getByTestId('proposal-sections')).toHaveStyle({ flexDirection: 'column' });
  });
});

describe('applying', () => {
  test('shows the apply as under way, takes every button out of use, and ignores a press', async () => {
    const { onApply, onAskForChanges, onDismiss } = await renderCard(UPDATED, { kind: 'applying' });

    const apply = button('Applying…');
    expect(apply).toBeDisabled();
    expect(button('Ask for More Changes')).toBeDisabled();
    expect(button('Dismiss')).toBeDisabled();
    await fireEvent.press(apply);
    await fireEvent.press(button('Ask for More Changes'));
    await fireEvent.press(button('Dismiss'));
    expect(onApply).not.toHaveBeenCalled();
    expect(onAskForChanges).not.toHaveBeenCalled();
    expect(onDismiss).not.toHaveBeenCalled();
  });

  test('still says it is Updated Workout and still not saved: it is not applied until the backend says so', async () => {
    await renderCard(UPDATED, { kind: 'applying' });

    status().getByText('Updated Workout');
    expect(status().queryByText('Applied')).toBeNull();
    expect(screen.getByTestId('proposal-caption')).toHaveTextContent(/Until then it stays as it is\./);
  });
});

describe('applied', () => {
  test('says Applied, with the apply taken out of use, and no longer offers to ask for changes or to dismiss it', async () => {
    const { onApply } = await renderCard(UPDATED, applied(100));

    status().getByText('Applied');
    const apply = button('Applied');
    expect(apply).toBeDisabled();
    await fireEvent.press(apply);
    expect(onApply).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Ask for More Changes' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Dismiss' })).toBeNull();
  });

  test('is no longer drawn as a pending proposal: no apply label, no "not saved", no "until then"', async () => {
    await renderCard(UPDATED, applied(100));

    expect(screen.queryByText('Apply Updated Workout')).toBeNull();
    expect(screen.queryByText('Updated Workout')).toBeNull();
    expect(screen.queryByText(/not saved|Until then|stays as it is/i)).toBeNull();
  });

  // what the backend confirmed, in its own words: the saved plan's name and day, and the one it replaced
  test('says what was replaced and by what for an update, and that it was added for a new workout, with the saved day', async () => {
    const view = await renderCard(UPDATED, applied(100));
    expect(screen.getByTestId('proposal-caption')).toHaveTextContent('Replaced “Core & Abs Focus” with “Core Stability & Abs” for Tue, 5 Mar.');
    await view.unmount();

    await renderCard(NEW, applied(101));
    expect(screen.getByTestId('proposal-caption')).toHaveTextContent('Added “Core Stability & Abs” to your plan for Tue, 5 Mar.');
  });

  test('says "today" and "tomorrow" for those days, and leaves the day out when the backend gave none', async () => {
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    const view = await renderCard(NEW, applied(100, localDateKey(new Date())));
    expect(screen.getByTestId('proposal-caption')).toHaveTextContent('Added “Core Stability & Abs” to your plan for today.');
    await view.unmount();

    const next = await renderCard(NEW, applied(100, localDateKey(tomorrow)));
    expect(screen.getByTestId('proposal-caption')).toHaveTextContent(/to your plan for tomorrow\.$/);
    await next.unmount();

    await renderCard(NEW, applied(100, null));
    expect(screen.getByTestId('proposal-caption')).toHaveTextContent('Added “Core Stability & Abs” to your plan.');
  });
});

describe('apply failed', () => {
  test('keeps the proposal, says why in an alert, and offers to try again when trying again can help', async () => {
    const { onApply } = await renderCard(UPDATED, RETRYABLE);

    const error = screen.getByTestId('apply-error');
    expect(error).toHaveProp('accessibilityRole', 'alert');
    within(error).getByText("Couldn't apply this workout");
    within(error).getByText("Can't reach Formiq. Check your connection and try again.");
    status().getByText('Updated Workout');
    screen.getByRole('header', { name: 'Core Stability & Abs' });
    within(screen.getByTestId('key-changes')).getByText('Replaced Bicycle Crunches with Dead Bug');

    await fireEvent.press(button('Try Again'));
    expect(onApply).toHaveBeenCalledTimes(1);
  });

  test('does not say it was applied or saved', async () => {
    await renderCard(UPDATED, RETRYABLE);

    expect(status().queryByText('Applied')).toBeNull();
    expect(screen.queryByText(/was applied|has been applied|was saved|has been saved/i)).toBeNull();
  });

  test('when the proposal itself is the problem, the apply stays out of use and asking for changes is the way on', async () => {
    const { onApply, onAskForChanges } = await renderCard(UPDATED, FINAL);

    within(screen.getByTestId('apply-error')).getByText('This proposal has expired. Ask the coach for a new one.');
    const apply = button('Apply Updated Workout');
    expect(apply).toBeDisabled();
    await fireEvent.press(apply);
    expect(onApply).not.toHaveBeenCalled();
    await fireEvent.press(button('Ask for More Changes'));
    expect(onAskForChanges).toHaveBeenCalledTimes(1);
    // there is nothing left to dismiss: the backend has refused it for good
    expect(screen.queryByRole('button', { name: 'Dismiss' })).toBeNull();
  });

  test('a failure that can be tried again still offers to dismiss it', async () => {
    const { onDismiss } = await renderCard(UPDATED, RETRYABLE);

    await fireEvent.press(button('Dismiss'));

    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});

describe('being dismissed', () => {
  test('shows the dismissal as under way, takes every button out of use and ignores a press: it is not dismissed until the backend says so', async () => {
    const { onApply, onAskForChanges, onDismiss } = await renderCard(UPDATED, { kind: 'rejecting' });

    const dismiss = button('Dismissing…');
    expect(dismiss).toBeDisabled();
    expect(button('Ask for More Changes')).toBeDisabled();
    expect(button('Apply Updated Workout')).toBeDisabled();
    await fireEvent.press(dismiss);
    await fireEvent.press(button('Apply Updated Workout'));
    expect(onDismiss).not.toHaveBeenCalled();
    expect(onApply).not.toHaveBeenCalled();
    expect(onAskForChanges).not.toHaveBeenCalled();
    status().getByText('Updated Workout');
    expect(status().queryByText('Dismissed')).toBeNull();
    expect(screen.getByTestId('proposal-caption')).toHaveTextContent(/Until then it stays as it is\./);
  });
});

describe('dismissed', () => {
  test('says Dismissed and that nothing was saved, and offers nothing more: no apply, no changes, no dismiss', async () => {
    await renderCard(NEW, { kind: 'rejected' });

    status().getByText('Dismissed');
    expect(screen.getByTestId('proposal-note')).toHaveTextContent('Dismissed. Nothing was saved.');
    expect(screen.queryByRole('button', { name: /Apply|Ask for|Dismiss|Try/ })).toBeNull();
    expect(screen.queryByText(/Apply|not saved yet/i)).toBeNull();
  });

  test('for an updated workout says the saved one is as it was', async () => {
    await renderCard(UPDATED, { kind: 'rejected' });

    expect(screen.getByTestId('proposal-note')).toHaveTextContent('Dismissed. Nothing was saved, and “Core & Abs Focus” is as it was.');
    expect(screen.queryByTestId('off-target-note')).toBeNull();
  });

  test('is not drawn as pending, applied or saved', async () => {
    await renderCard(UPDATED, { kind: 'rejected' });

    expect(status().queryByText('Updated Workout')).toBeNull();
    expect(status().queryByText('Applied')).toBeNull();
    // it says that nothing was saved, and never that something was
    expect(screen.queryByText(/was applied|has been applied|has been saved|(?<!nothing )was saved/i)).toBeNull();
  });
});

describe('no longer waiting', () => {
  test('says the backend does not have it any more, without calling it dismissed, and offers nothing more', async () => {
    await renderCard(UPDATED, { kind: 'expired' });

    status().getByText('No longer waiting');
    expect(screen.getByTestId('proposal-note')).toHaveTextContent('This workout is no longer waiting: it expired. Ask the coach for a new one.');
    expect(status().queryByText('Dismissed')).toBeNull();
    expect(screen.queryByRole('button', { name: /Apply|Ask for|Dismiss|Try/ })).toBeNull();
  });
});

describe('a dismissal that failed', () => {
  const FAILED = { kind: 'reject-failed', failure: { message: "Can't reach Formiq. Check your connection and try again.", retryable: true } } as const;
  const SETTLED = { kind: 'reject-failed', failure: { message: 'This workout was already applied or changed. Check your plans.', retryable: false } } as const;

  test('keeps the workout, says why in an alert, and offers to dismiss again, and still to apply or ask for changes', async () => {
    const { onDismiss, onApply } = await renderCard(UPDATED, FAILED);

    const error = screen.getByTestId('dismiss-error');
    expect(error).toHaveProp('accessibilityRole', 'alert');
    within(error).getByText("Couldn't dismiss this workout");
    within(error).getByText("Can't reach Formiq. Check your connection and try again.");
    status().getByText('Updated Workout');
    within(screen.getByTestId('key-changes')).getByText('Replaced Bicycle Crunches with Dead Bug');
    expect(button('Apply Updated Workout')).toBeEnabled();
    expect(button('Ask for More Changes')).toBeEnabled();

    await fireEvent.press(button('Dismiss Again'));
    expect(onDismiss).toHaveBeenCalledTimes(1);
    await fireEvent.press(button('Apply Updated Workout'));
    expect(onApply).toHaveBeenCalledTimes(1);
  });

  test('does not say it was dismissed', async () => {
    await renderCard(UPDATED, FAILED);

    expect(status().queryByText('Dismissed')).toBeNull();
    expect(screen.queryByText(/was dismissed|has been dismissed/i)).toBeNull();
  });

  test('when the backend says it was applied or changed, nothing more is offered to do with it but ask the coach', async () => {
    const { onApply, onDismiss } = await renderCard(UPDATED, SETTLED);

    within(screen.getByTestId('dismiss-error')).getByText('This workout was already applied or changed. Check your plans.');
    expect(button('Apply Updated Workout')).toBeDisabled();
    expect(screen.queryByRole('button', { name: /Dismiss/ })).toBeNull();
    await fireEvent.press(button('Apply Updated Workout'));
    expect(onApply).not.toHaveBeenCalled();
    expect(onDismiss).not.toHaveBeenCalled();
    expect(status().queryByText('Applied')).toBeNull();
    expect(status().queryByText('Dismissed')).toBeNull();
  });
});

describe('a workout that was waiting from before the conversation', () => {
  test('says when it was proposed, and is otherwise the same card with the same actions', async () => {
    await renderCard(UPDATED, READY, 'dark', { proposedAgo: 'Proposed 12 min ago' });

    expect(screen.getByTestId('proposal-recovered')).toHaveTextContent('Proposed 12 min ago');
    expect(button('Apply Updated Workout')).toBeEnabled();
    expect(button('Ask for More Changes')).toBeEnabled();
    expect(button('Dismiss')).toBeEnabled();
    status().getByText('Updated Workout');
  });

  test('says nothing of the sort for a workout the coach just made', async () => {
    await renderCard(UPDATED);

    expect(screen.queryByTestId('proposal-recovered')).toBeNull();
  });

  test('an older one, which the coach would not change, says why instead of offering to ask for changes, and can still be applied or dismissed', async () => {
    const reason = 'The coach changes your newest waiting workout, “Gentle Core & Abs”. This older one can only be applied or dismissed.';
    const { onApply, onDismiss } = await renderCard(UPDATED, READY, 'dark', { proposedAgo: 'Proposed 12 min ago', askUnavailable: reason });

    expect(screen.queryByRole('button', { name: 'Ask for More Changes' })).toBeNull();
    expect(screen.getByTestId('ask-unavailable')).toHaveTextContent(reason);
    await fireEvent.press(button('Apply Updated Workout'));
    await fireEvent.press(button('Dismiss'));
    expect(onApply).toHaveBeenCalledTimes(1);
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  test('says nothing of changes once it has been applied or dismissed', async () => {
    const view = await renderCard(UPDATED, applied(100), 'dark', { askUnavailable: 'x' });
    expect(screen.queryByTestId('ask-unavailable')).toBeNull();
    await view.unmount();

    await renderCard(UPDATED, { kind: 'rejected' }, 'dark', { askUnavailable: 'x' });
    expect(screen.queryByTestId('ask-unavailable')).toBeNull();
  });
});

describe('an older version', () => {
  test('says so, says where the newer one is, and offers no action', async () => {
    await renderCard(UPDATED, { kind: 'superseded', reason: 'newer-version' });

    status().getByText('Older version');
    expect(screen.getByTestId('proposal-note')).toHaveTextContent('The coach made a newer version of this workout. Use the one below.');
    expect(screen.queryByRole('button', { name: /Apply|Ask for More/ })).toBeNull();
  });

  test('says when another version of the same workout was applied', async () => {
    await renderCard(UPDATED, { kind: 'superseded', reason: 'workout-replaced' });

    expect(screen.getByTestId('proposal-note')).toHaveTextContent('Another version of this workout was applied, so this one can no longer be.');
  });
});

describe('loading', () => {
  test('has the shape of the card, says the workout is being prepared, and has no button', async () => {
    await renderWithTheme(<WorkoutProposalCard state="loading" />);

    screen.getByLabelText('Preparing your workout');
    expect(screen.getByTestId('proposal-loading')).toHaveProp('accessibilityLiveRegion', 'polite');
    expect(screen.queryByRole('button')).toBeNull();
    expect(screen.queryByText(/Apply|New Workout|Updated Workout/)).toBeNull();
  });
});

describe('the workout could not be made', () => {
  test('says so, why, and offers to try again, which asks for it again', async () => {
    const onRetry = jest.fn();
    await renderWithTheme(<WorkoutProposalCard state="generation-failed" message="Can't reach Formiq. Check your connection and try again." onRetry={onRetry} />);

    status().getByText("Couldn't create the workout");
    screen.getByText("Can't reach Formiq. Check your connection and try again.");
    expect(screen.queryByRole('button', { name: /Apply/ })).toBeNull();

    await fireEvent.press(button('Try Again'));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});

describe('the workout could not be made, and asking again cannot help', () => {
  test('says why and offers no Try Again: an expired session would only fail again', async () => {
    await renderWithTheme(<WorkoutProposalCard state="generation-failed" message="Your session has expired. Log in again." />);

    screen.getByText('Your session has expired. Log in again.');
    expect(screen.queryByRole('button', { name: 'Try Again' })).toBeNull();
    expect(screen.queryByRole('button', { name: /Apply/ })).toBeNull();
  });
});

describe('a workout that replaces a different one than the coach was opened from', () => {
  const OTHER = proposalCardData(mockProposal('edit', NOW, 2), NOW, { planId: 99, title: 'Leg Day' });

  test('says which workout it replaces and which one the coach was opened from, before it can be applied', async () => {
    await renderCard(OTHER);

    const note = within(screen.getByTestId('off-target-note'));
    note.getByText('A different workout');
    note.getByText('This replaces “Core & Abs Focus”, not “Leg Day”, which you opened the coach from.');
  });

  test('says nothing when it replaces the workout the coach was opened from, or when it is a new workout', async () => {
    const same = proposalCardData(mockProposal('edit', NOW, 2), NOW, { planId: 41, title: 'Core & Abs Focus' });
    const view = await renderCard(same);
    expect(screen.queryByTestId('off-target-note')).toBeNull();
    await view.unmount();

    await renderCard(NEW);
    expect(screen.queryByTestId('off-target-note')).toBeNull();
  });

  test('is dropped once the workout is applied or replaced by a newer one: it is no longer a question', async () => {
    const view = await renderCard(OTHER, applied(100));
    expect(screen.queryByTestId('off-target-note')).toBeNull();
    await view.unmount();

    const dismissed = await renderCard(OTHER, { kind: 'rejected' });
    expect(screen.queryByTestId('off-target-note')).toBeNull();
    await dismissed.unmount();

    await renderCard(OTHER, { kind: 'superseded', reason: 'newer-version' });
    expect(screen.queryByTestId('off-target-note')).toBeNull();
  });

  test('is still said for a workout that waited from before: it is the one to be careful with', async () => {
    await renderCard(OTHER, READY, 'dark', { proposedAgo: 'Proposed 3 min ago' });

    screen.getByTestId('off-target-note');
  });
});

describe('a workout the catalog could not fully cover', () => {
  test('says what is missing, in the backend\'s words, and can still be applied', async () => {
    await renderCard(INCOMPLETE);

    const note = screen.getByTestId('coverage-note');
    within(note).getByText('Not a complete workout');
    within(note).getByText("Formiq's catalog has no pulling exercise you can do without a pull-up bar.");
    expect(button('Apply This Workout')).toBeEnabled();
  });

  test('has no such note when the workout is complete', async () => {
    await renderCard(NEW);

    expect(screen.queryByTestId('coverage-note')).toBeNull();
  });
});

describe.each([
  ['dark', dark],
  ['light', light],
] as const)('the %s theme', (scheme, colors) => {
  test('draws the card on the surface with the theme\'s outline, and the label in the accent', async () => {
    await renderCard(UPDATED, READY, scheme);

    expect(screen.getByTestId('proposal-card')).toHaveStyle({ backgroundColor: colors.surface, borderColor: colors.border });
    expect(within(screen.getByTestId('proposal-status')).getByText('Updated Workout')).toHaveStyle({ color: colors.accent });
    expect(screen.getByTestId('key-changes')).toHaveStyle({ backgroundColor: colors.primarySubtle });
  });

  test('draws Applied in the success color', async () => {
    await renderCard(UPDATED, applied(1), scheme);

    expect(within(screen.getByTestId('proposal-status')).getByText('Applied')).toHaveStyle({ color: colors.success });
  });

  test('draws a failure to apply in the error color', async () => {
    await renderCard(UPDATED, RETRYABLE, scheme);

    expect(within(screen.getByTestId('apply-error')).getByText("Couldn't apply this workout")).toHaveStyle({ color: colors.error });
  });

  test('draws a failure to dismiss in the error color', async () => {
    await renderCard(UPDATED, { kind: 'reject-failed', failure: { message: 'x', retryable: true } }, scheme);

    expect(within(screen.getByTestId('dismiss-error')).getByText("Couldn't dismiss this workout")).toHaveStyle({ color: colors.error });
  });

  test('draws Dismissed and No longer waiting in the muted color, not as a success or an error', async () => {
    const dismissed = await renderCard(UPDATED, { kind: 'rejected' }, scheme);
    expect(within(screen.getByTestId('proposal-status')).getByText('Dismissed')).toHaveStyle({ color: colors.textMuted });
    await dismissed.unmount();

    await renderCard(UPDATED, { kind: 'expired' }, scheme);
    expect(within(screen.getByTestId('proposal-status')).getByText('No longer waiting')).toHaveStyle({ color: colors.textMuted });
  });

  test('draws Dismiss on the same outlined surface as the card\'s other secondary button', async () => {
    await renderCard(UPDATED, READY, scheme);

    expect(button('Dismiss')).toHaveStyle({ backgroundColor: colors.surface, borderColor: colors.borderStrong });
    expect(within(button('Dismiss')).getByText('Dismiss')).toHaveStyle({ color: colors.textPrimary });
  });

  test('says when a workout was proposed in the muted color', async () => {
    await renderCard(UPDATED, READY, scheme, { proposedAgo: 'Proposed 12 min ago' });

    expect(screen.getByTestId('proposal-recovered')).toHaveStyle({ color: colors.textMuted });
  });
});

describe('the three sections wear the workout screen\'s own colors', () => {
  test('purple for the warm-up, green for the main workout, blue for the cool-down', async () => {
    await renderCard(NEW);

    // the dots are the first child of each header row: read their colors from the rendered tree
    const colorsOf = ['WARM_UP', 'MAIN_WORKOUT', 'COOL_DOWN'].map((id) => {
      const header = screen.getByTestId(`proposal-section-${id}`);
      const row = header.children[0] as unknown as { children: { props: { style: { backgroundColor?: string } } }[] };
      return row.children[0]?.props?.style?.backgroundColor;
    });
    expect(colorsOf).toEqual(['#7C3AED', '#0AA96B', '#0A72E8']);
  });
});
