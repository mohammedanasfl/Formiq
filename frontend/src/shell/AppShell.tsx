import { useCallback, useEffect, useState } from 'react';
import { AppState, BackHandler, View } from 'react-native';

import type { SavedEquipment, Session } from '../api';
import { ConnectedCoachScreen } from '../coach/ConnectedCoachScreen';
import { DEFAULT_COACH_MODE, type CoachMode } from '../coach/mode';
import { DiscoverScreen } from '../discover/DiscoverScreen';
import { HomeScreen } from '../home/HomeScreen';
import { useTodayWorkout } from '../home/useTodayWorkout';
import { CoachCardPreviewScreen } from '../mock/CoachCardPreviewScreen';
import { MOCK_HOME } from '../mock/homeMock';
import { MockCoachScreen } from '../mock/MockCoachScreen';
import { EquipmentEditScreen } from '../profile/EquipmentEditScreen';
import { ProfileScreen } from '../profile/ProfileScreen';
import { useSavedEquipment } from '../profile/useSavedEquipment';
import { useTheme } from '../theme';
import { ExerciseDetailsScreen } from '../workouts/ExerciseDetailsScreen';
import { workoutDetailsFromPlan } from '../workouts/planMapping';
import { WorkoutDetailsScreen } from '../workouts/WorkoutDetailsScreen';
import { BottomTabBar } from './BottomTabBar';
import type { CoachContext, Route } from './routes';
import { SectionPlaceholderScreen } from './SectionPlaceholderScreen';
import { TabPlaceholderScreen } from './TabPlaceholderScreen';
import { isTab, type Destination, type TabId } from './tabs';

type AppShellProps = {
  // who is signed in: Home reads their workout state from the backend with it
  session: Session;
  onSignOut: () => void;
  // which coach the AI Coach tab talks to: the backend's (the default) or the made-up one of mock mode
  coachMode?: CoachMode;
};

// Whether the app is in the foreground. It is when the shell opens (the person has just signed in or
// continued), so it starts true and follows the system's changes: coming back from another app is a focus.
function useAppIsActive(): boolean {
  const [active, setActive] = useState(true);
  useEffect(() => {
    const subscription = AppState.addEventListener('change', (next) => setActive(next === 'active'));
    return () => subscription.remove();
  }, []);
  return active;
}

