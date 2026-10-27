import { fireEvent, screen, within } from '@testing-library/react-native';

import type { PendingProposal } from '../src/api';

import { waitingDetails } from '../src/coach/waitingDetails';
import { WaitingProposals } from '../src/coach/WaitingProposals';
import { mockPendingProposal } from '../src/mock/coachProposalsMock';
import { renderWithTheme } from '../test-utils/renderWithTheme';

const NOW = new Date(2026, 9, 22, 9, 0, 0);
const entries = (count: number) =>
  Array.from({ length: count }, (_, index) => mockPendingProposal(index % 2 === 0 ? 'new' : 'edit', NOW, index + 1, 5 + index));

describe('the list of workouts waiting from before', () => {
  test('one says "1 workout is waiting", not "1 workouts are": it is chosen, not one of several', async () => {
    await renderWithTheme(<WaitingProposals entries={entries(1)} onReview={jest.fn()} now={NOW} />);

    screen.getByText('1 workout is waiting for your approval');
    screen.getByText('It was proposed earlier. Choose it to look it over: it is not applied or dismissed until you do.');
    expect(screen.queryByText(/workouts are waiting/)).toBeNull();
    expect(screen.queryByText(/Choose one/)).toBeNull();
  });

  test.each([2, 3, 10])('%i say how many, in the plural', async (count) => {
    await renderWithTheme(<WaitingProposals entries={entries(count)} onReview={jest.fn()} now={NOW} />);

    screen.getByText(`${count} workouts are waiting for your approval`);
    screen.getByText('They were proposed earlier. Choose one to look it over: none is applied or dismissed until you do.');
  });
});

