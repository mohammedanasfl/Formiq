import { View } from 'react-native';

import { ActionTile, ListRow, SectionHeader, SummaryTile, TabScreen } from '../components';
import type { HomeData } from '../mock/homeMock';
import type { Destination } from '../shell/tabs';
import { spacing } from '../theme';
import { formatLongDate, formatPercent, formatThousands, greetingText } from './format';
import { HomeHeader } from './HomeHeader';
import { WorkoutCard } from '../workouts/WorkoutCard';
import { resolveWorkoutVisual } from '../workouts/workoutImages';
import { TodayWorkoutCard } from './TodayWorkoutCard';
import type { TodayWorkoutState } from './todayWorkout';

type HomeScreenProps = {
  // Everything shown but today's workout comes from here. The app passes made-up data for now
  // (src/mock/homeMock.ts); a connected Home will pass what the backend says, and this screen will not change.
  data: HomeData;
  // what the backend says about today's workout (src/home/todayWorkout.ts): the one connected part of Home
  todayWorkout: TodayWorkoutState;
  // asks the backend again after a failure
  onRetryTodayWorkout: () => void;
  onNavigate: (destination: Destination) => void;
  // Opens one workout, by its card's id. Left out where the app cannot open a workout: its cards then open
  // the Workouts screen, as they did before a workout had a screen of its own.
  onOpenWorkout?: (workoutId: number | string) => void;
  // for tests: the date shown is the device's own, and is read each time the screen draws
  today?: Date;
};

// The Home dashboard: a greeting for the time of day with the date and the theme toggle, today's workout (the
// real one, as the backend says it: to do, running, done, none, or not readable), how the day and the week are
// going, shortcuts, the workouts coming up and recent activity. Every control leads to a screen that exists.
// Workouts and Nutrition are no longer tabs: their shortcuts here open those screens over the tabs, and "Update
// Profile" opens the Profile tab. Log out lives on the Profile tab. A workout card opens that workout's own
// screen when the app can open it (`onOpenWorkout`); where it cannot, the card opens the Workouts screen, a
// placeholder for now that says so. No workout is started, and none is made to look started.
export function HomeScreen({ data, todayWorkout, onRetryTodayWorkout, onNavigate, onOpenWorkout, today }: HomeScreenProps) {
  const { upNext, nutrition, weeklyGoal, recentActivity } = data;
  const now = today ?? new Date();
  const openWorkout = (workoutId: number | string) =>
    onOpenWorkout ? onOpenWorkout(workoutId) : onNavigate('workouts');

  return (
    <View testID="home-screen" style={{ flex: 1 }}>
      <TabScreen>
        <View style={{ gap: spacing.xl }}>
          <View style={{ gap: spacing.lg }}>
            <HomeHeader
              greeting={greetingText(now, data.userName)}
              dateLabel={formatLongDate(now)}
            />
            <View style={{ gap: spacing.md }}>
              <SectionHeader title="Today's workout" />
              <TodayWorkoutCard
                state={todayWorkout}
                today={now}
                onOpenWorkout={openWorkout}
                onAskFormiq={() => onNavigate('coach')}
                onRetry={onRetryTodayWorkout}
              />
            </View>
            <View style={{ flexDirection: 'row', gap: spacing.md }}>
              <SummaryTile
                testID="nutrition-tile"
                icon="fire"
                iconColor="warm"
                tint="primary"
                label="Nutrition"
                value={`${formatThousands(nutrition.kcal)} kcal`}
                caption="Today's target"
                progress={nutrition.progress}
                progressLabel={formatPercent(nutrition.progress)}
                onPress={() => onNavigate('nutrition')}
              />
              <SummaryTile
                testID="progress-tile"
                icon="chart-bar"
                iconColor="progress"
                tint="progress"
                label="Progress"
                value={weeklyGoal.status}
                caption="Weekly goal"
                progress={weeklyGoal.sessionsDone / weeklyGoal.sessionsTarget}
                progressLabel={`${weeklyGoal.sessionsDone} / ${weeklyGoal.sessionsTarget}`}
                onPress={() => onNavigate('progress')}
              />
            </View>
          </View>

          <View style={{ gap: spacing.md }}>
            <SectionHeader title="Quick Actions" />
            <View style={{ gap: spacing.md }}>
              <View style={{ flexDirection: 'row', gap: spacing.md }}>
                <ActionTile
                  icon="calendar-check-outline"
                  title="View Plan"
                  description="See your workouts"
                  onPress={() => onNavigate('workouts')}
                />
                <ActionTile
                  icon="chat-question-outline"
                  title="Ask Formiq"
                  description="Get AI guidance"
                  onPress={() => onNavigate('coach')}
                />
              </View>
              <View style={{ flexDirection: 'row', gap: spacing.md }}>
                <ActionTile
                  icon="silverware-fork-knife"
                  title="Log Meal"
                  description="Track your nutrition"
                  onPress={() => onNavigate('nutrition')}
                />
                <ActionTile
                  icon="account-outline"
                  title="Update Profile"
                  description="Keep your info current"
                  onPress={() => onNavigate('profile')}
                />
              </View>
            </View>
          </View>

          {upNext.length > 0 ? (
            <View style={{ gap: spacing.md }}>
              <SectionHeader title="Up next" />
              <View style={{ gap: spacing.md }}>
                {upNext.map((workout) => (
                  <WorkoutCard key={workout.id} workout={workout} onPress={() => openWorkout(workout.id)} />
                ))}
              </View>
            </View>
          ) : null}

          <View style={{ gap: spacing.md }}>
            <SectionHeader
              title="Recent Activity"
              actionLabel="See all"
              actionAccessibilityLabel="See all recent activity"
              onAction={() => onNavigate('workouts')}
            />
            <View style={{ gap: spacing.sm }}>
              {recentActivity.map((entry) => (
                <ListRow
                  key={entry.id}
                  testID={`recent-${entry.id}`}
                  title={entry.title}
                  subtitle={entry.subtitle}
                  thumbnail={resolveWorkoutVisual(entry).source}
                  onPress={() => onNavigate('workouts')}
                />
              ))}
            </View>
          </View>
        </View>
      </TabScreen>
    </View>
  );
}
