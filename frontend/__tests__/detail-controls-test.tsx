import { useState } from 'react';
import { fireEvent, screen, within } from '@testing-library/react-native';
import { StyleSheet, type TextStyle } from 'react-native';

import { NumberStepper, UnderlineTabs } from '../src/components';
import { themes } from '../src/theme';
import { renderWithTheme } from '../test-utils/renderWithTheme';

const dark = themes.dark.colors;
const light = themes.light.colors;
const HIDDEN = { includeHiddenElements: true };
const textColor = (node: { props: { style?: unknown } }) => (StyleSheet.flatten(node.props.style as TextStyle) as TextStyle).color;

type Id = 'a' | 'b' | 'c';
const TABS: { id: Id; label: string }[] = [
  { id: 'a', label: 'First' },
  { id: 'b', label: 'Second' },
  { id: 'c', label: 'Third' },
];

function Tabs({ onSelect = jest.fn() }: { onSelect?: (id: Id) => void }) {
  const [selected, setSelected] = useState<Id>('a');
  return (
    <UnderlineTabs
      tabs={TABS}
      selected={selected}
      onSelect={(id) => {
        setSelected(id);
        onSelect(id);
      }}
      accessibilityLabel="Sections"
      testID="tabs"
    />
  );
}

describe('<UnderlineTabs />', () => {
  test('is a tab list with one tab for each entry, the first selected', async () => {
    await renderWithTheme(<Tabs />);

    expect(screen.getByTestId('tabs')).toHaveProp('accessibilityRole', 'tablist');
    expect(screen.getByTestId('tabs')).toHaveProp('accessibilityLabel', 'Sections');
    expect(screen.getAllByRole('tab').map((node) => node.props.accessibilityLabel)).toEqual(['First', 'Second', 'Third']);
    expect(screen.getByRole('tab', { name: 'First' })).toBeSelected();
    expect(screen.getByRole('tab', { name: 'Second' })).not.toBeSelected();
  });

  test('moves the selection to the tab that is pressed, and says which one', async () => {
    const onSelect = jest.fn();
    await renderWithTheme(<Tabs onSelect={onSelect} />);

    await fireEvent.press(screen.getByRole('tab', { name: 'Third' }));

    expect(onSelect).toHaveBeenCalledWith('c');
    expect(screen.getByRole('tab', { name: 'Third' })).toBeSelected();
    expect(screen.getByRole('tab', { name: 'First' })).not.toBeSelected();
  });

  test.each([
    ['dark', dark],
    ['light', light],
  ] as const)('shows the selected tab in the primary text color and the rest muted, in the %s theme', async (scheme, colors) => {
    await renderWithTheme(<Tabs />, scheme);

    expect(textColor(within(screen.getByRole('tab', { name: 'First' })).getByText('First'))).toBe(colors.textPrimary);
    expect(textColor(within(screen.getByRole('tab', { name: 'Second' })).getByText('Second'))).toBe(colors.textMuted);
    expect(screen.getByTestId('tabs-underline')).toHaveStyle({ backgroundColor: colors.primary });
  });

  test('shrinks a label that does not fit at a large font size instead of cutting it', async () => {
    await renderWithTheme(<Tabs />);

    for (const label of ['First', 'Second', 'Third']) {
      const text = within(screen.getByRole('tab', { name: label })).getByText(label);
      expect(text).toHaveProp('adjustsFontSizeToFit', true);
      expect(text).toHaveProp('numberOfLines', 1);
      expect(text.props.minimumFontScale).toBeLessThan(1);
    }
  });

  test('is as tall as a button, so each tab is easy to hit', async () => {
    await renderWithTheme(<Tabs />);

    for (const node of screen.getAllByRole('tab')) {
      expect(node).toHaveStyle({ minHeight: 48 });
    }
  });
});

function Stepper({ min = 1, max = 3, start = 2 }: { min?: number; max?: number; start?: number }) {
  const [value, setValue] = useState(start);
  return (
    <NumberStepper
      testID="stepper"
      label="Count"
      valueLabel={`${value} things`}
      canDecrease={value > min}
      canIncrease={value < max}
      decreaseLabel="Fewer"
      increaseLabel="More"
      onDecrease={() => setValue(value - 1)}
      onIncrease={() => setValue(value + 1)}
    />
  );
}

describe('<NumberStepper />', () => {
  test('shows the value between a - button and a + button', async () => {
    await renderWithTheme(<Stepper />);

    within(screen.getByTestId('stepper')).getByText('2 things');
    screen.getByRole('button', { name: 'Fewer' });
    screen.getByRole('button', { name: 'More' });
    expect(screen.getByTestId('icon-minus', HIDDEN)).toBeOnTheScreen();
    expect(screen.getByTestId('icon-plus', HIDDEN)).toBeOnTheScreen();
  });

  test('changes the value with each button, until the screen says a limit has been reached', async () => {
    await renderWithTheme(<Stepper />);

    await fireEvent.press(screen.getByRole('button', { name: 'More' }));
    screen.getByText('3 things');
    expect(screen.getByRole('button', { name: 'More' })).toBeDisabled();

    await fireEvent.press(screen.getByRole('button', { name: 'More' }));
    screen.getByText('3 things');

    await fireEvent.press(screen.getByRole('button', { name: 'Fewer' }));
    await fireEvent.press(screen.getByRole('button', { name: 'Fewer' }));
    screen.getByText('1 things');
    expect(screen.getByRole('button', { name: 'Fewer' })).toBeDisabled();
  });

  test("has buttons that are at least 48 dp square, a thumb's size", async () => {
    await renderWithTheme(<Stepper />);

    for (const name of ['Fewer', 'More']) {
      expect(screen.getByRole('button', { name })).toHaveStyle({ width: 56, height: 56 });
    }
  });

  test('dims a button at its limit and changes the color of one that is pressed, instead of fading it', async () => {
    await renderWithTheme(<Stepper start={1} />);
    const button = (name: string) => screen.getByRole('button', { name });

    expect(button('Fewer')).toHaveStyle({ backgroundColor: dark.disabledBackground });
    expect(button('More')).toHaveStyle({ backgroundColor: dark.surfaceMuted });

    // a finger down on it (the press is not over until release)
    await fireEvent(button('More'), 'responderGrant', { nativeEvent: { touches: [], changedTouches: [], timestamp: 0 }, persist: () => undefined });

    expect(button('More')).toHaveStyle({ backgroundColor: dark.primarySubtle });
    expect(StyleSheet.flatten(button('More').props.style)).not.toHaveProperty('opacity');
  });

  test('is one adjustable element for a screen reader, with the value as its value', async () => {
    await renderWithTheme(<Stepper />);

    const value = screen.getByTestId('stepper-value');
    expect(value).toHaveProp('accessibilityRole', 'adjustable');
    expect(value).toHaveProp('accessibilityLabel', 'Count');
    expect(value).toHaveAccessibilityValue({ text: '2 things' });

    await fireEvent(value, 'accessibilityAction', { nativeEvent: { actionName: 'increment' } });
    expect(screen.getByTestId('stepper-value')).toHaveAccessibilityValue({ text: '3 things' });
    // at the limit the swipe changes nothing
    await fireEvent(value, 'accessibilityAction', { nativeEvent: { actionName: 'increment' } });
    expect(screen.getByTestId('stepper-value')).toHaveAccessibilityValue({ text: '3 things' });
  });
});
