import { fireEvent, screen, within } from '@testing-library/react-native';

import { DISCOVER_AREAS, DISCOVER_NOTE, DiscoverScreen } from '../src/discover/DiscoverScreen';
import { themes, type ThemeScheme } from '../src/theme';
import { CATEGORY_COLORS } from '../src/workouts/categoryColors';
import { WORKOUT_IMAGES, workoutImageKey } from '../src/workouts/workoutImages';
import { renderWithTheme } from '../test-utils/renderWithTheme';

const dark = themes.dark.colors;

async function renderDiscover(scheme: ThemeScheme = 'dark') {
  const onOpen = jest.fn();
  const view = await renderWithTheme(<DiscoverScreen onOpen={onOpen} />, scheme);
  return { ...view, onOpen };
}

describe('<DiscoverScreen />', () => {
  test('says what it is for, with a heading', async () => {
    await renderDiscover();

    screen.getByRole('header', { name: 'Discover' });
    screen.getByText('Explore workouts, exercises, mobility and recovery.');
  });

  test('has an area each for workouts, exercises, mobility and recovery, in that order', async () => {
    await renderDiscover();

    expect(DISCOVER_AREAS.map((area) => area.title)).toEqual(['Workouts', 'Exercises', 'Mobility', 'Recovery']);
    expect(screen.getAllByRole('button').map((node) => node.props.accessibilityLabel)).toEqual([
      'Workouts. Plans and sessions to train with.',
      'Exercises. Moves, and how to do them well.',
      'Mobility. Stretch, warm up and move better.',
      'Recovery. Food, hydration and rest after training.',
    ]);
  });

  test.each([
    ['Workouts', 'workouts'],
    ['Exercises', 'exercises'],
    ['Mobility', 'mobility'],
    ['Recovery', 'nutrition'],
  ])('the %s card is one button that opens %s, and nothing else', async (title, section) => {
    const { onOpen } = await renderDiscover();

    await fireEvent.press(screen.getByRole('button', { name: new RegExp(`^${title}\\.`) }));

    expect(onOpen.mock.calls).toEqual([[section]]);
  });

  test('every card wears the photograph of its kind of workout, and a call to action only as an arrow', async () => {
    await renderDiscover();

    for (const area of DISCOVER_AREAS) {
      const card = screen.getByTestId(`discover-${area.id}`);
      expect(within(card).getByTestId(`discover-${area.id}-photo`)).toHaveProp(
        'source',
        WORKOUT_IMAGES[workoutImageKey(area.category)],
      );
      expect(within(card).getByTestId('icon-arrow-right', { includeHiddenElements: true })).toBeOnTheScreen();
    }
  });

  test.each(['dark', 'light'] as const)('in the %s theme the cards wear their category colours in the dark palette and the words are white', async (scheme) => {
    await renderDiscover(scheme as ThemeScheme);

    for (const area of DISCOVER_AREAS) {
      const palette = CATEGORY_COLORS[area.category].dark;
      expect(screen.getByTestId(`discover-${area.id}`)).toHaveStyle({
        backgroundColor: palette.blend,
        borderColor: palette.border,
      });
      expect(within(screen.getByTestId(`discover-${area.id}`)).getByText(area.title)).toHaveStyle({ color: dark.textPrimary });
    }
  });

  test('says at its foot that each area opens a placeholder until it is designed: nothing pretends to be real', async () => {
    await renderDiscover();

    expect(screen.getByTestId('discover-note')).toHaveTextContent(DISCOVER_NOTE);
    expect(DISCOVER_NOTE).toBe('Each area opens a placeholder until its own screen is designed.');
  });

  test("shows no user's data: no counts, minutes or progress", async () => {
    await renderDiscover();

    expect(screen.queryByText(/\d/)).toBeNull();
  });
});