// Workouts that wait under one name cannot be told apart by it: the list says what else the backend's answer tells them
// apart by, from its own fields, and leaves a workout with a name of its own as it was.
describe('waiting workouts with the same name', () => {
  // NOW is 22 Oct 2026, 9:00 am (the device's own time). A proposal made `minutesAgo` minutes before that.
  const made = (sequence: number, name: string, scheduledDate: string, minutesAgo = 12, extraSeconds = 0): PendingProposal => {
    const base = mockPendingProposal('edit', NOW, sequence, minutesAgo);
    const createdAt = new Date(new Date(base.created_at).getTime() + extraSeconds * 1000).toISOString();
    return { ...base, name, scheduled_date: scheduledDate, created_at: createdAt };
  };
  const id = (entry: PendingProposal) => entry.proposal_id;
  const detail = (entry: PendingProposal) => screen.queryByTestId(`waiting-detail-${id(entry)}`);

  test('two of one name on different days say which day each is for: today, tomorrow, or the date', async () => {
    const today = made(1, 'Leg Day', '2026-10-22');
    const tomorrow = made(2, 'Leg Day', '2026-10-23', 5);
    const later = made(3, 'Leg Day', '2026-10-30', 3);
    await renderWithTheme(<WaitingProposals entries={[later, tomorrow, today]} onReview={jest.fn()} now={NOW} />);

    expect(detail(today)).toHaveTextContent('For today');
    expect(detail(tomorrow)).toHaveTextContent('For tomorrow');
    expect(detail(later)).toHaveTextContent('For Fri, 30 Oct');
    // different days tell them apart: the time they were proposed is not added
    expect(screen.queryByText(/Proposed at/)).toBeNull();
  });

  test('two of one name on the same day also say when each was proposed, which does not change as the list stays open', async () => {
    const earlier = made(1, 'Leg Day', '2026-10-22', 12);
    const later = made(2, 'Leg Day', '2026-10-22', 5);
    const view = await renderWithTheme(<WaitingProposals entries={[later, earlier]} onReview={jest.fn()} now={NOW} />);

    expect(detail(earlier)).toHaveTextContent('For today • Proposed at 8:48 am');
    expect(detail(later)).toHaveTextContent('For today • Proposed at 8:55 am');

    // ten minutes on, the relative lines have moved and the stable one has not
    await view.unmount();
    await renderWithTheme(<WaitingProposals entries={[later, earlier]} onReview={jest.fn()} now={new Date(NOW.getTime() + 10 * 60_000)} />);
    screen.getByText('Proposed 22 min ago • expires in 8 min', { exact: false });
    expect(detail(earlier)).toHaveTextContent('For today • Proposed at 8:48 am');
    expect(detail(later)).toHaveTextContent('For today • Proposed at 8:55 am');
  });

  test('two proposed in the same minute are told apart by the second', async () => {
    const first = made(1, 'Leg Day', '2026-10-22', 5, 7);
    const second = made(2, 'Leg Day', '2026-10-22', 5, 41);
    await renderWithTheme(<WaitingProposals entries={[second, first]} onReview={jest.fn()} now={NOW} />);

    expect(detail(first)).toHaveTextContent('For today • Proposed at 8:55:07 am');
    expect(detail(second)).toHaveTextContent('For today • Proposed at 8:55:41 am');
  });

  test('a workout with a name of its own has no detail, and looks as it did, beside two that share one', async () => {
    const own = made(1, 'Core & Abs Focus', '2026-10-22', 20);
    const one = made(2, 'Leg Day', '2026-10-22', 12);
    const two = made(3, 'Leg Day', '2026-10-23', 5);
    await renderWithTheme(<WaitingProposals entries={[two, one, own]} onReview={jest.fn()} now={NOW} />);

    expect(detail(own)).toBeNull();
    expect(detail(one)).not.toBeNull();
    expect(detail(two)).not.toBeNull();
    const card = within(screen.getByTestId(`waiting-${id(own)}`));
    card.getByText('Updated Workout');
    card.getByText('Core & Abs Focus');
    expect(card.queryByText(/^For /)).toBeNull();
    expect(card.queryByText(/Proposed at/)).toBeNull();
    card.getByTestId(`waiting-when-${id(own)}`);
  });

  test('a list where every name is its own has no detail at all: the list is exactly as it was', async () => {
    const entriesOfOwn = [made(1, 'Core & Abs Focus', '2026-10-22'), made(2, 'Leg Day', '2026-10-22', 5), made(3, 'Upper Body', '2026-10-23', 3)];
    await renderWithTheme(<WaitingProposals entries={entriesOfOwn} onReview={jest.fn()} now={NOW} />);

    expect(screen.queryAllByTestId(/^waiting-detail-/)).toHaveLength(0);
  });

  test('a name is the same for a person when only the capitals or the spaces around it differ', async () => {
    const a = made(1, 'Leg Day', '2026-10-22', 12);
    const b = made(2, '  leg day ', '2026-10-23', 5);
    await renderWithTheme(<WaitingProposals entries={[b, a]} onReview={jest.fn()} now={NOW} />);

    expect(detail(a)).toHaveTextContent('For today');
    expect(detail(b)).toHaveTextContent('For tomorrow');
  });

  test('of three, only the two that tie on a day say when they were proposed', async () => {
    const first = made(1, 'Leg Day', '2026-10-22', 12);
    const second = made(2, 'Leg Day', '2026-10-22', 5);
    const third = made(3, 'Leg Day', '2026-10-23', 3);
    await renderWithTheme(<WaitingProposals entries={[third, second, first]} onReview={jest.fn()} now={NOW} />);

    expect(detail(first)).toHaveTextContent('For today • Proposed at 8:48 am');
    expect(detail(second)).toHaveTextContent('For today • Proposed at 8:55 am');
    expect(detail(third)).toHaveTextContent(/^For tomorrow$/);
  });

  test('says only what can be read: a time that is not a time is left out, never made up', () => {
    const a = made(1, 'Leg Day', '2026-10-22', 12);
    const b = { ...made(2, 'Leg Day', '2026-10-22', 5), created_at: 'sometime' };

    const details = waitingDetails([a, b], NOW);

    expect(details.get(id(a))).toBe('For today • Proposed at 8:48 am');
    expect(details.get(id(b))).toBe('For today');
  });

  test('pressing Review still reviews that one proposal', async () => {
    const onReview = jest.fn();
    const one = made(1, 'Leg Day', '2026-10-22', 12);
    const two = made(2, 'Leg Day', '2026-10-23', 5);
    await renderWithTheme(<WaitingProposals entries={[two, one]} onReview={onReview} now={NOW} />);

    await fireEvent.press(screen.getByTestId(`review-${id(one)}`));

    expect(onReview).toHaveBeenCalledWith(id(one));
  });
});
