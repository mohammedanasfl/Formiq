import { useState } from 'react';
import { Dimensions, StyleSheet, type TextStyle } from 'react-native';
import { fireEvent, render, screen, within } from '@testing-library/react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { MOCK_TODAY_WORKOUT } from '../src/mock/workoutDetailsMock';
import { ThemeProvider, themes, type ThemeScheme } from '../src/theme';
import { exerciseGif, EXERCISE_GIFS } from '../src/workouts/exerciseGifs';
import { exerciseImage } from '../src/workouts/exerciseImages';
import { ExerciseDetailsScreen } from '../src/workouts/ExerciseDetailsScreen';
import type { PlannedExercise } from '../src/workouts/planDetails';
import { renderWithTheme } from '../test-utils/renderWithTheme';

const dark = themes.dark.colors;
const light = themes.light.colors;
const HIDDEN = { includeHiddenElements: true };
const textColor = (node: { props: { style?: unknown } }) => (StyleSheet.flatten(node.props.style as TextStyle) as TextStyle).color;

// the exercise as a plan and the catalog would hand it over: every field the screen can show
const squat: PlannedExercise = {
  id: 42,
  order: 3,
  section: 'MAIN_WORKOUT',
  name: 'Goblet Squat',
  sets: 3,
  reps: 12,
  equipment: ['Dumbbell'],
  muscles: [
    { name: 'Quadriceps', role: 'PRIMARY' },
    { name: 'Glutes', role: 'SECONDARY' },
    { name: 'Core', role: 'SECONDARY' },
  ],
  instructions: ['Hold the weight at your chest.', 'Sit down between your knees.', 'Stand back up.'],
  description: 'A beginner squatting exercise.',
  restSeconds: 60,
  weightKg: 12.5,
  notes: 'Keep your heels down.',
  animation: exerciseGif('squat'),
  image: exerciseImage('squats'),
};
// an exercise the catalog says nothing about: only what the plan itself gives
const bare: PlannedExercise = { id: 'b1', order: 1, section: 'MAIN_WORKOUT', name: 'Mystery Move', sets: 2, reps: 8 };

// holds the count of sets done the way the app does, so completing a set shows
function Harness({ exercise, initial, onBack, onChange }: { exercise: PlannedExercise; initial: number; onBack: () => void; onChange: (count: number) => void }) {
  const [count, setCount] = useState(initial);
  return (
    <ExerciseDetailsScreen
      exercise={exercise}
      onBack={onBack}
      completedSets={count}
      onCompletedSetsChange={(next) => {
        setCount(next);
        onChange(next);
      }}
    />
  );
}

async function renderScreen(exercise: PlannedExercise = squat, options: { scheme?: ThemeScheme; completed?: number } = {}) {
  const onBack = jest.fn();
  const onChange = jest.fn();
  const view = await renderWithTheme(<Harness exercise={exercise} initial={options.completed ?? 0} onBack={onBack} onChange={onChange} />, options.scheme);
  return { ...view, onBack, onChange };
}

const tab = (name: string) => screen.getByRole('tab', { name });
const press = (name: string) => fireEvent.press(screen.getByRole('button', { name }));
// what expo-image's native view sends when a picture cannot be decoded
const imageError = () => ({ nativeEvent: { error: 'could not decode the animation' } });
const stepper = () => screen.getByTestId('exercise-stepper-value');

describe('the top of the screen', () => {
  test("shows the pressed exercise's own name as the heading, not an example", async () => {
    await renderScreen();

    screen.getByRole('header', { name: 'Goblet Squat' });
    expect(screen.queryByText('3/4 Sit-Up')).toBeNull();
  });

  test('shows its primary muscle and its equipment as compact labels', async () => {
    await renderScreen();

    const labels = within(screen.getByTestId('exercise-labels'));
    labels.getByText('Quadriceps');
    labels.getByText('Dumbbell');
    expect(labels.queryByText('Glutes')).toBeNull();
  });

  test('says "Bodyweight" when the catalog lists no equipment', async () => {
    await renderScreen({ ...squat, equipment: [] });

    within(screen.getByTestId('exercise-labels')).getByText('Bodyweight');
  });

  test('has no labels at all for an exercise that carries neither muscles nor equipment', async () => {
    await renderScreen(bare);

    expect(screen.queryByTestId('exercise-labels')).toBeNull();
    screen.getByRole('header', { name: 'Mystery Move' });
  });

  test('has a Back arrow that goes back, and no overflow menu with nothing in it', async () => {
    const { onBack } = await renderScreen();

    await press('Back');

    expect(onBack).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('button', { name: /more|menu|options/i })).toBeNull();
  });
});

