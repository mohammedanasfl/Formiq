import { Keyboard, ScrollView, TextInput } from 'react-native';
import { act, fireEvent, render, screen, within } from '@testing-library/react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { ApiError } from '../src/api';
import { CoachScreen } from '../src/coach/CoachScreen';
import { coachOpening } from '../src/coach/opening';
import { MAX_MESSAGE_LENGTH } from '../src/coach/conversation';
import type { CoachGateway } from '../src/coach/gateway';
import { MOCK_INTRO, MOCK_OPENING, MOCK_TYPED_REPLIES } from '../src/mock/coachMock';
import { mockPendingProposal, mockProposal, mockReplyFor, mockSavedPlan } from '../src/mock/coachProposalsMock';
import {
  createMockCoachGateway,
  createMockSwitches,
  MOCK_APPLY_DELAY_MS,
  MOCK_PENDING_DELAY_MS,
  MOCK_PROPOSAL_DELAY_MS,
  MOCK_REJECT_DELAY_MS,
  MOCK_REPLY_DELAY_MS,
  type MockSwitchStore,
} from '../src/mock/mockCoachGateway';
import { MockCoachScreen } from '../src/mock/MockCoachScreen';
import { ThemeProvider, themes, type ThemeScheme } from '../src/theme';
import { fakeGateway } from '../test-utils/coachGateway';
import { installMockFetch, type MockFetch } from '../test-utils/mockFetch';
import { renderWithTheme } from '../test-utils/renderWithTheme';

const dark = themes.dark.colors;
const light = themes.light.colors;
const NOW = new Date(2026, 9, 22, 9, 0, 0);

// Jest's ScrollView and TextInput are mocks whose methods are jest.fn()s shared by every instance: these are the
// ones that record a scroll, and a field being asked to take or let go of focus.
const scrollMock = (ScrollView as unknown as { prototype: { scrollToEnd: jest.Mock; scrollTo: jest.Mock } }).prototype;
const fieldMock = (TextInput as unknown as { prototype: { blur: jest.Mock; focus: jest.Mock } }).prototype;

let backend: MockFetch;

beforeEach(() => {
  // no route is scripted: any request the screen made would throw, and be recorded
  backend = installMockFetch();
  // only the pauses are faked: React's and the test library's own scheduling keep running
  jest.useFakeTimers({ doNotFake: ['nextTick', 'setImmediate', 'queueMicrotask'] });
});

afterEach(() => {
  jest.useRealTimers();
  jest.restoreAllMocks();
});

// the pauses of the made-up coach, which a test lets pass
const pass = (ms: number) =>
  act(async () => {
    await jest.advanceTimersByTimeAsync(ms);
  });

async function renderMock(options: { scheme?: ThemeScheme; coachContext?: { workoutId: number; title: string } | null } = {}) {
  const onBack = jest.fn();
  const onOpenPreview = jest.fn();
  const view = await renderWithTheme(
    <MockCoachScreen onBack={onBack} onOpenPreview={onOpenPreview} coachContext={options.coachContext} />,
    options.scheme ?? 'dark',
  );
  return { ...view, onBack, onOpenPreview };
}

// the screen on a gateway of the test's own, to look at what it does with the answers
async function renderWith(gateway: CoachGateway, scheme: ThemeScheme = 'dark') {
  const onBack = jest.fn();
  const view = await renderWithTheme(<CoachScreen gateway={gateway} openingFor={() => MOCK_OPENING} onBack={onBack} />, scheme);
  return { ...view, onBack };
}

const input = () => screen.getByLabelText('Message');
const sendButton = () => screen.getByRole('button', { name: 'Send message' });
const button = (name: string | RegExp) => screen.getByRole('button', { name });
const bubbles = () => screen.getAllByTestId(/^message-/);
const bubbleTexts = () => bubbles().map((bubble) => within(bubble).getByText(/./).props.children as string);
const cards = () => screen.queryAllByTestId('proposal-card');
async function typeAndSend(text: string) {
  await fireEvent.changeText(input(), text);
  await fireEvent.press(sendButton());
}
async function openMenu() {
  await fireEvent.press(button('More options'));
}
async function chooseFromMenu(name: string) {
  await openMenu();
  await fireEvent.press(screen.getByRole('menuitem', { name }));
}
// the card's own parts, the last card on the page
const lastCard = () => within(cards().at(-1)!);

