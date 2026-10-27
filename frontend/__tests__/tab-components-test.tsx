import { act, fireEvent, render, screen, within } from '@testing-library/react-native';
import { StatusBar } from 'expo-status-bar';
import { StyleSheet, View, type TextStyle } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import {
  ActionTile,
  AppIcon,
  AppText,
  FadeEdge,
  ListRow,
  ProgressBar,
  SectionHeader,
  SummaryTile,
  TabScreen,
  Toast,
  useToast,
} from '../src/components';
import { fadeGradient, fadeStops } from '../src/components/FadeEdge';
import { ThemeProvider, themes } from '../src/theme';
import { renderWithTheme } from '../test-utils/renderWithTheme';

// The status bar draws nothing: replace it to see which icon style the screen asks for.
jest.mock('expo-status-bar', () => ({ StatusBar: jest.fn(() => null) }));

const dark = themes.dark.colors;
const light = themes.light.colors;
const HIDDEN = { includeHiddenElements: true };
const PHOTO = require('../assets/images/welcome-hero.png');

describe('<ProgressBar />', () => {
  test('fills the share it is given of a track', async () => {
    await renderWithTheme(<ProgressBar testID="bar" value={0.6} />);

    expect(screen.getByTestId('bar', HIDDEN)).toHaveStyle({ backgroundColor: dark.border });
    expect(screen.getByTestId('bar-fill', HIDDEN)).toHaveStyle({ width: '60%', backgroundColor: dark.primary });
  });

  test('takes its color from a theme token', async () => {
    await renderWithTheme(<ProgressBar testID="bar" value={0.5} color="progress" />, 'light');

    expect(screen.getByTestId('bar-fill', HIDDEN)).toHaveStyle({ backgroundColor: light.progress });
    expect(screen.getByTestId('bar', HIDDEN)).toHaveStyle({ backgroundColor: light.border });
  });

  test.each([
    [-1, '0%'],
    [0, '0%'],
    [1, '100%'],
    [3, '100%'],
  ])('a value of %d is held to %s', async (value, width) => {
    await renderWithTheme(<ProgressBar testID="bar" value={value} />);

    expect(screen.getByTestId('bar-fill', HIDDEN)).toHaveStyle({ width });
  });

  test('is decoration: hidden from screen readers, which hear the words beside it', async () => {
    await renderWithTheme(<ProgressBar testID="bar" value={0.6} />);

    expect(screen.queryByTestId('bar')).toBeNull();
    expect(screen.getByTestId('bar', HIDDEN)).toHaveProp('importantForAccessibility', 'no-hide-descendants');
  });
});