describe('the animation', () => {
  test('plays the exercise\'s looping GIF in the image view, with no video player or controls', async () => {
    await renderScreen();

    const gif = screen.getByTestId('exercise-animation');
    // expo-image hands the native view a list of sources
    expect(gif).toHaveProp('source', [EXERCISE_GIFS.squat]);
    expect(gif).toHaveProp('accessibilityLabel', 'Goblet Squat, looping animation');
    expect(screen.queryByLabelText(/play|pause|video|replay/i)).toBeNull();
    expect(screen.queryByRole('button', { name: /play|pause/i })).toBeNull();
  });

  test('is drawn in explicit dp in the GIF\'s own 16 : 9 shape, the width of the content', async () => {
    await renderScreen();

    const width = Dimensions.get('window').width - 2 * 20;
    expect(screen.getByTestId('exercise-animation')).toHaveStyle({ width, height: Math.round((width * 270) / 480) });
    expect(screen.getByTestId('exercise-animation-area')).toHaveStyle({ width, height: Math.round((width * 270) / 480), overflow: 'hidden' });
  });

  test('says the supplied animations are development placeholders', async () => {
    await renderScreen();

    expect(within(screen.getByTestId('exercise-animation-caption')).getByText('Placeholder animation')).toBeOnTheScreen();
  });

  test('keeps its label inside the area, whatever the font size', async () => {
    await renderScreen({ ...squat, animation: null });

    const width = Dimensions.get('window').width - 2 * 20;
    expect(screen.getByTestId('exercise-animation-caption')).toHaveStyle({ maxWidth: width - 16, left: 8, top: 8 });
  });

  test('says nothing of the sort for a real exercise animation', async () => {
    await renderScreen({ ...squat, animation: { source: { uri: 'https://example.com/squat.gif' }, placeholder: false } });

    expect(screen.getByTestId('exercise-animation')).toHaveProp('source', [{ uri: 'https://example.com/squat.gif' }]);
    expect(screen.queryByTestId('exercise-animation-caption')).toBeNull();
  });

  test('with no animation shows the still picture, labelled as a still: a still does not pass for an animation', async () => {
    await renderScreen({ ...squat, animation: null });

    expect(screen.queryByTestId('exercise-animation')).toBeNull();
    expect(screen.getByTestId('exercise-still')).toHaveProp('accessibilityLabel', 'Goblet Squat, still picture');
    within(screen.getByTestId('exercise-animation-caption')).getByText('Still picture · no animation yet');
  });

  test('with neither an animation nor a picture shows a plain panel that says so', async () => {
    await renderScreen(bare);

    expect(screen.queryByTestId('exercise-animation')).toBeNull();
    expect(screen.queryByTestId('exercise-still')).toBeNull();
    expect(screen.getByTestId('exercise-animation-empty')).toBeOnTheScreen();
    within(screen.getByTestId('exercise-animation-caption')).getByText('No animation yet');
  });

  test('falls back to the still picture when the GIF fails to load, and says so', async () => {
    await renderScreen();

    await fireEvent(screen.getByTestId('exercise-animation'), 'error', imageError());

    expect(screen.queryByTestId('exercise-animation')).toBeNull();
    expect(screen.getByTestId('exercise-still')).toBeOnTheScreen();
    within(screen.getByTestId('exercise-animation-caption')).getByText("Animation couldn't load · still picture");
  });

  test('falls back to the plain panel when the GIF fails and there is no picture', async () => {
    await renderScreen({ ...squat, image: null });

    await fireEvent(screen.getByTestId('exercise-animation'), 'error', imageError());

    expect(screen.getByTestId('exercise-animation-empty')).toBeOnTheScreen();
    within(screen.getByTestId('exercise-animation-caption')).getByText("Animation couldn't load");
  });

  test('drops a still picture that fails too, leaving the plain panel and never a broken image', async () => {
    await renderScreen({ ...squat, animation: null });

    await fireEvent(screen.getByTestId('exercise-still'), 'error');

    expect(screen.queryByTestId('exercise-still')).toBeNull();
    expect(screen.getByTestId('exercise-animation-empty')).toBeOnTheScreen();
  });

  test('keeps the same size in every state, so nothing moves when one gives way to another', async () => {
    await renderScreen();
    const sized = () => StyleSheet.flatten(screen.getByTestId('exercise-animation-area').props.style);
    const withGif = sized();

    await fireEvent(screen.getByTestId('exercise-animation'), 'error', imageError());
    await fireEvent(screen.getByTestId('exercise-still'), 'error');

    expect(sized()).toMatchObject({ width: withGif.width, height: withGif.height });
  });
});

