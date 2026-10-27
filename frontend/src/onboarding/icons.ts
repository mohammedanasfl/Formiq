// The picture that goes with each choice. Presentation only: the values the backend receives are in
// options.ts, and nothing here is sent anywhere. Every icon is from the one bundled set (Material
// Community); the card colors it.

import type { IconName } from '../components';
import type { GoalValue, LocationValue } from './options';

export const GOAL_ICONS: Record<GoalValue, IconName> = {
  build_muscle: 'signal-cellular-3',
  lose_weight: 'fire',
  general_fitness: 'run-fast',
};

export const LOCATION_ICONS: Record<LocationValue, IconName> = {
  gym: 'dumbbell',
  home: 'home-variant-outline',
};

const OTHER_EQUIPMENT_ICON: IconName = 'shape-outline';

// Equipment names as the catalog spells them (backend/app/catalog/free_exercise_db.py), matched on
// the words in them so that a new spelling still lands on a sensible picture. The first match wins,
// so the specific words come before the general ones. An unknown item gets a neutral shape rather
// than a wrong one.
const EQUIPMENT_ICONS: readonly { match: RegExp; icon: IconName }[] = [
  { match: /kettlebell/i, icon: 'kettlebell' },
  { match: /dumbbell/i, icon: 'dumbbell' },
  { match: /\bez\b|e-z|curl/i, icon: 'arm-flex' },
  { match: /barbell|squat|rack/i, icon: 'weight-lifter' },
  { match: /pull.?up|chin.?up/i, icon: 'human-handsup' },
  { match: /band/i, icon: 'infinity' },
  { match: /medicine/i, icon: 'basketball' },
  { match: /ball/i, icon: 'volleyball' },
  { match: /foam|roll/i, icon: 'cylinder' },
  { match: /rowing/i, icon: 'rowing' },
  { match: /bike|cycle/i, icon: 'bike' },
  { match: /treadmill/i, icon: 'run' },
  { match: /bench/i, icon: 'bench' },
  { match: /cable|machine/i, icon: 'cog-outline' },
  { match: /\bmat\b|yoga/i, icon: 'yoga' },
];

export function equipmentIcon(name: string): IconName {
  return EQUIPMENT_ICONS.find((entry) => entry.match.test(name))?.icon ?? OTHER_EQUIPMENT_ICON;
}
