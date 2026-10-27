import type { IconName } from '../components';

export type TabId = 'home' | 'discover' | 'coach' | 'progress' | 'profile';

// Screens the bottom bar does not lead to. They open over the tabs, with a Back arrow, from the places that
// link to them (Home's shortcuts, Discover). Workouts and Nutrition were tabs once: their screens are kept.
export type SectionId = 'workouts' | 'nutrition' | 'exercises' | 'mobility';

// Anywhere a control can lead: a tab, or one of the screens above.
export type Destination = TabId | SectionId;

type Tab = {
  id: TabId;
  label: string;
  // outline while it is not the current tab, filled when it is, where the set has both
  icon: IconName;
  activeIcon: IconName;
};

// The five places the bottom bar leads to, left to right.
export const TABS: readonly Tab[] = [
  { id: 'home', label: 'Home', icon: 'home-outline', activeIcon: 'home' },
  { id: 'discover', label: 'Discover', icon: 'compass-outline', activeIcon: 'compass' },
  { id: 'coach', label: 'AI Coach', icon: 'chat-processing-outline', activeIcon: 'chat-processing' },
  { id: 'progress', label: 'Progress', icon: 'chart-bar', activeIcon: 'chart-bar' },
  { id: 'profile', label: 'Profile', icon: 'account-outline', activeIcon: 'account' },
];

export const SECTION_TITLES: Record<SectionId, string> = {
  workouts: 'Workouts',
  nutrition: 'Nutrition & recovery',
  exercises: 'Exercises',
  mobility: 'Mobility',
};

export function isTab(destination: Destination): destination is TabId {
  return TABS.some((tab) => tab.id === destination);
}