// The signed-in app: one screen at a time above the bottom tab bar. There is no navigation library: which
// tab is showing is this component's own state, as the onboarding's is its own, and so is the short stack
// of screens that open over the tabs (a workout, then one of its exercises; Workouts or Nutrition & recovery
// from Home or Discover). While one is open the tabs stay mounted but hidden, so the tab under it is
// exactly as it was left (Home's scroll position, for one) when the way back reaches it.
export function AppShell({ session, onSignOut, coachMode = DEFAULT_COACH_MODE }: AppShellProps) {
  const { colors } = useTheme();
  const [tab, setTab] = useState<TabId>('home');
  const [stack, setStack] = useState<Route[]>([]);
  const appActive = useAppIsActive();
  const [coachContext, setCoachContext] = useState<CoachContext | null>(null);
  // The AI Coach is mounted the first time it is opened and then stays, hidden under the other tabs: its conversation,
  // and a workout it is applying, are not lost when the person looks at Home and comes back.
  const [coachMounted, setCoachMounted] = useState(false);
  if (tab === 'coach' && !coachMounted) setCoachMounted(true);
  // MOCK-ONLY: how many sets of each exercise were marked done on its screen, kept while the app runs so they are
  // still there when the exercise is opened again. Nothing is recorded: the app has no workout session yet.
  const [setsDone, setSetsDone] = useState<Record<string, number>>({});
  const route = stack.length > 0 ? stack[stack.length - 1] : null;
  // Today's workout is read from the backend (read-only) when Home is what the person is looking at: the Home
  // tab, with no screen open over it, and the app in the foreground. It is kept here, not in Home, so leaving
  // Home and coming back shows the last answer at once (see useTodayWorkout for when it asks again).
  const todayWorkout = useTodayWorkout(session, tab === 'home' && route === null && appActive);
  // The equipment saved with the profile is read from the backend (read-only) when the Profile tab is what the person
  // is looking at, as Today's workout is when Home is: it is kept here so the tab shows the last answer at once.
  const savedEquipment = useSavedEquipment(session, tab === 'profile' && route === null && appActive);

  const selectTab = useCallback((next: TabId) => {
    setTab(next);
    setCoachContext(null);
  }, []);
  const pop = useCallback(() => setStack((current) => current.slice(0, -1)), []);
  const push = useCallback((next: Route) => setStack((current) => [...current, next]), []);
  // Opens the equipment editor over the Profile tab, starting from the equipment the backend has saved.
  const openEquipmentEditor = useCallback((saved: SavedEquipment) => push({ screen: 'equipment-edit', saved }), [push]);

  // Where a control leads: a tab selects it, any other screen opens over the tabs.
  const navigate = useCallback(
    (destination: Destination) => {
      if (isTab(destination)) selectTab(destination);
      else push({ screen: 'section', section: destination });
    },
    [push, selectTab],
  );

  // Opens a workout's own screen. Only today's plan, the one Home shows from the backend, has one: it is
  // opened with what its plan carries (workoutDetailsFromPlan). Any other card still leads to the Workouts
  // screen, which is a placeholder for now and says so.
  const todayState = todayWorkout.state;
  const openWorkout = useCallback(
    (workoutId: number | string) => {
      if (todayState.kind === 'scheduled' && todayState.plan.id === workoutId) {
        push({ screen: 'workout', workout: workoutDetailsFromPlan(todayState.plan) });
      } else {
        push({ screen: 'section', section: 'workouts' });
      }
    },
    [push, todayState],
  );

  // The AI Coach tab, opened with the workout it was opened from. The workout is left exactly as it is.
  const editWithAI = useCallback((workout: { id: number | string; title: string }) => {
    setStack([]);
    setTab('coach');
    setCoachContext({ workoutId: workout.id, title: workout.title });
  }, []);

  // Android's back button closes the screen on top, then goes back to Home from any other tab, and
  // leaves the app from Home.
  useEffect(() => {
    const subscription = BackHandler.addEventListener('hardwareBackPress', () => {
      if (stack.length > 0) {
        pop();
        return true;
      }
      if (tab === 'home') return false;
      selectTab('home');
      return true;
    });
    return () => subscription.remove();
  }, [tab, stack.length, pop, selectTab]);

  return (
    <View testID="app-shell" style={{ flex: 1, backgroundColor: colors.background }}>
      <View testID="app-shell-tabs" style={{ flex: 1, display: route ? 'none' : 'flex' }}>
        <View style={{ flex: 1 }}>
          {tab === 'home' ? (
            // today's workout is the backend's; MOCK: the rest of the dashboard is made-up data (src/mock/homeMock.ts)
            <HomeScreen
              data={MOCK_HOME}
              todayWorkout={todayState}
              onRetryTodayWorkout={todayWorkout.retry}
              onNavigate={navigate}
              onOpenWorkout={openWorkout}
            />
          ) : tab === 'discover' ? (
            <DiscoverScreen onOpen={navigate} />
          ) : tab === 'profile' ? (
            // MOCK: the name is Home's made-up one, until the profile is read from the backend
            <ProfileScreen
              name={MOCK_HOME.userName}
              equipment={savedEquipment.state}
              onRetryEquipment={savedEquipment.retry}
              onEditEquipment={openEquipmentEditor}
              onSignOut={onSignOut}
            />
          ) : tab === 'coach' ? null : (
            <TabPlaceholderScreen tab={tab} />
          )}
          {coachMounted ? (
            <View testID="coach-tab" style={{ flex: 1, display: tab === 'coach' ? 'flex' : 'none' }}>
              {coachMode === 'mock' ? (
                // MOCK: a made-up conversation and workouts, answered by a made-up gateway (src/mock/); the coach API
                // is not called. Back goes where Android's back button goes from any tab other than Home.
                <MockCoachScreen
                  onBack={() => selectTab('home')}
                  coachContext={coachContext}
                  active={tab === 'coach'}
                  onApplied={todayWorkout.invalidate}
                  onOpenPreview={() => push({ screen: 'coach-preview' })}
                />
              ) : (
                <ConnectedCoachScreen
                  session={session}
                  onBack={() => selectTab('home')}
                  coachContext={coachContext}
                  active={tab === 'coach'}
                  onApplied={todayWorkout.invalidate}
                  // the static page of every card state is a development aid, not part of the app
                  onOpenPreview={__DEV__ ? () => push({ screen: 'coach-preview' }) : undefined}
                />
              )}
            </View>
          ) : null}
        </View>
        <BottomTabBar current={tab} onSelect={selectTab} />
      </View>
      {stack.map((entry, index) => (
        // every screen of the stack stays mounted and only the top one shows, so the one beneath it (the
        // workout, under one of its exercises) is as it was left when the way back reaches it
        <View
          key={`${index}-${entry.screen}`}
          testID={`route-${entry.screen}`}
          style={{ flex: 1, display: index === stack.length - 1 ? 'flex' : 'none' }}
        >
          {entry.screen === 'workout' ? (
            <WorkoutDetailsScreen
              workout={entry.workout}
              onBack={pop}
              onOpenExercise={(exercise) => push({ screen: 'exercise', workout: entry.workout, exercise })}
              onEditWithAI={() => editWithAI(entry.workout)}
            />
          ) : entry.screen === 'exercise' ? (
            <ExerciseDetailsScreen
              exercise={entry.exercise}
              onBack={pop}
              completedSets={setsDone[setsKey(entry.workout.id, entry.exercise.id)] ?? 0}
              onCompletedSetsChange={(count) =>
                setSetsDone((current) => ({ ...current, [setsKey(entry.workout.id, entry.exercise.id)]: count }))
              }
            />
          ) : entry.screen === 'equipment-edit' ? (
            // what the backend answers to a save is what the Profile tab then shows (see useSavedEquipment.replace)
            <EquipmentEditScreen session={session} saved={entry.saved} onSaved={savedEquipment.replace} onClose={pop} />
          ) : entry.screen === 'coach-preview' ? (
            <CoachCardPreviewScreen onBack={pop} />
          ) : (
            <SectionPlaceholderScreen section={entry.section} onBack={pop} />
          )}
        </View>
      ))}
    </View>
  );
}

// one exercise of one workout, as the key of its sets done
const setsKey = (workoutId: number | string, exerciseId: number | string) => `${workoutId}:${exerciseId}`;