describe('the tabs', () => {
  test('are Instructions, Muscles and Tips in a tab list, with Instructions selected first', async () => {
    await renderScreen();

    expect(screen.getByTestId('exercise-tabs')).toHaveProp('accessibilityRole', 'tablist');
    expect(screen.getAllByRole('tab').map((node) => node.props.accessibilityLabel)).toEqual(['Instructions', 'Muscles', 'Tips']);
    expect(tab('Instructions')).toBeSelected();
    expect(tab('Muscles')).not.toBeSelected();
    expect(tab('Tips')).not.toBeSelected();
    expect(screen.getByTestId('exercise-panel-instructions')).toBeOnTheScreen();
  });

  test('Instructions shows the numbered steps, in order', async () => {
    await renderScreen();

    const steps = screen.getByTestId('exercise-steps');
    expect(within(steps).getAllByText(/^\d$/).map((node) => node.props.children)).toEqual([1, 2, 3]);
    within(steps).getByText('Hold the weight at your chest.');
    within(steps).getByText('Sit down between your knees.');
    within(steps).getByText('Stand back up.');
    expect(screen.getByTestId('exercise-step-2')).toHaveProp('accessibilityLabel', 'Step 2. Sit down between your knees.');
  });

  test('Muscles shows the primary and secondary muscles, each group named', async () => {
    await renderScreen();

    await fireEvent.press(tab('Muscles'));

    expect(tab('Muscles')).toBeSelected();
    expect(tab('Instructions')).not.toBeSelected();
    expect(screen.queryByTestId('exercise-steps')).toBeNull();
    expect(within(screen.getByTestId('exercise-muscles-primary')).getByText('Quadriceps')).toBeOnTheScreen();
    const secondary = within(screen.getByTestId('exercise-muscles-secondary'));
    secondary.getByText('Glutes');
    secondary.getByText('Core');
    expect(screen.getByTestId('exercise-muscles-secondary')).toHaveProp('accessibilityLabel', 'Secondary muscles: Glutes, Core');
  });

  test('Tips shows what the plan and the catalog say, each line labelled with what it is', async () => {
    await renderScreen();

    await fireEvent.press(tab('Tips'));

    const tips = within(screen.getByTestId('exercise-tips'));
    tips.getByText('Plan note');
    tips.getByText('Keep your heels down.');
    tips.getByText('Rest between sets');
    tips.getByText('1 minute');
    tips.getByText('Weight');
    tips.getByText('12.5 kg');
    tips.getByText('About this exercise');
    tips.getByText('A beginner squatting exercise.');
  });

  test('goes back and forth between the tabs without losing any of them', async () => {
    await renderScreen();

    await fireEvent.press(tab('Tips'));
    await fireEvent.press(tab('Muscles'));
    await fireEvent.press(tab('Instructions'));

    expect(tab('Instructions')).toBeSelected();
    expect(screen.getByTestId('exercise-steps')).toBeOnTheScreen();
  });

  test('mark the selected tab with an emerald line under it, and only that one', async () => {
    await renderScreen();

    expect(screen.getAllByTestId('exercise-tabs-underline')).toHaveLength(1);
    expect(screen.getByTestId('exercise-tabs-underline')).toHaveStyle({ backgroundColor: dark.primary });
    expect(within(tab('Instructions')).getByTestId('exercise-tabs-underline')).toBeOnTheScreen();

    await fireEvent.press(tab('Tips'));
    expect(within(tab('Tips')).getByTestId('exercise-tabs-underline')).toBeOnTheScreen();
    expect(within(tab('Instructions')).queryByTestId('exercise-tabs-underline')).toBeNull();
  });

  describe('for an exercise with nothing but its plan', () => {
    test('Instructions says there are none and makes none up', async () => {
      await renderScreen(bare);

      expect(screen.getByTestId('exercise-unavailable')).toHaveTextContent('No instructions for this exercise yet.');
      expect(screen.queryByTestId('exercise-steps')).toBeNull();
    });

    test('Muscles says they are not available', async () => {
      await renderScreen(bare);

      await fireEvent.press(tab('Muscles'));

      expect(screen.getByTestId('exercise-unavailable')).toHaveTextContent("Muscle details aren't available for this exercise.");
    });

    test('Tips says there are none', async () => {
      await renderScreen(bare);

      await fireEvent.press(tab('Tips'));

      expect(screen.getByTestId('exercise-unavailable')).toHaveTextContent('No tips for this exercise yet.');
    });
  });

  test('Instructions shows the description when the exercise has no steps, and Tips does not repeat it', async () => {
    await renderScreen({ ...squat, instructions: [] });

    expect(screen.getByTestId('exercise-description')).toHaveTextContent('A beginner squatting exercise.');
    expect(screen.queryByTestId('exercise-steps')).toBeNull();

    await fireEvent.press(tab('Tips'));
    expect(screen.queryByText('About this exercise')).toBeNull();
    screen.getByText('Keep your heels down.');
  });

  test('Muscles lists only the muscle groups the exercise has', async () => {
    await renderScreen({ ...squat, muscles: [{ name: 'Quadriceps', role: 'PRIMARY' }] });

    await fireEvent.press(tab('Muscles'));

    expect(screen.getByTestId('exercise-muscles-primary')).toBeOnTheScreen();
    expect(screen.queryByTestId('exercise-muscles-secondary')).toBeNull();
  });
});