describe('<SummaryTile />', () => {
  const props = {
    icon: 'fire' as const,
    iconColor: 'warm' as const,
    tint: 'primary' as const,
    label: 'Nutrition',
    value: '1,850 kcal',
    caption: "Today's target",
    progress: 0.6,
    progressLabel: '60%',
  };

  test('is one button, read as one sentence, that calls its handler', async () => {
    const onPress = jest.fn();
    await renderWithTheme(<SummaryTile {...props} onPress={onPress} />);

    const tile = screen.getByRole('button');
    expect(tile).toHaveAccessibleName("Nutrition: 1,850 kcal, Today's target, 60%");
    await fireEvent.press(tile);
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  test('shows the label, the value, the caption and how far along it is', async () => {
    await renderWithTheme(<SummaryTile {...props} onPress={jest.fn()} />);

    for (const text of ['Nutrition', '1,850 kcal', "Today's target", '60%']) screen.getByText(text);
    expect(screen.getByTestId('icon-fire', HIDDEN)).toBeOnTheScreen();
    expect(screen.getByTestId('icon-chevron-right', HIDDEN)).toBeOnTheScreen();
  });

  test('is washed in its own tint and keeps the value on one line', async () => {
    await renderWithTheme(<SummaryTile {...props} tint="progress" iconColor="progress" onPress={jest.fn()} />);

    expect(screen.getByRole('button')).toHaveStyle({
      borderColor: `${dark.progress}40`,
      backgroundColor: `${dark.progress}14`,
    });
    expect(screen.getByText('1,850 kcal')).toHaveProp('numberOfLines', 1);
    expect(screen.getByText('1,850 kcal')).toHaveProp('adjustsFontSizeToFit', true);
  });
});

describe('<ActionTile />', () => {
  test('is one button named by its title and description, and calls its handler', async () => {
    const onPress = jest.fn();
    await renderWithTheme(
      <ActionTile icon="silverware-fork-knife" title="Log Meal" description="Track your nutrition" onPress={onPress} />,
    );

    const tile = screen.getByRole('button');
    expect(tile).toHaveAccessibleName('Log Meal. Track your nutrition');
    expect(tile).toHaveStyle({ backgroundColor: dark.surface, borderColor: dark.border });
    await fireEvent.press(tile);
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  test('has an icon and no chevron: the words need the room', async () => {
    await renderWithTheme(<ActionTile icon="account-outline" title="A" description="B" onPress={jest.fn()} />);

    expect(screen.getByTestId('icon-account-outline', HIDDEN)).toBeOnTheScreen();
    expect(screen.queryByTestId('icon-chevron-right', HIDDEN)).toBeNull();
  });

  test('is at least as tall as a touch target and lets the description take two lines', async () => {
    await renderWithTheme(<ActionTile icon="account-outline" title="A" description="B" onPress={jest.fn()} />);

    expect(screen.getByRole('button')).toHaveStyle({ minHeight: 60 });
    expect(screen.getByText('B')).toHaveProp('numberOfLines', 2);
  });
});

describe('<ListRow />', () => {
  test('is one button named by its title and the line under it, with a chevron', async () => {
    const onPress = jest.fn();
    await renderWithTheme(
      <ListRow testID="row" title="Upper Body Strength" subtitle="Completed • Yesterday" thumbnail={PHOTO} onPress={onPress} />,
    );

    const row = screen.getByRole('button');
    expect(row).toHaveAccessibleName('Upper Body Strength. Completed • Yesterday');
    expect(screen.getByTestId('icon-chevron-right', HIDDEN)).toBeOnTheScreen();
    await fireEvent.press(row);
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  test('has a thumbnail that is only a picture: sized explicitly, with no name', async () => {
    await renderWithTheme(<ListRow testID="row" title="T" subtitle="S" thumbnail={PHOTO} onPress={jest.fn()} />);

    const thumbnail = screen.getByTestId('row-thumbnail', HIDDEN);
    expect(thumbnail).toHaveProp('source', PHOTO);
    expect(thumbnail).toHaveProp('accessible', false);
    expect(thumbnail).not.toHaveProp('accessibilityLabel');
    expect(thumbnail).toHaveStyle({ width: 56, height: 40 });
  });

  test('can be shown without a thumbnail', async () => {
    await renderWithTheme(<ListRow testID="row" title="T" subtitle="S" onPress={jest.fn()} />);

    expect(screen.queryByTestId('row-thumbnail', HIDDEN)).toBeNull();
  });
});

describe('<SectionHeader />', () => {
  test('has its title as a heading and no link when there is no action', async () => {
    await renderWithTheme(<SectionHeader title="Quick Actions" />);

    expect(screen.getByRole('header')).toHaveTextContent('Quick Actions');
    expect(screen.queryByRole('link')).toBeNull();
  });

  test('has a link that says where it leads, and calls its handler', async () => {
    const onAction = jest.fn();
    await renderWithTheme(
      <SectionHeader
        title="Recent Activity"
        actionLabel="See all"
        actionAccessibilityLabel="See all recent activity"
        onAction={onAction}
      />,
    );

    const link = screen.getByRole('link', { name: 'See all recent activity' });
    expect(within(link).getByText('See all')).toHaveStyle({ color: dark.accent });
    await fireEvent.press(link);
    expect(onAction).toHaveBeenCalledTimes(1);
  });

  test('names the link by its visible words when nothing else is given', async () => {
    await renderWithTheme(<SectionHeader title="T" actionLabel="See all" onAction={jest.fn()} />);

    expect(screen.getByRole('link', { name: 'See all' })).toBeOnTheScreen();
  });
});

describe('<Toast /> and useToast', () => {
  afterEach(() => jest.useRealTimers());

  function Host({ duration }: { duration?: number }) {
    const { message, show } = useToast(duration);
    return (
      <View style={{ flex: 1 }}>
        <AppText onPress={() => show('First')} accessibilityRole="button" accessibilityLabel="show first">
          show first
        </AppText>
        <AppText onPress={() => show('Second')} accessibilityRole="button" accessibilityLabel="show second">
          show second
        </AppText>
        <Toast message={message} />
      </View>
    );
  }

  test('shows nothing without a message', async () => {
    await renderWithTheme(<Toast message={null} />);

    expect(screen.queryByTestId('toast')).toBeNull();
  });

  test('shows its message in a polite live region and never takes a tap', async () => {
    await renderWithTheme(<Toast message="Hello" />);

    const toast = screen.getByTestId('toast');
    expect(toast).toHaveProp('accessibilityLiveRegion', 'polite');
    expect(within(toast).getByText('Hello')).toBeOnTheScreen();
    expect(screen.getByTestId('toast-layer')).toHaveProp('pointerEvents', 'none');
    expect(screen.getByTestId('toast-layer')).toHaveStyle({ position: 'absolute', bottom: 16 });
  });

  test('appears when shown and goes by itself after three seconds', async () => {
    jest.useFakeTimers();
    await renderWithTheme(<Host />);

    await fireEvent.press(screen.getByRole('button', { name: 'show first' }));
    screen.getByText('First');

    await act(async () => {
      jest.advanceTimersByTime(2900);
    });
    screen.getByText('First');
    await act(async () => {
      jest.advanceTimersByTime(200);
    });
    expect(screen.queryByText('First')).toBeNull();
  });

  test('a second message replaces the first and restarts the clock', async () => {
    jest.useFakeTimers();
    await renderWithTheme(<Host duration={1000} />);

    await fireEvent.press(screen.getByRole('button', { name: 'show first' }));
    await act(async () => {
      jest.advanceTimersByTime(800);
    });
    await fireEvent.press(screen.getByRole('button', { name: 'show second' }));
    expect(screen.queryByText('First')).toBeNull();
    screen.getByText('Second');

    await act(async () => {
      jest.advanceTimersByTime(800);
    });
    // 1600 ms after the first message, but only 800 ms after the second
    screen.getByText('Second');
    await act(async () => {
      jest.advanceTimersByTime(300);
    });
    expect(screen.queryByText('Second')).toBeNull();
  });

  test('clears its own timer when the screen goes away', async () => {
    const set = jest.spyOn(globalThis, 'setTimeout');
    const clear = jest.spyOn(globalThis, 'clearTimeout');
    const view = await renderWithTheme(<Host />);
    await fireEvent.press(screen.getByRole('button', { name: 'show first' }));
    const created = set.mock.calls.findIndex((call: unknown[]) => call[1] === 3000);
    expect(created).toBeGreaterThanOrEqual(0);
    const timer = set.mock.results[created].value;

    await view.unmount();

    expect(clear).toHaveBeenCalledWith(timer);
    jest.restoreAllMocks();
  });
});

describe('<FadeEdge />', () => {
  test('fades from solid at the edge to clear at the end, and never grows more solid on the way', () => {
    const stops = fadeStops(0);

    expect(stops[0]).toEqual({ position: 0, opacity: 1 });
    expect(stops[stops.length - 1]).toEqual({ position: 1, opacity: 0 });
    stops.forEach((stop, index) => {
      if (index > 0) {
        expect(stop.position).toBeGreaterThan(stops[index - 1].position);
        expect(stop.opacity).toBeLessThanOrEqual(stops[index - 1].opacity);
      }
    });
  });

  test('holds solid through the share it is told to, then eases out', () => {
    const stops = fadeStops(0.5);

    // solid from the edge to the middle, and clear at the end
    expect(stops[0]).toEqual({ position: 0, opacity: 1 });
    expect(stops[1]).toEqual({ position: 0.5, opacity: 1 });
    expect(stops[2].opacity).toBeLessThan(1);
    expect(stops[stops.length - 1]).toEqual({ position: 1, opacity: 0 });
  });

  test('eases with no kink: the curve is smoothstep, so it is half solid half way along', () => {
    const stops = fadeStops(0, 16);

    expect(stops.find((stop) => stop.position === 0.5)?.opacity).toBeCloseTo(0.5, 9);
    // the steepest step between stops stays small, so a bright picture shows no bands
    const steepest = Math.max(...stops.slice(1).map((stop, index) => stops[index].opacity - stop.opacity));
    expect(steepest).toBeLessThan(0.1);
  });

  test('a hold that would leave no room to fade still ends clear', () => {
    const stops = fadeStops(1);

    expect(stops[stops.length - 1]).toEqual({ position: 1, opacity: 0 });
  });

  test('the gradient is the same color at every stop, only its opacity changes', () => {
    const gradient = fadeGradient('#0F2A22', 0.12);

    expect(gradient.startsWith('linear-gradient(to right, rgba(15, 42, 34, 1) 0%, rgba(15, 42, 34, 1) 12%')).toBe(true);
    expect(gradient.endsWith('rgba(15, 42, 34, 0) 100%)')).toBe(true);
    // nothing but that one color: no black or grey is passed through
    expect(gradient.match(/rgba\((\d+), (\d+), (\d+),/g)?.every((color) => color.startsWith('rgba(15, 42, 34,'))).toBe(true);
  });

  test('reads a short hex color too, and passes any other color to the platform as it is', () => {
    expect(fadeGradient('#fff', 0)).toContain('rgba(255, 255, 255, 1) 0%');
    expect(fadeGradient('rebeccapurple', 0)).toBe('linear-gradient(to right, rebeccapurple, transparent)');
  });

  test('can run in any of the four directions, solid at the start of it: a vertical fade for the foot of a photograph', () => {
    expect(fadeGradient('#0F2A22', 0, 'to top')).toContain('linear-gradient(to top, rgba(15, 42, 34, 1) 0%');
    expect(fadeGradient('#0F2A22', 0, 'to bottom')).toContain('linear-gradient(to bottom, rgba(15, 42, 34, 1) 0%');
    expect(fadeGradient('#0F2A22', 0, 'to left')).toContain('linear-gradient(to left, rgba(15, 42, 34, 1) 0%');
    // a color the app does not parse keeps the direction too
    expect(fadeGradient('rebeccapurple', 0, 'to top')).toBe('linear-gradient(to top, rebeccapurple, transparent)');
  });

  test('can be held back: a strength below 1 scales every stop, so it never hides what is under it entirely', () => {
    const gradient = fadeGradient('#0F2A22', 0.1, 'to right', 0.4);

    expect(gradient).toContain('rgba(15, 42, 34, 0.4) 0%, rgba(15, 42, 34, 0.4) 10%');
    expect(gradient.endsWith('rgba(15, 42, 34, 0) 100%)')).toBe(true);
    const opacities = [...gradient.matchAll(/rgba\(15, 42, 34, ([\d.]+)\)/g)].map((match) => Number(match[1]));
    expect(Math.max(...opacities)).toBe(0.4);
    // the same curve as the full-strength one, scaled
    const full = [...fadeGradient('#0F2A22', 0.1).matchAll(/rgba\(15, 42, 34, ([\d.]+)\)/g)].map((match) => Number(match[1]));
    opacities.forEach((opacity, index) => expect(opacity).toBeCloseTo(full[index] * 0.4, 3));
  });

  test('is one view with that gradient, from the left edge to the width it is given, not a stack of strips', async () => {
    await renderWithTheme(<FadeEdge testID="fade" color="#112233" width="60%" hold={0.4} />);

    const fade = screen.getByTestId('fade', HIDDEN);
    expect(fade).toHaveStyle({
      position: 'absolute',
      left: 0,
      top: 0,
      bottom: 0,
      width: '60%',
      backgroundImage: fadeGradient('#112233', 0.4),
    });
    expect(fade).toHaveProp('pointerEvents', 'none');
    expect(fade).toHaveProp('importantForAccessibility', 'no-hide-descendants');
    expect(fade.children).toHaveLength(0);
  });
});

describe('<AppIcon /> tint', () => {
  const glyphColor = (name: string) =>
    StyleSheet.flatten((screen.getByTestId(`icon-${name}`, HIDDEN).children[0] as unknown as { props: { style: TextStyle } }).props.style)?.color;

  test('wears a color that is not a theme token when it is given one, over the token', async () => {
    await renderWithTheme(
      <>
        <AppIcon name="target" color="textMuted" tint="#3FC2AE" />
        <AppIcon name="home" color="textMuted" />
        <AppIcon name="clock-outline" />
      </>,
    );

    expect(glyphColor('target')).toBe('#3FC2AE');
    expect(glyphColor('home')).toBe(themes.dark.colors.textMuted);
    expect(glyphColor('clock-outline')).toBe(themes.dark.colors.accent);
  });
});

describe('<AppIcon /> rotate', () => {
  test('turns a glyph the set draws at an angle, and leaves other icons alone', async () => {
    await renderWithTheme(
      <>
        <AppIcon name="dumbbell" rotate={-45} />
        <AppIcon name="home" />
      </>,
    );

    expect(screen.getByTestId('icon-dumbbell', HIDDEN)).toHaveStyle({ transform: [{ rotate: '-45deg' }] });
    expect(screen.getByTestId('icon-home', HIDDEN).props.style).toBeUndefined();
  });
});

describe('<TabScreen />', () => {
  const metrics = {
    frame: { x: 0, y: 0, width: 360, height: 800 },
    insets: { top: 40, bottom: 20, left: 8, right: 4 },
  };

  test('keeps clear of the status bar and sides, and leaves the bottom inset to the tab bar', async () => {
    await render(
      <SafeAreaProvider initialMetrics={metrics}>
        <ThemeProvider>
          <TabScreen testID="page">
            <AppText>Content</AppText>
          </TabScreen>
        </ThemeProvider>
      </SafeAreaProvider>,
    );

    // the top inset is on a view around the scroll, not inside it: content slides away under the status
    // bar's lower edge and never passes behind its clock and icons. The page itself is not padded, so
    // the photo behind it reaches the top and the bottom.
    expect(screen.getByTestId('page')).toHaveStyle({ flex: 1, backgroundColor: dark.background });
    expect(screen.getByTestId('page')).not.toHaveStyle({ paddingTop: 40 });
    expect(screen.getByTestId('tab-inset')).toHaveStyle({ flex: 1, paddingTop: 40 });
    expect(screen.getByTestId('tab-scroll')).toHaveProp('contentContainerStyle', {
      paddingTop: 16,
      paddingBottom: 24,
      paddingLeft: 8 + 16,
      paddingRight: 4 + 16,
    });
    screen.getByText('Content');
  });

  test('scrolls without a scroll bar', async () => {
    await renderWithTheme(
      <TabScreen>
        <View />
      </TabScreen>,
    );

    expect(screen.getByTestId('tab-scroll')).toHaveProp('showsVerticalScrollIndicator', false);
  });

  test('has a solid themed background and no photograph in either theme', async () => {
    for (const scheme of ['dark', 'light'] as const) {
      const view = await renderWithTheme(
        <TabScreen testID="page">
          <View />
        </TabScreen>,
        scheme,
      );

      expect(screen.getByTestId('page')).toHaveStyle({ backgroundColor: themes[scheme].colors.background });
      expect(screen.queryByTestId('tab-photo', HIDDEN)).toBeNull();
      expect(screen.queryByTestId('tab-photo-scrim', HIDDEN)).toBeNull();
      // nothing under the page's own background but the scroll: no image at all
      expect(screen.getByTestId('page').children).toHaveLength(1);
      await view.unmount();
    }
  });

  test('asks for light status bar icons on dark and dark icons on light', async () => {
    const view = await renderWithTheme(
      <TabScreen>
        <View />
      </TabScreen>,
    );
    expect(StatusBar).toHaveBeenLastCalledWith(expect.objectContaining({ style: 'light' }), undefined);
    await view.unmount();

    await renderWithTheme(
      <TabScreen>
        <View />
      </TabScreen>,
      'light',
    );
    expect(StatusBar).toHaveBeenLastCalledWith(expect.objectContaining({ style: 'dark' }), undefined);
  });
});