describe('<CoachScreen />: what is on the screen', () => {
  test('has a header with Back, the coach\'s name and subtitle, an avatar and an overflow menu button', async () => {
    await renderMock();

    const header = within(screen.getByTestId('coach-header'));
    header.getByRole('button', { name: 'Back' });
    header.getByRole('header', { name: 'Formiq Coach' });
    header.getByText('Your AI fitness coach');
    header.getByTestId('coach-avatar', { includeHiddenElements: true });
    header.getByRole('button', { name: 'More options' });
  });

  test('does not say the coach is online: it is not reached yet', async () => {
    await renderMock();

    expect(screen.queryByText(/online|active now/i)).toBeNull();
  });

  test('opens on the static conversation: the coach greets, the user asks for a different ab workout, the coach asks about the length', async () => {
    await renderMock();

    expect(bubbleTexts()).toEqual(MOCK_INTRO.map((item) => (item.kind === 'message' ? item.text : '')));
    expect(bubbleTexts()[1]).toBe('Can I get a different ab workout?');
    expect(bubbleTexts()[2]).toBe('Sure. Do you want to keep the same duration, or try a different length?');
    expect(cards()).toHaveLength(0);
  });

  test("puts the coach's messages on the left and the user's on the right", async () => {
    await renderMock();

    expect(screen.getByTestId('message-m1')).toHaveStyle({ alignSelf: 'flex-start' });
    expect(screen.getByTestId('message-m2')).toHaveStyle({ alignSelf: 'flex-end' });
    expect(screen.getByTestId('message-m3')).toHaveStyle({ alignSelf: 'flex-start' });
  });

  test('names the speaker of each message for a screen reader', async () => {
    await renderMock();

    expect(screen.getByLabelText(/^Formiq Coach: Hi, I'm Formiq Coach/)).toBeOnTheScreen();
    expect(screen.getByLabelText('You: Can I get a different ab workout?')).toBeOnTheScreen();
  });

  test('offers the suggested replies in one row that scrolls sideways', async () => {
    await renderMock();

    const row = screen.getByTestId('suggested-replies');
    expect(row).toHaveProp('horizontal', true);
    expect(row).toHaveProp('showsHorizontalScrollIndicator', false);
    expect(within(row).getAllByRole('button').map((chip) => chip.props.accessibilityLabel)).toEqual([
      'Keep same duration',
      'Try different length',
      'Create a 25-minute upper-body workout',
    ]);
  });

  test('has a message field and a send button at the bottom, with the send button off until something is typed', async () => {
    await renderMock();

    const composer = within(screen.getByTestId('chat-composer'));
    expect(composer.getByLabelText('Message')).toBeOnTheScreen();
    composer.getByPlaceholderText('Message Formiq Coach');
    expect(composer.getByRole('button', { name: 'Send message' })).toBeDisabled();
  });

  test('has no tab bar of its own: the shell keeps that below the screen', async () => {
    await renderMock();

    expect(screen.queryByTestId('bottom-tab-bar')).toBeNull();
  });
});

describe('<CoachScreen />: a message that is not a request for a workout', () => {
  test('"Try different length" is added at once, the chips go, the coach is shown typing, and its question comes after the pause', async () => {
    await renderMock();

    await fireEvent.press(button('Try different length'));

    expect(bubbleTexts().at(-1)).toBe('Try different length');
    expect(screen.getByTestId('message-m4')).toHaveStyle({ alignSelf: 'flex-end' });
    expect(screen.queryByTestId('suggested-replies')).toBeNull();
    screen.getByLabelText('Formiq Coach is typing');
    expect(cards()).toHaveLength(0);

    await pass(MOCK_REPLY_DELAY_MS);

    expect(screen.queryByTestId('typing-indicator')).toBeNull();
    expect(bubbleTexts().slice(-2)).toEqual(['Try different length', 'No problem. How long would you like it to be: 10, 20 or 30 minutes?']);
    // m4 is the user's, m5 was the coach's pending answer, m6 is the answer
    expect(screen.getByTestId('message-m6')).toHaveStyle({ alignSelf: 'flex-start' });
  });

  test('a typed message is added on the right, empties the field and shows the coach typing, then gets the first fixed line', async () => {
    await renderMock();

    await typeAndSend('Make it harder please');

    expect(bubbleTexts().at(-1)).toBe('Make it harder please');
    expect(input()).toHaveDisplayValue('');
    expect(screen.getByTestId('typing-indicator')).toBeOnTheScreen();
    expect(screen.queryByTestId('suggested-replies')).toBeNull();

    await pass(MOCK_REPLY_DELAY_MS);

    expect(bubbleTexts().slice(-2)).toEqual(['Make it harder please', MOCK_TYPED_REPLIES[0]]);
    expect(screen.queryByTestId('typing-indicator')).toBeNull();
  });

  test('the fixed lines come in turn, and round again after the last', async () => {
    await renderMock();
    const answers: string[] = [];

    for (let turn = 0; turn < MOCK_TYPED_REPLIES.length + 1; turn += 1) {
      await typeAndSend(`message ${turn}`);
      await pass(MOCK_REPLY_DELAY_MS);
      answers.push(bubbleTexts().at(-1) as string);
    }

    expect(answers).toEqual([...MOCK_TYPED_REPLIES, MOCK_TYPED_REPLIES[0]]);
  });

  test('sends the message without the spaces around it, and keeps the line breaks inside it', async () => {
    await renderMock();

    await typeAndSend('   thanks for that  \n');
    await pass(MOCK_REPLY_DELAY_MS);
    await typeAndSend('first\nsecond');

    expect(bubbleTexts()).toContain('thanks for that');
    expect(bubbleTexts()).toContain('first\nsecond');
  });

  test('the field takes several lines up to the coach API\'s limit, and Enter is a new line, not a send', async () => {
    await renderMock();

    expect(input()).toHaveProp('multiline', true);
    expect(input()).toHaveProp('maxLength', MAX_MESSAGE_LENGTH);
    expect(input()).not.toHaveProp('onSubmitEditing');
  });
});

describe('<CoachScreen />: an empty message is never sent', () => {
  test('the send button is off for an empty field and for one of only spaces and line breaks', async () => {
    await renderMock();
    expect(sendButton()).toBeDisabled();

    await fireEvent.changeText(input(), '    ');
    expect(sendButton()).toBeDisabled();
    await fireEvent.changeText(input(), '\n \n');
    expect(sendButton()).toBeDisabled();

    await fireEvent.changeText(input(), 'hi');
    expect(sendButton()).toBeEnabled();
  });

  test('pressing the disabled button adds nothing and starts no reply', async () => {
    await renderMock();
    await fireEvent.changeText(input(), '   ');

    await fireEvent.press(sendButton());
    await pass(MOCK_PROPOSAL_DELAY_MS);

    expect(bubbles()).toHaveLength(MOCK_INTRO.length);
    expect(screen.queryByTestId('typing-indicator')).toBeNull();
    expect(screen.getByTestId('suggested-replies')).toBeOnTheScreen();
  });
});

describe('<CoachScreen />: while the coach is answering', () => {
  test('the field stays open for the next message but sending waits, so replies never come out of order', async () => {
    await renderMock();
    await typeAndSend('first');

    await fireEvent.changeText(input(), 'second');
    expect(input()).toHaveDisplayValue('second');
    expect(sendButton()).toBeDisabled();
    await fireEvent.press(sendButton());
    expect(bubbleTexts().filter((text) => text === 'second')).toHaveLength(0);

    await pass(MOCK_REPLY_DELAY_MS);
    expect(sendButton()).toBeEnabled();
    await fireEvent.press(sendButton());
    expect(bubbleTexts().at(-1)).toBe('second');
  });

  test('a suggested reply cannot be sent twice: only one message goes', async () => {
    await renderMock();

    const chip = button('Try different length');
    await fireEvent.press(chip);
    await fireEvent.press(chip);
    await pass(MOCK_REPLY_DELAY_MS);

    expect(bubbleTexts().filter((text) => text === 'Try different length')).toHaveLength(1);
  });

  test('going away drops the reply that was on its way: it arrives to nothing, and nothing is updated', async () => {
    const error = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    const { unmount } = await renderMock();
    await typeAndSend('hello');

    await unmount();
    await pass(MOCK_PROPOSAL_DELAY_MS);

    expect(error).not.toHaveBeenCalled();
  });
});

describe('<CoachScreen />: Scenario A, a new workout', () => {
  async function askForNewWorkout() {
    await typeAndSend('Create a 25-minute upper-body workout.');
    await pass(MOCK_PROPOSAL_DELAY_MS);
  }

  test('shows the message, the coach typing, then its words followed by the workout card', async () => {
    await renderMock();

    await typeAndSend('Create a 25-minute upper-body workout.');
    expect(bubbleTexts().at(-1)).toBe('Create a 25-minute upper-body workout.');
    expect(screen.getByTestId('typing-indicator')).toBeOnTheScreen();
    expect(cards()).toHaveLength(0);

    await pass(MOCK_PROPOSAL_DELAY_MS);

    expect(screen.queryByTestId('typing-indicator')).toBeNull();
    expect(bubbleTexts().at(-1)).toBe(mockReplyFor('new'));
    expect(cards()).toHaveLength(1);
  });

  test('is a New Workout card with its title, picture, length, exercises and sections, and nothing it was not given', async () => {
    await renderMock();
    await askForNewWorkout();

    const card = lastCard();
    within(screen.getByTestId('proposal-status')).getByText('New Workout');
    card.getByRole('header', { name: 'Upper Body Strength' });
    card.getByText('24 min');
    card.getByText('8 exercises');
    card.getByText('Upper body focus • Today');
    card.getByRole('button', { name: 'Main Workout, 4 exercises, 21 min' });
    expect(card.queryByText(/moderate|difficulty/i)).toBeNull();
    expect(card.queryByTestId('key-changes')).toBeNull();
    expect(card.getByRole('button', { name: 'Apply This Workout' })).toBeEnabled();
    expect(card.getByRole('button', { name: 'Ask for More Changes' })).toBeEnabled();
    expect(card.getByTestId('proposal-caption')).toHaveTextContent(/Not saved yet/);
  });

  test('is not saved by being shown: nothing is approved until Apply is pressed', async () => {
    const gateway = createMockCoachGateway(createMockSwitches(), () => NOW);
    const approve = jest.spyOn(gateway, 'approve');
    await renderWith(gateway);

    await typeAndSend('Create a 25-minute upper-body workout.');
    await pass(MOCK_PROPOSAL_DELAY_MS);
    await pass(60_000);

    expect(approve).not.toHaveBeenCalled();
    within(screen.getByTestId('proposal-status')).getByText('New Workout');
  });

  test('Apply shows it applying, and only when the backend has answered, Applied: the caption says it was added to the plan', async () => {
    await renderMock();
    await askForNewWorkout();

    await fireEvent.press(button('Apply This Workout'));
    expect(button('Applying…')).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Applied' })).toBeNull();
    within(screen.getByTestId('proposal-status')).getByText('New Workout');

    await pass(MOCK_APPLY_DELAY_MS - 1);
    expect(screen.queryByRole('button', { name: 'Applied' })).toBeNull();

    await pass(1);
    within(screen.getByTestId('proposal-status')).getByText('Applied');
    expect(button('Applied')).toBeDisabled();
    expect(screen.getByTestId('proposal-caption')).toHaveTextContent(/^Added “Upper Body Strength” to your plan for today\.$/);
    expect(screen.queryByRole('button', { name: 'Ask for More Changes' })).toBeNull();
    expect(screen.queryByRole('button', { name: /Apply This Workout/ })).toBeNull();
  });
});

describe('<CoachScreen />: Scenario B, an edit of a saved workout', () => {
  async function askForEdit() {
    await fireEvent.press(button('Keep same duration'));
    await pass(MOCK_PROPOSAL_DELAY_MS);
  }

  test('a request for a workout shows the card loading while the coach works, and the chips go', async () => {
    await renderMock();

    await fireEvent.press(button('Keep same duration'));

    expect(bubbleTexts().at(-1)).toBe('Keep same duration');
    screen.getByLabelText('Preparing your workout');
    expect(screen.queryByTestId('typing-indicator')).toBeNull();
    expect(screen.queryByTestId('suggested-replies')).toBeNull();
    expect(screen.queryByRole('button', { name: /Apply/ })).toBeNull();

    await pass(MOCK_PROPOSAL_DELAY_MS);

    expect(screen.queryByLabelText('Preparing your workout')).toBeNull();
    expect(cards()).toHaveLength(1);
  });

  test('is an Updated Workout card, after the coach\'s words, with Apply Updated Workout', async () => {
    await renderMock();
    await askForEdit();

    expect(bubbleTexts().at(-1)).toBe(mockReplyFor('edit'));
    within(screen.getByTestId('proposal-status')).getByText('Updated Workout');
    lastCard().getByRole('header', { name: 'Core Stability & Abs' });
    expect(button('Apply Updated Workout')).toBeEnabled();
    expect(screen.queryByRole('button', { name: 'Apply This Workout' })).toBeNull();
    expect(button('Ask for More Changes')).toBeEnabled();
  });

  test('has the Key Changes the backend found by comparing it with the saved workout, and says the saved one stays until it is applied', async () => {
    await renderMock();
    await askForEdit();

    const changes = within(screen.getByTestId('key-changes'));
    changes.getByText('Replaced Bicycle Crunches with Dead Bug');
    changes.getByText('Replaced Leg Raises with Side Plank');
    changes.getByText('Plank: 30 s → 40 s');
    // the backend said how long the saved workout takes, and it is as long as this one
    changes.getByText('Kept the same duration (18 min)');
    expect(screen.getByTestId('proposal-caption')).toHaveTextContent('Applying replaces “Core & Abs Focus”. Until then it stays as it is.');
  });

  test('leaves the saved workout exactly as it is while it is only proposed, and until it is applied: nothing is approved or dismissed', async () => {
    const gateway = createMockCoachGateway(createMockSwitches(), () => NOW);
    const approve = jest.spyOn(gateway, 'approve');
    const reject = jest.spyOn(gateway, 'reject');
    await renderWith(gateway);

    await fireEvent.press(button('Keep same duration'));
    await pass(MOCK_PROPOSAL_DELAY_MS);
    await pass(60_000);

    expect(approve).not.toHaveBeenCalled();
    expect(reject).not.toHaveBeenCalled();
    within(screen.getByTestId('proposal-status')).getByText('Updated Workout');
  });

  test('replaces the saved workout only after the backend confirms: it is Applied, and the caption says what it replaced', async () => {
    const gateway = createMockCoachGateway(createMockSwitches(), () => NOW);
    await renderWith(gateway);
    await fireEvent.press(button('Keep same duration'));
    await pass(MOCK_PROPOSAL_DELAY_MS);

    await fireEvent.press(button('Apply Updated Workout'));
    await pass(MOCK_APPLY_DELAY_MS - 1);
    expect(screen.queryByRole('button', { name: 'Applied' })).toBeNull();
    within(screen.getByTestId('proposal-status')).getByText('Updated Workout');

    await pass(1);
    within(screen.getByTestId('proposal-status')).getByText('Applied');
    expect(screen.getByTestId('proposal-caption')).toHaveTextContent(/^Replaced “Core & Abs Focus” with “Core Stability & Abs” for /);
  });

  test('a double press on Apply applies it once', async () => {
    const gateway = createMockCoachGateway(createMockSwitches(), () => NOW);
    const approve = jest.spyOn(gateway, 'approve');
    await renderWith(gateway);
    await fireEvent.press(button('Keep same duration'));
    await pass(MOCK_PROPOSAL_DELAY_MS);

    const apply = button('Apply Updated Workout');
    await fireEvent.press(apply);
    await fireEvent.press(apply);
    await fireEvent.press(apply);
    await pass(MOCK_APPLY_DELAY_MS);

    expect(approve).toHaveBeenCalledTimes(1);
    within(screen.getByTestId('proposal-status')).getByText('Applied');
  });

  test('a message cannot be sent while it is being applied, and Start over waits too', async () => {
    await renderMock();
    await askForEdit();
    await fireEvent.press(button('Apply Updated Workout'));

    await fireEvent.changeText(input(), 'wait, change it');
    expect(sendButton()).toBeDisabled();
    await openMenu();
    expect(screen.getByRole('menuitem', { name: 'Start over' })).toBeDisabled();
    await fireEvent.press(screen.getByRole('button', { name: 'Close menu' }));

    await pass(MOCK_APPLY_DELAY_MS);
    expect(sendButton()).toBeEnabled();
  });

  test('typing the request instead of tapping the chip gives the same card', async () => {
    await renderMock();

    await typeAndSend('Suggest a different ab workout for today.');
    await pass(MOCK_PROPOSAL_DELAY_MS);

    within(screen.getByTestId('proposal-status')).getByText('Updated Workout');
    lastCard().getByRole('header', { name: 'Core Stability & Abs' });
  });
});

describe('<CoachScreen />: Scenario C, more changes', () => {
  async function editThenAskForChanges() {
    await fireEvent.press(button('Keep same duration'));
    await pass(MOCK_PROPOSAL_DELAY_MS);
  }

  test('Ask for More Changes puts the keyboard up with a field that asks what to change, and offers ways to change it', async () => {
    await renderMock();
    await editThenAskForChanges();
    fieldMock.focus.mockClear();

    await fireEvent.press(button('Ask for More Changes'));

    expect(fieldMock.focus).toHaveBeenCalledTimes(1);
    expect(input()).toHaveProp('placeholder', 'What would you like to change?');
    expect(within(screen.getByTestId('suggested-replies')).getAllByRole('button').map((chip) => chip.props.accessibilityLabel)).toEqual([
      'Keep same duration',
      'Try different length',
      'Make it more intense',
      'Use no equipment',
    ]);
    // asking creates nothing and changes nothing
    expect(cards()).toHaveLength(1);
  });

  test('a refinement is sent with the conversation, and shows the newer card in the older one\'s place', async () => {
    await renderMock();
    await editThenAskForChanges();
    await fireEvent.press(button('Ask for More Changes'));

    await typeAndSend('Keep the same duration, but make it easier on my knees.');
    expect(input()).toHaveProp('placeholder', 'Message Formiq Coach');
    screen.getByLabelText('Formiq Coach is typing');
    await pass(MOCK_PROPOSAL_DELAY_MS);

    expect(cards()).toHaveLength(2);
    expect(bubbleTexts().at(-1)).toBe(mockReplyFor('edit-refined'));
    const [older, newer] = cards();
    within(older).getByText('Older version');
    expect(within(older).queryByRole('button', { name: /Apply|Ask for More/ })).toBeNull();
    within(newer).getByText('Updated Workout');
    within(newer).getByRole('header', { name: 'Gentle Core & Abs' });
    // exactly one workout can be applied now
    expect(screen.getAllByRole('button', { name: 'Apply Updated Workout' })).toHaveLength(1);
  });

  test('the newer card\'s Key Changes compare it with the original saved workout, not with the first proposal', async () => {
    await renderMock();
    await editThenAskForChanges();
    await typeAndSend('make it easier on my knees');
    await pass(MOCK_PROPOSAL_DELAY_MS);

    const changes = within(cards()[1]).getByTestId('key-changes');
    expect(within(changes).getByText('Replaced Mountain Climbers with Cat-Cow Stretch in the warm-up')).toBeOnTheScreen();
    expect(within(changes).getByText('Replaced Leg Raises with Reverse Crunch')).toBeOnTheScreen();
    expect(within(changes).queryByText(/Plank:/)).toBeNull();
  });

  test('a tapped way to change it is a request for a workout: the card shows loading, and a newer card follows', async () => {
    await renderMock();
    await editThenAskForChanges();

    await fireEvent.press(button('Use no equipment'));

    expect(bubbleTexts().at(-1)).toBe('Use no equipment');
    expect(screen.getAllByLabelText('Preparing your workout')).toHaveLength(1);
    expect(screen.queryByTestId('typing-indicator')).toBeNull();
    await pass(MOCK_PROPOSAL_DELAY_MS);

    expect(cards()).toHaveLength(2);
  });

  test('the saved workout is still exactly as it was after a refinement, until a version is applied: nothing is approved', async () => {
    const gateway = createMockCoachGateway(createMockSwitches(), () => NOW);
    const approve = jest.spyOn(gateway, 'approve');
    await renderWith(gateway);
    await fireEvent.press(button('Keep same duration'));
    await pass(MOCK_PROPOSAL_DELAY_MS);

    await typeAndSend('easier on my knees');
    await pass(MOCK_PROPOSAL_DELAY_MS);

    expect(approve).not.toHaveBeenCalled();
  });

  test('applying the newer version replaces the saved workout, and the older card stays an older version', async () => {
    const gateway = createMockCoachGateway(createMockSwitches(), () => NOW);
    await renderWith(gateway);
    await fireEvent.press(button('Keep same duration'));
    await pass(MOCK_PROPOSAL_DELAY_MS);
    await typeAndSend('easier on my knees');
    await pass(MOCK_PROPOSAL_DELAY_MS);

    await fireEvent.press(button('Apply Updated Workout'));
    await pass(MOCK_APPLY_DELAY_MS);

    const [older, newer] = cards();
    within(older).getByText('Older version');
    within(within(newer).getByTestId('proposal-status')).getByText('Applied');
  });

  test('a new workout changed shows a newer New Workout card, still without Key Changes', async () => {
    await renderMock();
    await typeAndSend('Create a 25-minute upper-body workout.');
    await pass(MOCK_PROPOSAL_DELAY_MS);

    await fireEvent.press(button('Use no equipment'));
    await pass(MOCK_PROPOSAL_DELAY_MS);

    const [older, newer] = cards();
    within(older).getByText('Older version');
    within(newer).getByText('New Workout');
    within(newer).getByRole('header', { name: 'Upper Body, No Equipment' });
    expect(within(newer).queryByTestId('key-changes')).toBeNull();
  });
});

describe('<CoachScreen />: when applying fails', () => {
  async function toTheEdit() {
    const view = await renderMock();
    await fireEvent.press(button('Keep same duration'));
    await pass(MOCK_PROPOSAL_DELAY_MS);
    return view;
  }

  test('keeps the proposal and the saved workout, says why, and a second try applies it', async () => {
    const switches = createMockSwitches({ failNextApply: true });
    const gateway = createMockCoachGateway(switches, () => NOW);
    await renderWith(gateway);
    await fireEvent.press(button('Keep same duration'));
    await pass(MOCK_PROPOSAL_DELAY_MS);

    await fireEvent.press(button('Apply Updated Workout'));
    await pass(MOCK_APPLY_DELAY_MS);

    const error = screen.getByTestId('apply-error');
    expect(error).toHaveProp('accessibilityRole', 'alert');
    within(error).getByText("Can't reach Formiq. Check your connection and try again.");
    within(screen.getByTestId('proposal-status')).getByText('Updated Workout');
    expect(screen.queryByText('Applied')).toBeNull();
    within(screen.getByTestId('key-changes')).getByText('Replaced Leg Raises with Side Plank');

    await fireEvent.press(button('Try Again'));
    expect(button('Applying…')).toBeDisabled();
    await pass(MOCK_APPLY_DELAY_MS);

    within(screen.getByTestId('proposal-status')).getByText('Applied');
    expect(screen.queryByTestId('apply-error')).toBeNull();
  });

  test('the menu switch makes exactly the next apply fail, and shows when it is on', async () => {
    await toTheEdit();

    await openMenu();
    expect(screen.getByRole('menuitem', { name: 'Mock: next apply fails' })).toHaveProp('accessibilityState', expect.objectContaining({ checked: false }));
    await fireEvent.press(screen.getByRole('menuitem', { name: 'Mock: next apply fails' }));
    await openMenu();
    expect(screen.getByRole('menuitem', { name: 'Mock: next apply fails' })).toHaveProp('accessibilityState', expect.objectContaining({ checked: true }));
    await fireEvent.press(screen.getByRole('button', { name: 'Close menu' }));

    await fireEvent.press(button('Apply Updated Workout'));
    await pass(MOCK_APPLY_DELAY_MS);
    screen.getByTestId('apply-error');

    // it was used up
    await openMenu();
    expect(screen.getByRole('menuitem', { name: 'Mock: next apply fails' })).toHaveProp('accessibilityState', expect.objectContaining({ checked: false }));
  });

  test('a refusal that trying again cannot fix is final: the apply stays out of use, and asking for changes is the way on', async () => {
    const { gateway } = fakeGateway();
    gateway.send.mockResolvedValue({ reply: 'Here', proposal: mockProposal('edit', NOW, 2) });
    gateway.approve.mockRejectedValue(new ApiError('http', 409, 'this proposal has expired: ask the coach for a new one'));
    await renderWith(gateway);
    await fireEvent.press(button('Keep same duration'));
    await pass(1);

    await fireEvent.press(button('Apply Updated Workout'));
    await pass(1);

    within(screen.getByTestId('apply-error')).getByText('This proposal has expired. Ask the coach for a new one.');
    expect(button('Apply Updated Workout')).toBeDisabled();
    expect(button('Ask for More Changes')).toBeEnabled();
    await fireEvent.press(button('Apply Updated Workout'));
    expect(gateway.approve).toHaveBeenCalledTimes(1);
  });
});

describe('<CoachScreen />: when the coach cannot answer', () => {
  test('a request for a workout shows the card as not made, and Try Again asks again without a second message', async () => {
    const switches: MockSwitchStore = createMockSwitches({ failNextRequest: true });
    const gateway = createMockCoachGateway(switches, () => NOW);
    await renderWith(gateway);

    await fireEvent.press(button('Keep same duration'));
    screen.getByLabelText('Preparing your workout');
    await pass(MOCK_PROPOSAL_DELAY_MS);

    within(screen.getByTestId('proposal-status')).getByText("Couldn't create the workout");
    screen.getByText("Can't reach Formiq. Check your connection and try again.");
    expect(screen.queryByRole('button', { name: /Apply/ })).toBeNull();

    await fireEvent.press(button('Try Again'));
    screen.getByLabelText('Preparing your workout');
    await pass(MOCK_PROPOSAL_DELAY_MS);

    expect(bubbleTexts().filter((text) => text === 'Keep same duration')).toHaveLength(1);
    within(screen.getByTestId('proposal-status')).getByText('Updated Workout');
    expect(screen.queryByText("Couldn't create the workout")).toBeNull();
  });

  test('a message that was not known to be a request for a workout gets a plain failure with Try Again', async () => {
    await renderMock();
    await chooseFromMenu('Mock: next request fails');

    await typeAndSend('hello there');
    screen.getByTestId('typing-indicator');
    await pass(MOCK_REPLY_DELAY_MS);

    const failure = within(screen.getByTestId('request-failed'));
    failure.getByText("Can't reach Formiq. Check your connection and try again.");
    expect(cards()).toHaveLength(0);

    await fireEvent.press(failure.getByRole('button', { name: 'Try Again' }));
    await pass(MOCK_REPLY_DELAY_MS);

    expect(screen.queryByTestId('request-failed')).toBeNull();
    expect(bubbleTexts().at(-1)).toBe(MOCK_TYPED_REPLIES[0]);
    expect(bubbleTexts().filter((text) => text === 'hello there')).toHaveLength(1);
  });

  test('a failure is announced as an alert', async () => {
    await renderMock();
    await chooseFromMenu('Mock: next request fails');
    await typeAndSend('hello there');
    await pass(MOCK_REPLY_DELAY_MS);

    expect(within(screen.getByTestId('request-failed')).getByRole('alert')).toBeOnTheScreen();
  });
});

describe('<CoachScreen />: the latest message stays in view', () => {
  // the nearest ancestor that reports its own layout: the wrapper the screen puts around each item
  const reportLayout = (testId: string, y: number, height: number) => {
    let node = screen.getAllByTestId(testId, { includeHiddenElements: true }).at(-1)!.parent;
    while (node && !node.props.onLayout) node = node.parent;
    return fireEvent(node!, 'layout', { nativeEvent: { layout: { x: 0, y, width: 360, height } } });
  };

  test('asks the list to scroll to the end, animated, when a message arrives and when its room changes', async () => {
    await renderMock();
    scrollMock.scrollToEnd.mockClear();

    await fireEvent(screen.getByTestId('coach-messages'), 'contentSizeChange', 360, 1200);
    expect(scrollMock.scrollToEnd).toHaveBeenCalledTimes(1);
    expect(scrollMock.scrollToEnd).toHaveBeenLastCalledWith({ animated: true });

    // the keyboard opening or closing changes the list's height
    await fireEvent(screen.getByTestId('coach-messages'), 'layout', { nativeEvent: { layout: { x: 0, y: 0, width: 360, height: 300 } } });
    expect(scrollMock.scrollToEnd).toHaveBeenCalledTimes(2);
  });

  test('a message that is only changed afterwards (the same newest item growing) does not take the person back to the end', async () => {
    await renderMock();
    await fireEvent(screen.getByTestId('coach-messages'), 'contentSizeChange', 360, 1200);
    scrollMock.scrollToEnd.mockClear();

    await fireEvent(screen.getByTestId('coach-messages'), 'contentSizeChange', 360, 1300);

    expect(scrollMock.scrollToEnd).not.toHaveBeenCalled();
  });

  test('a new message makes the list grow, and the list follows it', async () => {
    await renderMock();
    await fireEvent(screen.getByTestId('coach-messages'), 'contentSizeChange', 360, 1200);
    scrollMock.scrollToEnd.mockClear();

    await typeAndSend('hello');
    await fireEvent(screen.getByTestId('coach-messages'), 'contentSizeChange', 360, 1300);
    await pass(MOCK_REPLY_DELAY_MS);
    await fireEvent(screen.getByTestId('coach-messages'), 'contentSizeChange', 360, 1400);

    expect(scrollMock.scrollToEnd).toHaveBeenCalledTimes(2);
  });

  test('a workout card is taller than the room, so the list goes to where the coach\'s reply begins, not to the card\'s end', async () => {
    const { gateway } = fakeGateway();
    gateway.send.mockResolvedValue({ reply: 'Here is a workout', proposal: mockProposal('edit', NOW, 2) });
    await renderWith(gateway);
    // the window on the list is 600 dp tall
    await fireEvent(screen.getByTestId('coach-messages'), 'layout', { nativeEvent: { layout: { x: 0, y: 0, width: 360, height: 600 } } });
    await fireEvent.press(button('Keep same duration'));
    await pass(1);
    scrollMock.scrollToEnd.mockClear();
    scrollMock.scrollTo.mockClear();

    // the reply starts 700 dp down, the card 840, and the card is 560 tall: the page ends at 1400 + 16
    await reportLayout('message-m6', 700, 140);
    await reportLayout('proposal-card', 840, 560);

    expect(scrollMock.scrollToEnd).not.toHaveBeenCalled();
    // the end would be 1416 - 600 = 816; the reply (700) less a margin of 12 is before it
    expect(scrollMock.scrollTo).toHaveBeenCalledTimes(1);
    expect(scrollMock.scrollTo).toHaveBeenLastCalledWith({ y: 688, animated: true });
  });

  test('does not go past the end of a page that ends before the reply\'s own place', async () => {
    const { gateway } = fakeGateway();
    gateway.send.mockResolvedValue({ reply: 'Here is a workout', proposal: mockProposal('edit', NOW, 2) });
    await renderWith(gateway);
    await fireEvent(screen.getByTestId('coach-messages'), 'layout', { nativeEvent: { layout: { x: 0, y: 0, width: 360, height: 900 } } });
    await fireEvent.press(button('Keep same duration'));
    await pass(1);
    scrollMock.scrollTo.mockClear();

    await reportLayout('message-m6', 700, 140);
    await reportLayout('proposal-card', 840, 300);

    // the page ends at 1156 and the window is 900: 256 is as far as it scrolls
    expect(scrollMock.scrollTo).toHaveBeenLastCalledWith({ y: 256, animated: true });
  });

  test('a card going from applying to applied is not scrolled to again: the person is reading it', async () => {
    const { gateway, approvals } = fakeGateway();
    gateway.send.mockResolvedValue({ reply: 'Here is a workout', proposal: mockProposal('edit', NOW, 2) });
    await renderWith(gateway);
    await fireEvent(screen.getByTestId('coach-messages'), 'layout', { nativeEvent: { layout: { x: 0, y: 0, width: 360, height: 600 } } });
    await fireEvent.press(button('Keep same duration'));
    await pass(1);
    await reportLayout('message-m6', 700, 140);
    await reportLayout('proposal-card', 840, 560);
    scrollMock.scrollTo.mockClear();
    scrollMock.scrollToEnd.mockClear();

    await fireEvent.press(button('Apply Updated Workout'));
    await reportLayout('proposal-card', 840, 520);
    await fireEvent(screen.getByTestId('coach-messages'), 'contentSizeChange', 360, 1380);
    await act(async () => {
      approvals[0].resolve(mockSavedPlan(mockProposal('edit', NOW, 2), 100));
    });
    await reportLayout('proposal-card', 840, 480);
    await fireEvent(screen.getByTestId('coach-messages'), 'contentSizeChange', 360, 1340);

    within(screen.getByTestId('proposal-status')).getByText('Applied');
    expect(scrollMock.scrollTo).not.toHaveBeenCalled();
    expect(scrollMock.scrollToEnd).not.toHaveBeenCalled();
  });

  // The typing dots and the failure that replaces them have the same id on the page: the failure is a taller, different
  // thing (its words and a Try Again button) that the person must see without scrolling for it.
  test.each([
    ['a message', 'request-failed', async () => typeAndSend('hello')],
    ['a request for a workout', 'proposal-generation-failed', async () => fireEvent.press(button('Keep same duration'))],
  ] as const)('the failure of %s that replaces the typing dots is brought into view, Try Again and all', async (_what, failure, ask) => {
    const fake = fakeGateway();
    await renderWith(fake.gateway);
    await ask();
    // the dots are there and the list has gone to them
    await fireEvent(screen.getByTestId('coach-messages'), 'contentSizeChange', 360, 1200);
    expect(scrollMock.scrollToEnd).toHaveBeenCalled();
    scrollMock.scrollToEnd.mockClear();

    await act(async () => {
      fake.sends.shift()!.reject(new ApiError('network', null, null));
    });
    expect(screen.getByTestId(failure)).toBeOnTheScreen();
    // the failure is taller than the dots: the list grew
    await fireEvent(screen.getByTestId('coach-messages'), 'contentSizeChange', 360, 1330);

    expect(scrollMock.scrollToEnd).toHaveBeenCalledTimes(1);
    expect(scrollMock.scrollToEnd).toHaveBeenLastCalledWith({ animated: true });
    screen.getByRole('button', { name: 'Try Again' });

    // asking again brings the dots, and a second failure the failure: each is brought into view
    scrollMock.scrollToEnd.mockClear();
    await fireEvent.press(button('Try Again'));
    await fireEvent(screen.getByTestId('coach-messages'), 'contentSizeChange', 360, 1200);
    expect(scrollMock.scrollToEnd).toHaveBeenCalledTimes(1);
    await act(async () => {
      fake.sends.shift()!.reject(new ApiError('http', 502, 'the AI coach could not answer; try again later'));
    });
    await fireEvent(screen.getByTestId('coach-messages'), 'contentSizeChange', 360, 1330);
    expect(scrollMock.scrollToEnd).toHaveBeenCalledTimes(2);
  });

  test('the failure is also brought into view when its own place on the page is reported', async () => {
    const fake = fakeGateway();
    await renderWith(fake.gateway);
    await typeAndSend('hello');
    await reportLayout('typing-indicator', 1100, 40);
    scrollMock.scrollToEnd.mockClear();

    await act(async () => {
      fake.sends.shift()!.reject(new ApiError('network', null, null));
    });
    await reportLayout('request-failed', 1100, 120);

    expect(scrollMock.scrollToEnd).toHaveBeenCalledTimes(1);
  });

  test('a failure, once brought into view, is not scrolled to again by later changes to the list (the person may be reading)', async () => {
    const fake = fakeGateway();
    await renderWith(fake.gateway);
    await typeAndSend('hello');
    await fireEvent(screen.getByTestId('coach-messages'), 'contentSizeChange', 360, 1200);
    await act(async () => {
      fake.sends.shift()!.reject(new ApiError('network', null, null));
    });
    await fireEvent(screen.getByTestId('coach-messages'), 'contentSizeChange', 360, 1330);
    scrollMock.scrollToEnd.mockClear();

    await fireEvent(screen.getByTestId('coach-messages'), 'contentSizeChange', 360, 1340);

    expect(scrollMock.scrollToEnd).not.toHaveBeenCalled();
  });

  test('a card is left where it is when only the window changes (the keyboard)', async () => {
    const { gateway } = fakeGateway();
    gateway.send.mockResolvedValue({ reply: 'Here is a workout', proposal: mockProposal('edit', NOW, 2) });
    await renderWith(gateway);
    await fireEvent.press(button('Keep same duration'));
    await pass(1);
    scrollMock.scrollTo.mockClear();
    scrollMock.scrollToEnd.mockClear();

    await fireEvent(screen.getByTestId('coach-messages'), 'layout', { nativeEvent: { layout: { x: 0, y: 0, width: 360, height: 300 } } });

    expect(scrollMock.scrollTo).not.toHaveBeenCalled();
    expect(scrollMock.scrollToEnd).not.toHaveBeenCalled();
  });
});

describe('<CoachScreen />: the keyboard', () => {
  test('the replies and the composer are lifted by what the keyboard covers, and let down when it goes', async () => {
    // Jest has no real keyboard: catch the listener the avoiding view registers and call it as the system would.
    const listeners = new Map<string, (event: unknown) => void>();
    jest.spyOn(Keyboard, 'addListener').mockImplementation(((name: string, listener: (event: unknown) => void) => {
      listeners.set(name, listener);
      return { remove: () => listeners.delete(name) };
    }) as never);
    await renderMock();
    const avoider = screen.getByTestId('coach-keyboard-avoider');
    // the view sits above the tab bar: its bottom edge is 100 dp above the bottom of an 800 dp screen
    await fireEvent(avoider, 'layout', { nativeEvent: { layout: { x: 0, y: 100, width: 360, height: 600 } }, persist: () => undefined });

    await act(async () => {
      listeners.get('keyboardWillShow')?.({ duration: 0, easing: 'keyboard', endCoordinates: { screenX: 0, screenY: 500, width: 360, height: 300 } });
    });
    // the keyboard (300 dp tall) covers the bar's 100 dp already: only the 200 dp above it is made room for
    expect(avoider).toHaveStyle({ paddingBottom: 200 });
    expect(within(avoider).getByTestId('chat-composer')).toBeOnTheScreen();

    await act(async () => listeners.get('keyboardWillHide')?.({}));
    expect(avoider).toHaveStyle({ paddingBottom: 0 });
  });

  test('the field lets go of focus when the keyboard is put away, so no focus outline is left on it', async () => {
    const listeners = new Map<string, (event: unknown) => void>();
    jest.spyOn(Keyboard, 'addListener').mockImplementation(((name: string, listener: (event: unknown) => void) => {
      listeners.set(name, listener);
      return { remove: () => listeners.delete(name) };
    }) as never);
    await renderMock();
    fieldMock.blur.mockClear();

    await act(async () => listeners.get('keyboardDidHide')?.({}));

    expect(fieldMock.blur).toHaveBeenCalledTimes(1);
  });

  test('stops listening to the keyboard when the screen goes away', async () => {
    const listeners = new Map<string, (event: unknown) => void>();
    jest.spyOn(Keyboard, 'addListener').mockImplementation(((name: string, listener: (event: unknown) => void) => {
      listeners.set(name, listener);
      return { remove: () => listeners.delete(name) };
    }) as never);
    const { unmount } = await renderMock();
    expect(listeners.has('keyboardDidHide')).toBe(true);

    await unmount();

    expect(listeners.has('keyboardDidHide')).toBe(false);
  });

  test('a chip or the send button works with the keyboard up, and dragging the list puts the keyboard away', async () => {
    await renderMock();

    expect(screen.getByTestId('coach-messages')).toHaveProp('keyboardShouldPersistTaps', 'handled');
    expect(screen.getByTestId('coach-messages')).toHaveProp('keyboardDismissMode', 'on-drag');
    expect(screen.getByTestId('suggested-replies')).toHaveProp('keyboardShouldPersistTaps', 'handled');
  });

  test('the field is limited in height, so a long message scrolls inside it instead of pushing the page away', async () => {
    await renderMock();

    const style = input().props.style;
    const flat = Object.assign({}, ...(Array.isArray(style) ? style : [style]));
    expect(flat.maxHeight).toBeGreaterThan(flat.minHeight);
    expect(flat.minHeight).toBeGreaterThanOrEqual(48);
  });
});

describe('<CoachScreen />: Back and the overflow menu', () => {
  test('the Back arrow goes back, once', async () => {
    const { onBack } = await renderMock();

    await fireEvent.press(button('Back'));

    expect(onBack).toHaveBeenCalledTimes(1);
  });

  test('the menu is closed to begin with, and "More options" opens it with Start over first', async () => {
    await renderMock();
    expect(screen.queryByTestId('coach-menu')).toBeNull();

    await openMenu();

    const items = within(screen.getByTestId('coach-menu')).getAllByRole('menuitem');
    expect(items.map((item) => item.props.accessibilityLabel)).toEqual([
      'Start over',
      'Preview card states',
      'Mock: next request fails',
      'Mock: next apply fails',
      'Mock: next dismiss fails',
      'Mock: a workout is waiting',
      'Mock: two workouts are waiting',
    ]);
  });

  test('pressing outside the menu closes it and changes nothing', async () => {
    await renderMock();
    await typeAndSend('hello');
    await openMenu();

    await fireEvent.press(button('Close menu'));

    expect(screen.queryByTestId('coach-menu')).toBeNull();
    expect(bubbleTexts().at(-1)).toBe('hello');
  });

  test("Android's back button closes the menu (the Modal's own close)", async () => {
    await renderMock();
    await openMenu();

    let node = screen.getByTestId('coach-menu').parent;
    while (node && !node.props.onRequestClose) node = node.parent;
    expect(node).not.toBeNull();
    await act(async () => {
      node?.props.onRequestClose();
    });

    expect(screen.queryByTestId('coach-menu')).toBeNull();
  });

  test('"Preview card states" opens the page of every state, and closes the menu', async () => {
    const { onOpenPreview } = await renderMock();

    await chooseFromMenu('Preview card states');

    expect(onOpenPreview).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId('coach-menu')).toBeNull();
  });

  test('"Start over" brings back the opening conversation and its replies, drops every card, and closes the menu', async () => {
    await renderMock();
    await fireEvent.press(button('Keep same duration'));
    await pass(MOCK_PROPOSAL_DELAY_MS);
    await fireEvent.press(button('Apply Updated Workout'));
    await pass(MOCK_APPLY_DELAY_MS);
    expect(cards()).toHaveLength(1);

    await chooseFromMenu('Start over');

    expect(screen.queryByTestId('coach-menu')).toBeNull();
    expect(bubbleTexts()).toEqual(MOCK_INTRO.map((item) => (item.kind === 'message' ? item.text : '')));
    expect(cards()).toHaveLength(0);
    expect(within(screen.getByTestId('suggested-replies')).getAllByRole('button')).toHaveLength(3);
  });

  test('"Start over" also starts the made-up coach over: the same chip gives the same workout again, as if nothing had been applied', async () => {
    await renderMock();
    await fireEvent.press(button('Keep same duration'));
    await pass(MOCK_PROPOSAL_DELAY_MS);
    await fireEvent.press(button('Apply Updated Workout'));
    await pass(MOCK_APPLY_DELAY_MS);
    await chooseFromMenu('Start over');

    await fireEvent.press(button('Keep same duration'));
    await pass(MOCK_PROPOSAL_DELAY_MS);

    within(screen.getByTestId('proposal-status')).getByText('Updated Workout');
    expect(button('Apply Updated Workout')).toBeEnabled();
  });

  test('"Start over" drops a reply that is still on its way', async () => {
    await renderMock();
    await typeAndSend('first');

    await chooseFromMenu('Start over');
    await pass(MOCK_PROPOSAL_DELAY_MS);

    expect(bubbles()).toHaveLength(MOCK_INTRO.length);
    expect(screen.queryByTestId('typing-indicator')).toBeNull();
  });
});

describe('<CoachScreen />: opened from a workout', () => {
  test('shows which workout it was opened from, and says nothing was changed or saved', async () => {
    await renderMock({ coachContext: { workoutId: 41, title: 'Core & Abs Focus' } });

    const context = screen.getByTestId('coach-context');
    expect(within(context).getByText('Opened from Core & Abs Focus')).toBeOnTheScreen();
    expect(context).toHaveTextContent(/Nothing was changed or saved/);
    expect(context).toHaveTextContent(/until you approve a revised proposal/);
    expect(bubbleTexts()).toEqual(MOCK_INTRO.map((item) => (item.kind === 'message' ? item.text : '')));
  });

  test('shows no such note when it was opened from the tab bar', async () => {
    await renderMock();

    expect(screen.queryByTestId('coach-context')).toBeNull();
  });
});

describe('<CoachScreen />: it is a mock, and it stays one', () => {
  test('makes no network request through a whole conversation: new workout, edit, refinement, apply, failure, start over', async () => {
    await renderMock();

    await typeAndSend('Create a 25-minute upper-body workout.');
    await pass(MOCK_PROPOSAL_DELAY_MS);
    await fireEvent.press(button('Use no equipment'));
    await pass(MOCK_PROPOSAL_DELAY_MS);
    await fireEvent.press(button('Apply This Workout'));
    await pass(MOCK_APPLY_DELAY_MS);
    await chooseFromMenu('Mock: next request fails');
    await typeAndSend('hello');
    await pass(MOCK_REPLY_DELAY_MS);
    await chooseFromMenu('Start over');
    await fireEvent.press(button('Keep same duration'));
    await pass(MOCK_PROPOSAL_DELAY_MS);

    expect(backend.requests).toEqual([]);
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });
});

describe('<CoachScreen />: the themes', () => {
  test.each([
    ['dark', dark],
    ['light', light],
  ] as const)("the coach's bubble is the plain surface and the user's is tinted emerald with an emerald outline, in the %s theme", async (scheme, colors) => {
    await renderMock({ scheme });

    expect(screen.getByTestId('message-m1')).toHaveStyle({ backgroundColor: colors.surface, borderColor: colors.border });
    expect(screen.getByTestId('message-m2')).toHaveStyle({ backgroundColor: colors.primarySubtle, borderColor: colors.accent });
    expect(screen.getByTestId('coach-screen')).toHaveStyle({ backgroundColor: colors.background });
  });

  test.each([
    ['dark', dark],
    ['light', light],
  ] as const)('the workout card follows the %s theme', async (scheme, colors) => {
    await renderMock({ scheme });
    await fireEvent.press(button('Keep same duration'));
    await pass(MOCK_PROPOSAL_DELAY_MS);

    expect(screen.getByTestId('proposal-card')).toHaveStyle({ backgroundColor: colors.surface, borderColor: colors.border });
    expect(within(screen.getByTestId('proposal-status')).getByText('Updated Workout')).toHaveStyle({ color: colors.accent });
    expect(screen.getByTestId('key-changes')).toHaveStyle({ backgroundColor: colors.primarySubtle });
  });

  test.each([
    ['dark', dark],
    ['light', light],
  ] as const)('the send button is emerald when there is something to send and dimmed when there is not, in the %s theme', async (scheme, colors) => {
    await renderMock({ scheme });
    expect(sendButton()).toHaveStyle({ backgroundColor: colors.disabledBackground });

    await fireEvent.changeText(input(), 'hi');

    expect(sendButton()).toHaveStyle({ backgroundColor: colors.primary });
  });
});

describe('<CoachScreen />: the safe areas and larger text', () => {
  test('keeps its content off the notch at the sides: the header, the list and the composer share the same margins', async () => {
    await render(
      <SafeAreaProvider initialMetrics={{ frame: { x: 0, y: 0, width: 360, height: 800 }, insets: { top: 40, bottom: 24, left: 8, right: 6 } }}>
        <ThemeProvider>
          <MockCoachScreen onBack={jest.fn()} onOpenPreview={jest.fn()} />
        </ThemeProvider>
      </SafeAreaProvider>,
    );

    for (const id of ['coach-header', 'chat-composer']) {
      expect(screen.getByTestId(id)).toHaveStyle({ paddingLeft: 8 + 16, paddingRight: 6 + 16 });
    }
    expect(screen.getByTestId('coach-messages')).toHaveProp('contentContainerStyle', expect.objectContaining({ paddingLeft: 24, paddingRight: 22 }));
  });

  test("message text follows the font size setting only up to the app's limit", async () => {
    await renderMock();

    expect(within(screen.getByTestId('message-m1')).getByText(/Hi, I'm/)).toHaveProp('maxFontSizeMultiplier', 1.5);
    expect(input()).toHaveProp('maxFontSizeMultiplier', 1.5);
  });
});

describe('<CoachScreen />: when it is hidden under another tab', () => {
  test('puts the keyboard away when it stops being the screen on show, and not before', async () => {
    const dismiss = jest.spyOn(Keyboard, 'dismiss');
    const gateway = createMockCoachGateway(createMockSwitches(), () => NOW);
    const view = await renderWithTheme(<CoachScreen gateway={gateway} openingFor={() => MOCK_OPENING} onBack={jest.fn()} active />, 'dark');
    expect(dismiss).not.toHaveBeenCalled();

    await view.rerender(
      <SafeAreaProvider>
        <ThemeProvider initialScheme="dark">
          <CoachScreen gateway={gateway} openingFor={() => MOCK_OPENING} onBack={jest.fn()} active={false} />
        </ThemeProvider>
      </SafeAreaProvider>,
    );

    expect(dismiss).toHaveBeenCalledTimes(1);
  });
});

describe('<CoachScreen />: a failure asking again cannot help', () => {
  test('is said in a bubble with no Try Again for a message, and in the card for a workout request', async () => {
    const fake = fakeGateway();
    await renderWith(fake.gateway);

    await typeAndSend('hello');
    await act(async () => {
      fake.sends.shift()!.reject(new ApiError('http', 401, 'could not validate credentials'));
    });

    within(screen.getByTestId('request-failed')).getByText('Your session has expired. Log in again.');
    expect(screen.queryByRole('button', { name: 'Try Again' })).toBeNull();
  });

  test('a workout request that fails the same way says so in the card, with no Try Again', async () => {
    const fake = fakeGateway();
    await renderWith(fake.gateway);

    await fireEvent.press(button('Keep same duration'));
    await act(async () => {
      fake.sends.shift()!.reject(new ApiError('http', 401, 'could not validate credentials'));
    });

    within(screen.getByTestId('proposal-generation-failed')).getByText('Your session has expired. Log in again.');
    expect(screen.queryByRole('button', { name: 'Try Again' })).toBeNull();
  });

  test('a Try Again that meets an expired session ends with no Try Again, in the bubble and in the card', async () => {
    const fake = fakeGateway();
    await renderWith(fake.gateway);

    // a lost connection: Try Again is offered, and pressed; the token has expired meanwhile
    await typeAndSend('hello');
    await act(async () => {
      fake.sends.shift()!.reject(new ApiError('network', null, null));
    });
    await fireEvent.press(within(screen.getByTestId('request-failed')).getByRole('button', { name: 'Try Again' }));
    await act(async () => {
      fake.sends.shift()!.reject(new ApiError('http', 401, 'could not validate credentials'));
    });

    within(screen.getByTestId('request-failed')).getByText('Your session has expired. Log in again.');
    expect(screen.queryByRole('button', { name: 'Try Again' })).toBeNull();
    // the screen is still usable: the person can type another message
    expect(input()).toBeEnabled();
  });

  test('and so does a request for a workout: the card has no Try Again after a retry meets an expired session', async () => {
    const fake = fakeGateway();
    await renderWith(fake.gateway);

    await fireEvent.press(button('Keep same duration'));
    await act(async () => {
      fake.sends.shift()!.reject(new ApiError('http', 503, 'the AI coach is not configured'));
    });
    await fireEvent.press(button('Try Again'));
    await act(async () => {
      fake.sends.shift()!.reject(new ApiError('http', 401, 'could not validate credentials'));
    });
    within(screen.getByTestId('proposal-generation-failed')).getByText('Your session has expired. Log in again.');
    expect(screen.queryByRole('button', { name: 'Try Again' })).toBeNull();
  });
});

describe('<CoachScreen />: dismissing a workout', () => {
  async function toTheNewWorkout() {
    const view = await renderMock();
    await typeAndSend('Create a 25-minute upper-body workout.');
    await pass(MOCK_PROPOSAL_DELAY_MS);
    return view;
  }

  test('Dismiss shows it being dismissed, and only when the backend has answered, Dismissed: and says nothing was saved', async () => {
    await toTheNewWorkout();

    await fireEvent.press(button('Dismiss'));
    expect(button('Dismissing…')).toBeDisabled();
    within(screen.getByTestId('proposal-status')).getByText('New Workout');
    expect(screen.queryByText('Dismissed')).toBeNull();

    await pass(MOCK_REJECT_DELAY_MS - 1);
    expect(screen.queryByText('Dismissed')).toBeNull();
    await pass(1);

    within(screen.getByTestId('proposal-status')).getByText('Dismissed');
    expect(screen.getByTestId('proposal-note')).toHaveTextContent('Dismissed. Nothing was saved.');
    expect(screen.queryByRole('button', { name: /Apply|Ask for More|Dismiss/ })).toBeNull();
    // the chips of a workout that can be changed are gone with it
    expect(screen.queryByTestId('suggested-replies')).toBeNull();
  });

  test('a dismissed workout cannot be applied: nothing is approved', async () => {
    const gateway = createMockCoachGateway(createMockSwitches(), () => NOW);
    const approve = jest.spyOn(gateway, 'approve');
    await renderWith(gateway);
    await typeAndSend('Create a 25-minute upper-body workout.');
    await pass(MOCK_PROPOSAL_DELAY_MS);

    await fireEvent.press(button('Dismiss'));
    await pass(MOCK_REJECT_DELAY_MS);

    expect(approve).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: /Apply/ })).toBeNull();
  });

  test('a double press on Dismiss dismisses it once', async () => {
    const gateway = createMockCoachGateway(createMockSwitches(), () => NOW);
    const reject = jest.spyOn(gateway, 'reject');
    await renderWith(gateway);
    await typeAndSend('Create a 25-minute upper-body workout.');
    await pass(MOCK_PROPOSAL_DELAY_MS);

    const dismiss = button('Dismiss');
    await fireEvent.press(dismiss);
    await fireEvent.press(dismiss);
    await fireEvent.press(dismiss);
    await pass(MOCK_REJECT_DELAY_MS);

    expect(reject).toHaveBeenCalledTimes(1);
    within(screen.getByTestId('proposal-status')).getByText('Dismissed');
  });

  test('says an updated workout dismissed leaves the saved one as it was', async () => {
    await renderMock();
    await fireEvent.press(button('Keep same duration'));
    await pass(MOCK_PROPOSAL_DELAY_MS);

    await fireEvent.press(button('Dismiss'));
    await pass(MOCK_REJECT_DELAY_MS);

    expect(screen.getByTestId('proposal-note')).toHaveTextContent('Dismissed. Nothing was saved, and “Core & Abs Focus” is as it was.');
  });

  test('while it is being dismissed a message cannot be sent, and Start over waits, and Apply is out of use', async () => {
    await renderMock();
    await fireEvent.press(button('Keep same duration'));
    await pass(MOCK_PROPOSAL_DELAY_MS);
    await fireEvent.press(button('Dismiss'));

    await fireEvent.changeText(input(), 'wait, change it');
    expect(sendButton()).toBeDisabled();
    expect(button('Apply Updated Workout')).toBeDisabled();
    await openMenu();
    expect(screen.getByRole('menuitem', { name: 'Start over' })).toBeDisabled();
    await fireEvent.press(screen.getByRole('button', { name: 'Close menu' }));

    await pass(MOCK_REJECT_DELAY_MS);
    expect(sendButton()).toBeEnabled();
  });

  test('the menu switch makes exactly the next dismissal fail: it says why, keeps the workout waiting, and Dismiss Again dismisses it', async () => {
    await toTheNewWorkout();
    await chooseFromMenu('Mock: next dismiss fails');

    await fireEvent.press(button('Dismiss'));
    await pass(MOCK_REJECT_DELAY_MS);

    const error = screen.getByTestId('dismiss-error');
    expect(error).toHaveProp('accessibilityRole', 'alert');
    within(error).getByText("Can't reach Formiq. Check your connection and try again.");
    within(screen.getByTestId('proposal-status')).getByText('New Workout');
    expect(screen.queryByText('Dismissed')).toBeNull();
    expect(button('Apply This Workout')).toBeEnabled();

    await fireEvent.press(button('Dismiss Again'));
    await pass(MOCK_REJECT_DELAY_MS);

    within(screen.getByTestId('proposal-status')).getByText('Dismissed');
    expect(screen.queryByTestId('dismiss-error')).toBeNull();
  });

  test('a failed dismissal does not stop the workout being applied', async () => {
    await toTheNewWorkout();
    await chooseFromMenu('Mock: next dismiss fails');
    await fireEvent.press(button('Dismiss'));
    await pass(MOCK_REJECT_DELAY_MS);

    await fireEvent.press(button('Apply This Workout'));
    await pass(MOCK_APPLY_DELAY_MS);

    within(screen.getByTestId('proposal-status')).getByText('Applied');
  });

  test('the backend not having it any more ends the card as no longer waiting, not as dismissed', async () => {
    const fake = fakeGateway();
    await renderWith(fake.gateway);
    await fireEvent.press(button('Keep same duration'));
    await act(async () => {
      fake.sends.shift()!.resolve({ reply: 'Here', proposal: mockProposal('edit', NOW, 2) });
    });

    await fireEvent.press(button('Dismiss'));
    await act(async () => {
      fake.rejections[0].reject(new ApiError('http', 404, 'there is no workout plan proposal'));
    });

    within(screen.getByTestId('proposal-status')).getByText('No longer waiting');
    expect(screen.queryByText('Dismissed')).toBeNull();
    expect(screen.getByTestId('proposal-note')).toHaveTextContent('This workout is no longer waiting: it expired. Ask the coach for a new one.');
  });

  describe('a 409 to a dismissal (the workout was already applied: the answer to its approval was lost)', () => {
    const ALREADY = () => new ApiError('http', 409, 'this proposal was already approved: it cannot be rejected');

    async function dismissedTooLate() {
      const fake = fakeGateway();
      await renderWith(fake.gateway);
      await fireEvent.press(button('Keep same duration'));
      const proposal = mockProposal('edit', NOW, 2);
      await act(async () => {
        fake.sends.shift()!.resolve({ reply: 'Here', proposal });
      });
      await fireEvent.press(button('Dismiss'));
      await act(async () => {
        fake.rejections[0].reject(ALREADY());
      });
      return { fake, proposal };
    }

    test('asks the approval again and shows the plan it saved as applied: never dismissed', async () => {
      const { fake, proposal } = await dismissedTooLate();

      // nothing is claimed before the backend answers the approval
      expect(screen.queryByText('Dismissed')).toBeNull();
      expect(screen.queryByText('Applied')).toBeNull();
      expect(fake.approvals).toHaveLength(1);
      expect(fake.approvals[0]).toMatchObject({ proposalId: proposal.proposal_id, binding: proposal.binding });

      await act(async () => {
        fake.approvals[0].resolve(mockSavedPlan(proposal, 100));
      });

      within(screen.getByTestId('proposal-status')).getByText('Applied');
      expect(screen.queryByText('Dismissed')).toBeNull();
      expect(screen.queryByTestId('dismiss-error')).toBeNull();
      expect(screen.queryByRole('button', { name: /Dismiss/ })).toBeNull();
    });

    test('when the saved plan was changed since, says it was already applied: neither dismissed nor applied again', async () => {
      const { fake } = await dismissedTooLate();

      await act(async () => {
        fake.approvals[0].reject(
          new ApiError('http', 409, 'this proposal was already approved, but the workout plan it saved was changed, cancelled or removed since'),
        );
      });

      within(screen.getByTestId('dismiss-error')).getByText('This workout was already applied. Check your plans.');
      expect(screen.queryByText('Dismissed')).toBeNull();
      expect(screen.queryByText('Applied')).toBeNull();
      expect(button('Apply Updated Workout')).toBeDisabled();
      expect(screen.queryByRole('button', { name: /Dismiss/ })).toBeNull();
    });
  });

  test('"Start over" works again once it has been dismissed', async () => {
    await toTheNewWorkout();
    await fireEvent.press(button('Dismiss'));
    await pass(MOCK_REJECT_DELAY_MS);

    await chooseFromMenu('Start over');

    expect(cards()).toHaveLength(0);
    expect(bubbleTexts()).toEqual(MOCK_INTRO.map((item) => (item.kind === 'message' ? item.text : '')));
  });
});