describe('the active set', () => {
  test('starts at set 1 of the plan\'s sets, at the reps the plan gives', async () => {
    await renderScreen();

    expect(screen.getByTestId('exercise-set-label')).toHaveTextContent('Set 1 of 3');
    expect(stepper()).toHaveAccessibilityValue({ text: '12 reps' });
    expect(screen.getByRole('button', { name: 'Complete Set' })).toBeOnTheScreen();
  });

  test('starts at the seconds the plan gives, for a held or timed set', async () => {
    await renderScreen({ ...squat, reps: null, durationSeconds: 45 });

    expect(stepper()).toHaveAccessibilityValue({ text: '45 seconds' });
    screen.getByRole('button', { name: 'Increase duration' });
    screen.getByRole('button', { name: 'Decrease duration' });
  });

  test('takes the numbers from the exercise that was opened, not from an example', async () => {
    await renderScreen(MOCK_TODAY_WORKOUT.exercises[1]);

    expect(screen.getByTestId('exercise-set-label')).toHaveTextContent('Set 1 of 2');
    expect(stepper()).toHaveAccessibilityValue({ text: '10 reps' });
  });

  describe('the reps', () => {
    test('go up and down by one with the + and - buttons', async () => {
      await renderScreen();

      await press('Increase reps');
      expect(stepper()).toHaveAccessibilityValue({ text: '13 reps' });
      await press('Decrease reps');
      await press('Decrease reps');
      expect(stepper()).toHaveAccessibilityValue({ text: '11 reps' });
    });

    test('stop at 1: the - button is dimmed and does nothing there', async () => {
      await renderScreen({ ...squat, reps: 3 });

      await press('Decrease reps');
      await press('Decrease reps');
      expect(stepper()).toHaveAccessibilityValue({ text: '1 rep' });

      expect(screen.getByRole('button', { name: 'Decrease reps' })).toBeDisabled();
      await press('Decrease reps');
      expect(stepper()).toHaveAccessibilityValue({ text: '1 rep' });
      expect(screen.getByRole('button', { name: 'Increase reps' })).toBeEnabled();
    });

    test('stop at 100: the + button is dimmed and does nothing there', async () => {
      await renderScreen({ ...squat, reps: 99 });

      await press('Increase reps');
      expect(stepper()).toHaveAccessibilityValue({ text: '100 reps' });

      expect(screen.getByRole('button', { name: 'Increase reps' })).toBeDisabled();
      await press('Increase reps');
      expect(stepper()).toHaveAccessibilityValue({ text: '100 reps' });
    });

    test('can be changed by a screen reader\'s swipe up and down as well', async () => {
      await renderScreen();

      await fireEvent(stepper(), 'accessibilityAction', { nativeEvent: { actionName: 'increment' } });
      expect(stepper()).toHaveAccessibilityValue({ text: '13 reps' });
      await fireEvent(stepper(), 'accessibilityAction', { nativeEvent: { actionName: 'decrement' } });
      await fireEvent(stepper(), 'accessibilityAction', { nativeEvent: { actionName: 'decrement' } });
      expect(stepper()).toHaveAccessibilityValue({ text: '11 reps' });
      expect(stepper()).toHaveProp('accessibilityRole', 'adjustable');
      expect(stepper()).toHaveProp('accessibilityLabel', 'Reps');
    });
  });

  describe('the duration', () => {
    const timed = { ...squat, reps: null, durationSeconds: 30 };

    test('goes up and down by five seconds', async () => {
      await renderScreen(timed);

      await press('Increase duration');
      expect(stepper()).toHaveAccessibilityValue({ text: '35 seconds' });
      await press('Decrease duration');
      await press('Decrease duration');
      expect(stepper()).toHaveAccessibilityValue({ text: '25 seconds' });
    });

    test('stops at 5 seconds at the bottom and at 10 minutes at the top', async () => {
      await renderScreen({ ...timed, durationSeconds: 10 });

      await press('Decrease duration');
      expect(stepper()).toHaveAccessibilityValue({ text: '5 seconds' });
      expect(screen.getByRole('button', { name: 'Decrease duration' })).toBeDisabled();
    });

    test('writes a long duration in minutes, and stops at ten of them', async () => {
      await renderScreen({ ...timed, durationSeconds: 595 });

      await press('Increase duration');

      expect(stepper()).toHaveAccessibilityValue({ text: '10 minutes' });
      expect(screen.getByRole('button', { name: 'Increase duration' })).toBeDisabled();
    });
  });

  test('a target beyond the limits is shown as the plan gives it, never as another number', async () => {
    await renderScreen({ ...squat, reps: 150 });

    expect(stepper()).toHaveAccessibilityValue({ text: '150 reps' });
    expect(screen.getByRole('button', { name: 'Increase reps' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Decrease reps' })).toBeEnabled();
  });

  test('shows no control and no number when the plan gives no target, and still lets the set be completed', async () => {
    const { onChange } = await renderScreen({ ...squat, reps: null, durationSeconds: null });

    expect(screen.queryByTestId('exercise-stepper')).toBeNull();
    expect(screen.getByTestId('exercise-no-target')).toHaveTextContent('This plan gives no reps or time for each set.');
    await press('Complete Set');
    expect(onChange).toHaveBeenCalledWith(1);
  });

  describe('Complete Set', () => {
    test('moves on to the next set, keeps the reps that were set, and says it was kept on this screen only', async () => {
      const { onChange } = await renderScreen();
      await press('Increase reps');

      await press('Complete Set');

      expect(onChange).toHaveBeenCalledWith(1);
      expect(screen.getByTestId('exercise-set-label')).toHaveTextContent('Set 2 of 3');
      expect(stepper()).toHaveAccessibilityValue({ text: '13 reps' });
      const notice = screen.getByTestId('toast');
      expect(notice).toHaveTextContent('Set 1 of 3 marked done on this screen only. Nothing was saved.');
      expect(notice).toHaveProp('accessibilityLiveRegion', 'polite');
    });

    test('draws a dot for each set: those done filled, the next one outlined', async () => {
      await renderScreen();
      const dot = (n: number) => screen.getByTestId(`exercise-set-dot-${n}`, HIDDEN);

      expect(dot(1)).toHaveStyle({ backgroundColor: 'transparent', borderColor: dark.primary });
      expect(dot(2)).toHaveStyle({ borderColor: dark.borderStrong });

      await press('Complete Set');

      expect(dot(1)).toHaveStyle({ backgroundColor: dark.primary });
      expect(dot(2)).toHaveStyle({ backgroundColor: 'transparent', borderColor: dark.primary });
      expect(dot(3)).toHaveStyle({ borderColor: dark.borderStrong });
      expect(screen.getByTestId('exercise-set-dots', HIDDEN)).toHaveProp('importantForAccessibility', 'no-hide-descendants');
    });

    test('picks up where the caller says the sets stand', async () => {
      await renderScreen(squat, { completed: 2 });

      expect(screen.getByTestId('exercise-set-label')).toHaveTextContent('Set 3 of 3');
    });

    test('says "All 3 sets done" after the last one, and does not complete the workout or leave the screen', async () => {
      const { onBack } = await renderScreen(squat, { completed: 2 });

      await press('Complete Set');

      expect(screen.getByTestId('exercise-set-label')).toHaveTextContent('All 3 sets done');
      expect(screen.queryByRole('button', { name: 'Complete Set' })).toBeNull();
      expect(screen.queryByTestId('exercise-stepper')).toBeNull();
      expect(onBack).not.toHaveBeenCalled();
      expect(screen.queryByText(/workout (is )?(complete|finished)/i)).toBeNull();
      expect(screen.getByTestId('toast')).toHaveTextContent('Set 3 of 3 marked done on this screen only. Nothing was saved.');
    });

    test('then offers "Back to workout", which goes back, and "Do the sets again", which starts over', async () => {
      const { onBack, onChange } = await renderScreen(squat, { completed: 3 });

      await press('Back to workout');
      expect(onBack).toHaveBeenCalledTimes(1);

      await fireEvent.press(screen.getByRole('link', { name: 'Do the sets again' }));

      expect(onChange).toHaveBeenLastCalledWith(0);
      expect(screen.getByTestId('exercise-set-label')).toHaveTextContent('Set 1 of 3');
      expect(screen.getByRole('button', { name: 'Complete Set' })).toBeOnTheScreen();
    });

    test('a count beyond the plan\'s sets is shown as all done, not as a set 5 of 3', async () => {
      await renderScreen(squat, { completed: 7 });

      expect(screen.getByTestId('exercise-set-label')).toHaveTextContent('All 3 sets done');
    });

    test('never finishes when the plan does not say how many sets there are', async () => {
      await renderScreen({ ...squat, sets: 0 });

      expect(screen.getByTestId('exercise-set-label')).toHaveTextContent('Set 1');
      expect(screen.queryByTestId('exercise-set-dots', HIDDEN)).toBeNull();
      await press('Complete Set');
      await press('Complete Set');
      expect(screen.getByTestId('exercise-set-label')).toHaveTextContent('Set 3');
      expect(screen.getByRole('button', { name: 'Complete Set' })).toBeOnTheScreen();
    });

    test('says a single set is "1 set", not "1 sets"', async () => {
      await renderScreen({ ...squat, sets: 1 }, { completed: 1 });

      expect(screen.getByTestId('exercise-set-label')).toHaveTextContent('All 1 set done');
    });

    test('tells a screen reader that it does not save', async () => {
      await renderScreen();

      expect(screen.getByRole('button', { name: 'Complete Set' })).toHaveProp(
        'accessibilityHint',
        'Marks this set done on this screen only. Nothing is saved yet.',
      );
    });
  });
});

describe('the layout', () => {
  test('keeps the set controls below the scrolling page, so Complete Set is always in reach', async () => {
    await renderScreen();

    const footer = within(screen.getByTestId('exercise-details-footer'));
    footer.getByRole('button', { name: 'Complete Set' });
    footer.getByRole('button', { name: 'Increase reps' });
    footer.getByTestId('exercise-set-label');
    const page = within(screen.getByTestId('exercise-details-scroll'));
    expect(page.queryByRole('button', { name: 'Complete Set' })).toBeNull();
    // the title, the animation, the tabs and their content are what scrolls
    page.getByRole('header', { name: 'Goblet Squat' });
    page.getByTestId('exercise-animation');
    page.getByTestId('exercise-tabs');
  });

  test('keeps the Back arrow above the scrolling page, in reach at any scroll', async () => {
    await renderScreen();

    expect(within(screen.getByTestId('exercise-details-scroll')).queryByRole('button', { name: 'Back' })).toBeNull();
    expect(within(screen.getByTestId('exercise-details-body')).getByRole('button', { name: 'Back' })).toBeOnTheScreen();
  });

  test('fades the page into the background at both ends of the scrolling area, so text is never cut hard', async () => {
    await renderScreen();

    const top = screen.getByTestId('exercise-details-top-fade');
    const bottom = screen.getByTestId('exercise-details-bottom-fade');
    expect(top.props.style.backgroundImage).toContain('linear-gradient(to bottom, rgba(11, 13, 14, 1) 0%');
    expect(bottom.props.style.backgroundImage).toContain('linear-gradient(to top, rgba(11, 13, 14, 1) 0%');
    expect(top).toHaveProp('pointerEvents', 'none');
    expect(bottom).toHaveProp('pointerEvents', 'none');
  });

  test('puts the notice above the set controls, never over them', async () => {
    await renderScreen();
    await press('Complete Set');

    expect(within(screen.getByTestId('exercise-details-footer')).queryByTestId('toast')).toBeNull();
    expect(screen.getByTestId('toast-layer')).toHaveProp('pointerEvents', 'none');
  });

  describe('safe areas', () => {
    const metrics = {
      frame: { x: 0, y: 0, width: 360, height: 800 },
      insets: { top: 40, bottom: 20, left: 8, right: 4 },
    };
    const renderWithInsets = () =>
      render(
        <SafeAreaProvider initialMetrics={metrics}>
          <ThemeProvider>
            <ExerciseDetailsScreen exercise={squat} onBack={jest.fn()} completedSets={0} onCompletedSetsChange={jest.fn()} />
          </ThemeProvider>
        </SafeAreaProvider>,
      );

    test('keeps the controls clear of the system bar and of a cut-out beside them', async () => {
      await renderWithInsets();

      expect(screen.getByTestId('exercise-details-footer')).toHaveStyle({
        paddingBottom: 20 + 12,
        paddingLeft: 8 + 20,
        paddingRight: 4 + 20,
      });
    });

    test('keeps the Back arrow and the title below the status bar', async () => {
      await renderWithInsets();

      expect(screen.getByTestId('exercise-details-body')).toHaveStyle({ paddingTop: 40 });
    });

    test('draws the animation inside the side insets', async () => {
      await renderWithInsets();

      expect(screen.getByTestId('exercise-animation')).toHaveStyle({ width: Dimensions.get('window').width - (8 + 20) - (4 + 20) });
    });
  });
});

describe('the themes', () => {
  test('follows the dark theme', async () => {
    await renderScreen();

    expect(screen.getByTestId('exercise-details')).toHaveStyle({ backgroundColor: dark.background });
    expect(screen.getByRole('header', { name: 'Goblet Squat' })).toHaveStyle({ color: dark.textPrimary });
    expect(textColor(within(tab('Instructions')).getByText('Instructions'))).toBe(dark.textPrimary);
    expect(textColor(within(tab('Muscles')).getByText('Muscles'))).toBe(dark.textMuted);
    expect(screen.getByTestId('exercise-details-footer')).toHaveStyle({ backgroundColor: dark.background });
  });

  test('follows the light theme', async () => {
    await renderScreen(squat, { scheme: 'light' });

    expect(screen.getByTestId('exercise-details')).toHaveStyle({ backgroundColor: light.background });
    expect(screen.getByRole('header', { name: 'Goblet Squat' })).toHaveStyle({ color: light.textPrimary });
    expect(textColor(within(tab('Instructions')).getByText('Instructions'))).toBe(light.textPrimary);
    expect(textColor(within(tab('Muscles')).getByText('Muscles'))).toBe(light.textMuted);
    expect(screen.getByTestId('exercise-details-footer')).toHaveStyle({ backgroundColor: light.background });
    expect(screen.getByRole('button', { name: 'Complete Set' })).toHaveStyle({ backgroundColor: light.primary });
  });

  test('the muscle groups wear emerald on both themes', async () => {
    await renderScreen(squat, { scheme: 'light' });
    await fireEvent.press(tab('Muscles'));

    const primary = within(screen.getByTestId('exercise-muscles-primary')).getByText('Quadriceps');
    expect(textColor(primary)).toBe(light.accent);
    expect(primary.parent).toHaveStyle({ backgroundColor: light.primarySubtle, borderColor: light.primary });
  });
});