describe('<CoachScreen />: workouts waiting from before the conversation', () => {
  // the preview's switches leave proposals "made earlier" for the next time the screen looks, which Start over does
  async function leaveWaiting(menuItem: 'Mock: a workout is waiting' | 'Mock: two workouts are waiting') {
    await chooseFromMenu(menuItem);
    await chooseFromMenu('Start over');
    await pass(MOCK_PENDING_DELAY_MS);
  }

  test('there is nothing to show when nothing is waiting: the screen opens as it always did', async () => {
    await renderMock();
    await pass(MOCK_PENDING_DELAY_MS);

    expect(bubbleTexts()).toEqual(MOCK_INTRO.map((item) => (item.kind === 'message' ? item.text : '')));
    expect(cards()).toHaveLength(0);
    expect(screen.queryByTestId('waiting-proposals')).toBeNull();
    expect(screen.queryByTestId('recovery-failed')).toBeNull();
  });

  test('one is shown as its card, after a line that says it was proposed earlier, with when it was proposed and the three actions', async () => {
    await renderMock();

    await leaveWaiting('Mock: a workout is waiting');

    expect(bubbleTexts().at(-1)).toBe('You have a workout waiting for your approval. It was proposed earlier: look it over before you apply it.');
    expect(cards()).toHaveLength(1);
    within(screen.getByTestId('proposal-status')).getByText('Updated Workout');
    expect(screen.getByTestId('proposal-recovered')).toHaveTextContent('Proposed 12 min ago');
    expect(button('Apply Updated Workout')).toBeEnabled();
    expect(button('Ask for More Changes')).toBeEnabled();
    expect(button('Dismiss')).toBeEnabled();
    // it has Key Changes like any other: the backend's comparison came with it
    within(screen.getByTestId('key-changes')).getByText('Replaced Bicycle Crunches with Dead Bug');
  });

  test('shows it without applying, dismissing or changing anything: it waits for the person', async () => {
    const gateway = createMockCoachGateway(createMockSwitches({ waiting: 1 }), () => NOW);
    const approve = jest.spyOn(gateway, 'approve');
    const reject = jest.spyOn(gateway, 'reject');
    const send = jest.spyOn(gateway, 'send');
    await renderWith(gateway);

    await pass(MOCK_PENDING_DELAY_MS);
    await pass(60_000);

    expect(cards()).toHaveLength(1);
    within(screen.getByTestId('proposal-status')).getByText('Updated Workout');
    expect(approve).not.toHaveBeenCalled();
    expect(reject).not.toHaveBeenCalled();
    expect(send).not.toHaveBeenCalled();
  });

  test('is applied with its own Apply: Applying…, then Applied once the backend answers, and the caption says what it replaced', async () => {
    await renderMock();
    await leaveWaiting('Mock: a workout is waiting');

    await fireEvent.press(button('Apply Updated Workout'));
    expect(button('Applying…')).toBeDisabled();
    within(screen.getByTestId('proposal-status')).getByText('Updated Workout');
    await pass(MOCK_APPLY_DELAY_MS);

    within(screen.getByTestId('proposal-status')).getByText('Applied');
    expect(screen.getByTestId('proposal-caption')).toHaveTextContent(/^Replaced “Core & Abs Focus” with “Core Stability & Abs” for /);
  });

  test('is dismissed with its own Dismiss, and Dismissed is said once the backend answers', async () => {
    await renderMock();
    await leaveWaiting('Mock: a workout is waiting');

    await fireEvent.press(button('Dismiss'));
    expect(button('Dismissing…')).toBeDisabled();
    await pass(MOCK_REJECT_DELAY_MS);

    within(screen.getByTestId('proposal-status')).getByText('Dismissed');
  });

  test('can be changed: Ask for More Changes works on the only waiting workout, and the refinement is a newer card', async () => {
    await renderMock();
    await leaveWaiting('Mock: a workout is waiting');

    await fireEvent.press(button('Ask for More Changes'));
    expect(input()).toHaveProp('placeholder', 'What would you like to change?');
    await typeAndSend('easier on my knees');
    await pass(MOCK_PROPOSAL_DELAY_MS);

    expect(cards()).toHaveLength(2);
    within(cards()[0]).getByText('Older version');
    within(cards()[1]).getByRole('header', { name: 'Gentle Core & Abs' });
  });

  describe('several', () => {
    test('are listed to choose from: each with what it is, what it replaces, when it was proposed and a Review button, and none is a card', async () => {
      await renderMock();

      await leaveWaiting('Mock: two workouts are waiting');

      const list = within(screen.getByTestId('waiting-proposals'));
      list.getByText('2 workouts are waiting for your approval');
      expect(cards()).toHaveLength(0);
      const [newest, older] = screen.getAllByTestId(/^waiting-0/);
      // the newest first
      within(newest).getByText('Updated Workout');
      within(newest).getByText('Core Stability & Abs');
      within(newest).getByText('18 min • 6 exercises');
      within(newest).getByText('Replaces “Core & Abs Focus”');
      within(newest).getByText(/^Proposed 5 min ago • expires in 2[45] min$/);
      within(older).getByText('New Workout');
      within(older).getByText('Upper Body Strength');
      within(older).getByText(/^Proposed 12 min ago • expires in 1[78] min$/);
      expect(list.getAllByRole('button', { name: 'Review' })).toHaveLength(2);
      // nothing was chosen, applied or dismissed for the person
      expect(screen.queryByRole('button', { name: /Apply|Dismiss/ })).toBeNull();
    });

    test('keep the opening replies: the person has said nothing yet', async () => {
      await renderMock();

      await leaveWaiting('Mock: two workouts are waiting');

      expect(within(screen.getByTestId('suggested-replies')).getAllByRole('button')).toHaveLength(3);
    });

    test('Review puts that workout\'s card in the conversation and leaves the other listed', async () => {
      await renderMock();
      await leaveWaiting('Mock: two workouts are waiting');
      const [, older] = screen.getAllByTestId(/^waiting-0/);

      await fireEvent.press(within(older).getByRole('button', { name: 'Review' }));

      expect(cards()).toHaveLength(1);
      within(screen.getByTestId('proposal-status')).getByText('New Workout');
      lastCard().getByRole('header', { name: 'Upper Body Strength' });
      expect(screen.getByTestId('proposal-recovered')).toHaveTextContent('Proposed 12 min ago');
      expect(screen.getAllByTestId(/^waiting-0/)).toHaveLength(1);
      // still nothing applied or dismissed
      expect(button('Apply This Workout')).toBeEnabled();
    });

    test('an older one, which the coach would not change, says why instead of offering to ask for changes', async () => {
      await renderMock();
      await leaveWaiting('Mock: two workouts are waiting');
      const [, older] = screen.getAllByTestId(/^waiting-0/);

      await fireEvent.press(within(older).getByRole('button', { name: 'Review' }));

      expect(screen.queryByRole('button', { name: 'Ask for More Changes' })).toBeNull();
      expect(screen.getByTestId('ask-unavailable')).toHaveTextContent(
        'The coach changes your newest waiting workout, “Core Stability & Abs”. This older one can only be applied or dismissed.',
      );
      expect(button('Apply This Workout')).toBeEnabled();
      expect(button('Dismiss')).toBeEnabled();
      // and the quick ways to change it are not offered either
      expect(screen.queryByTestId('suggested-replies')).toBeNull();
    });

    test('the newest one can be changed, and once both were chosen the list is gone', async () => {
      await renderMock();
      await leaveWaiting('Mock: two workouts are waiting');
      const [newest, older] = screen.getAllByTestId(/^waiting-0/);

      await fireEvent.press(within(older).getByRole('button', { name: 'Review' }));
      await fireEvent.press(within(screen.getAllByTestId(/^waiting-0/)[0]).getByRole('button', { name: 'Review' }));

      expect(screen.queryByTestId('waiting-proposals')).toBeNull();
      expect(cards()).toHaveLength(2);
      const [first, second] = cards();
      expect(within(first).queryByRole('button', { name: 'Ask for More Changes' })).toBeNull();
      expect(within(second).getByRole('button', { name: 'Ask for More Changes' })).toBeEnabled();
      expect(newest).toBeDefined();
    });

    test('the newest, once dismissed, no longer stands in the way of changing the older one', async () => {
      await renderMock();
      await leaveWaiting('Mock: two workouts are waiting');
      await fireEvent.press(within(screen.getAllByTestId(/^waiting-0/)[1]).getByRole('button', { name: 'Review' }));
      await fireEvent.press(within(screen.getAllByTestId(/^waiting-0/)[0]).getByRole('button', { name: 'Review' }));
      expect(within(cards()[0]).queryByRole('button', { name: 'Ask for More Changes' })).toBeNull();

      await fireEvent.press(within(cards()[1]).getByRole('button', { name: 'Dismiss' }));
      await pass(MOCK_REJECT_DELAY_MS);

      expect(within(cards()[0]).getByRole('button', { name: 'Ask for More Changes' })).toBeEnabled();
      expect(screen.queryByTestId('ask-unavailable')).toBeNull();
    });

    test('applying a chosen one that replaces the saved workout takes the other that replaces it out of the list', async () => {
      await renderMock();
      await leaveWaiting('Mock: two workouts are waiting');
      // the second listed is the new workout, which replaces nothing: it stays listed
      await fireEvent.press(within(screen.getAllByTestId(/^waiting-0/)[0]).getByRole('button', { name: 'Review' }));
      await fireEvent.press(button('Apply Updated Workout'));
      await pass(MOCK_APPLY_DELAY_MS);

      within(screen.getByTestId('proposal-status')).getByText('Applied');
      expect(screen.getAllByTestId(/^waiting-0/)).toHaveLength(1);
      within(screen.getByTestId('waiting-proposals')).getByText('Upper Body Strength');
    });
  });

  test('is not looked for while the screen is hidden, and is looked for each time it is shown again', async () => {
    const fake = fakeGateway();
    const view = await renderWithTheme(<CoachScreen gateway={fake.gateway} openingFor={() => MOCK_OPENING} onBack={jest.fn()} active={false} />, 'dark');
    expect(fake.gateway.pending).not.toHaveBeenCalled();
    const shown = (active: boolean) => (
      <SafeAreaProvider>
        <ThemeProvider initialScheme="dark">
          <CoachScreen gateway={fake.gateway} openingFor={() => MOCK_OPENING} onBack={jest.fn()} active={active} />
        </ThemeProvider>
      </SafeAreaProvider>
    );

    await view.rerender(shown(true));
    expect(fake.gateway.pending).toHaveBeenCalledTimes(1);
    fake.waiting.list = [mockPendingProposal('edit', NOW, 1, 3)];
    await view.rerender(shown(false));
    await view.rerender(shown(true));

    expect(fake.gateway.pending).toHaveBeenCalledTimes(2);
    expect(cards()).toHaveLength(1);
    // and coming back again does not add it twice
    await view.rerender(shown(false));
    await view.rerender(shown(true));
    expect(cards()).toHaveLength(1);
    expect(fake.gateway.pending).toHaveBeenCalledTimes(3);
  });

  test('a look that fails says so in a notice that does not block the conversation, with Try Again, and never says there is none', async () => {
    const fake = fakeGateway();
    fake.waiting.list = new ApiError('network', null, null);
    await renderWith(fake.gateway);

    const notice = within(screen.getByTestId('recovery-failed'));
    notice.getByText("Couldn't check your waiting workouts");
    notice.getByText("Can't reach Formiq. Couldn't check for workouts waiting for your approval.");
    expect(cards()).toHaveLength(0);
    // the conversation goes on: a message can be sent
    await fireEvent.changeText(input(), 'hello');
    expect(sendButton()).toBeEnabled();

    fake.waiting.list = [mockPendingProposal('new', NOW, 1, 4)];
    await fireEvent.press(notice.getByRole('button', { name: 'Try Again' }));

    expect(screen.queryByTestId('recovery-failed')).toBeNull();
    expect(cards()).toHaveLength(1);
    within(screen.getByTestId('proposal-status')).getByText('New Workout');
    expect(fake.gateway.pending).toHaveBeenCalledTimes(2);
  });

  test('an expired session says so with no Try Again', async () => {
    const fake = fakeGateway();
    fake.waiting.list = new ApiError('http', 401, 'could not validate credentials');
    await renderWith(fake.gateway);

    within(screen.getByTestId('recovery-failed')).getByText('Your session has expired. Log in again.');
    expect(screen.queryByTestId('recovery-retry')).toBeNull();
  });

  test('nothing is looked for while a workout is being applied, dismissed or asked for: Try Again then does nothing', async () => {
    const fake = fakeGateway();
    fake.waiting.list = new ApiError('network', null, null);
    await renderWith(fake.gateway);
    await fireEvent.press(button('Keep same duration'));
    const asked = fake.gateway.pending.mock.calls.length;

    await fireEvent.press(screen.getByTestId('recovery-retry'));

    expect(fake.gateway.pending).toHaveBeenCalledTimes(asked);
    expect(screen.getByTestId('recovery-failed')).toBeOnTheScreen();
  });

  test('a late answer from before "Start over" shows nothing of the old conversation', async () => {
    const fake = fakeGateway();
    fake.waiting.hold = true;
    await renderWith(fake.gateway);
    expect(fake.lists).toHaveLength(1);

    await chooseFromMenu('Start over');
    expect(fake.lists).toHaveLength(2);
    await act(async () => {
      fake.lists[0].resolve([mockPendingProposal('edit', NOW, 1, 3)]);
    });

    expect(cards()).toHaveLength(0);
    expect(screen.queryByTestId('waiting-proposals')).toBeNull();
  });
});

describe('<CoachScreen />: the workout the conversation is about', () => {
  const CORE = { workoutId: 41, title: 'Core & Abs Focus' };

  async function renderAbout() {
    const fake = fakeGateway();
    const view = await renderWithTheme(
      <CoachScreen gateway={fake.gateway} openingFor={coachOpening} onBack={jest.fn()} coachContext={CORE} />,
      'dark',
    );
    return { ...view, fake };
  }

  test('names it in every message and in the one after an apply, to the plan that replaced it', async () => {
    const { fake } = await renderAbout();
    await fireEvent.press(button('Make it shorter'));
    expect(fake.sends[0].request).toEqual({ message: 'Make it shorter', history: [], workoutPlanId: 41 });
    await act(async () => {
      fake.sends.shift()!.resolve({ reply: 'Here', proposal: mockProposal('edit', NOW, 2) });
    });
    // opened from the workout, and it says so
    screen.getByTestId('coach-context');

    await fireEvent.press(button('Apply Updated Workout'));
    await act(async () => {
      fake.approvals[0].resolve(mockSavedPlan(mockProposal('edit', NOW, 2), 100));
    });

    // the workout it was opened from was replaced: the note about it goes, and the next change is to the plan that replaced it
    expect(screen.queryByTestId('coach-context')).toBeNull();
    await typeAndSend('now a bit longer');
    expect(fake.sends[0].request.workoutPlanId).toBe(100);
  });

  test('a message about a workout that can no longer be edited says so, in a bubble with no Try Again', async () => {
    const { fake } = await renderAbout();

    await typeAndSend('make it shorter');
    await act(async () => {
      fake.sends.shift()!.reject(new ApiError('http', 409, 'workout plan 41 is CANCELLED'));
    });

    within(screen.getByTestId('request-failed')).getByText("This workout can't be edited any more — it was replaced or cancelled. Start over to pick another.");
    expect(screen.queryByRole('button', { name: 'Try Again' })).toBeNull();
  });

  test('the same failure to a request for a workout is in the card, with no Try Again', async () => {
    const { fake } = await renderAbout();

    await fireEvent.press(button('Make it shorter'));
    await act(async () => {
      fake.sends.shift()!.reject(new ApiError('http', 404, 'user 7 has no workout plan 41'));
    });

    within(screen.getByTestId('proposal-generation-failed')).getByText(/can't be edited any more/);
    expect(screen.queryByRole('button', { name: 'Try Again' })).toBeNull();
  });

  test('still warns when the proposal replaces another workout than the one the conversation is about', async () => {
    const { fake } = await renderAbout();
    await fireEvent.press(button('Make it shorter'));
    const other = mockProposal('edit', NOW, 2);

    await act(async () => {
      fake.sends.shift()!.resolve({
        reply: 'Here',
        proposal: { ...other, revision: other.revision && { ...other.revision, replaces_plan_id: 99, replaces_plan_name: 'Leg Day' }, changes: null },
      });
    });

    expect(within(screen.getByTestId('off-target-note')).getByText('This replaces “Leg Day”, not “Core & Abs Focus”, which you opened the coach from.')).toBeOnTheScreen();
  });
});

describe.each([
  ['dark', dark],
  ['light', light],
] as const)('<CoachScreen />: what is new, in the %s theme', (scheme, colors) => {
  test('the list of waiting workouts is on the surface, with the muted line for when they were proposed', async () => {
    const fake = fakeGateway();
    fake.waiting.list = [mockPendingProposal('edit', new Date(), 2, 5), mockPendingProposal('new', new Date(), 1, 12)];
    await renderWithTheme(<CoachScreen gateway={fake.gateway} openingFor={() => MOCK_OPENING} onBack={jest.fn()} />, scheme);

    const [entry] = screen.getAllByTestId(/^waiting-0/);
    expect(entry).toHaveStyle({ backgroundColor: colors.surface, borderColor: colors.border });
    expect(within(entry).getByText('Updated Workout')).toHaveStyle({ color: colors.accent });
    expect(within(entry).getByTestId(/^waiting-when-/)).toHaveStyle({ color: colors.textMuted });
    expect(within(entry).getByRole('button', { name: 'Review' })).toHaveStyle({ backgroundColor: colors.surface, borderColor: colors.borderStrong });
  });

  test('the notice that waiting workouts could not be looked up is in the error color', async () => {
    const fake = fakeGateway();
    fake.waiting.list = new ApiError('network', null, null);
    await renderWithTheme(<CoachScreen gateway={fake.gateway} openingFor={() => MOCK_OPENING} onBack={jest.fn()} />, scheme);

    expect(within(screen.getByTestId('recovery-failed')).getByText("Couldn't check your waiting workouts")).toHaveStyle({ color: colors.error });
  });

  test('a workout waiting from before says when it was proposed in the muted color, and the dismissed card is muted', async () => {
    const fake = fakeGateway();
    // made 7 minutes before the clock the test runs on (the pauses are faked, the date is not)
    fake.waiting.list = [mockPendingProposal('new', new Date(), 1, 7)];
    await renderWithTheme(<CoachScreen gateway={fake.gateway} openingFor={() => MOCK_OPENING} onBack={jest.fn()} />, scheme);

    expect(screen.getByTestId('proposal-recovered')).toHaveTextContent('Proposed 7 min ago');
    expect(screen.getByTestId('proposal-recovered')).toHaveStyle({ color: colors.textMuted });
    await fireEvent.press(button('Dismiss'));
    await act(async () => {
      fake.rejections[0].resolve();
    });
    expect(within(screen.getByTestId('proposal-status')).getByText('Dismissed')).toHaveStyle({ color: colors.textMuted });
  });
});
