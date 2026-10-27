import { useMemo, useSyncExternalStore } from 'react';

import type { WorkoutPlan } from '../api';
import { CoachScreen } from '../coach/CoachScreen';
import type { CoachMenuItem } from '../coach/CoachMenu';
import type { CoachContext } from '../shell/routes';
import { MOCK_OPENING } from './coachMock';
import { createMockCoachGateway, createMockSwitches } from './mockCoachGateway';

type MockCoachScreenProps = {
  onBack: () => void;
  coachContext?: CoachContext | null;
  active?: boolean;
  onApplied?: (plan: WorkoutPlan) => void;
  // opens the static preview of every card state
  onOpenPreview: () => void;
};

// MOCK: the AI Coach screen wired to the made-up gateway of mock mode (src/mock/mockCoachGateway.ts), with
// the extra menu items only a preview needs: the page of every card state, three switches that make the next
// request, apply or dismissal fail once, and two that leave workouts waiting for the person, which the screen finds the
// next time it looks (open it again, or Start over). The app uses it only in mock mode (src/coach/mode.ts); otherwise
// it shows ConnectedCoachScreen, which talks to the backend.
const openingFor = () => MOCK_OPENING;

export function MockCoachScreen({ onBack, coachContext, active, onApplied, onOpenPreview }: MockCoachScreenProps) {
  const switches = useMemo(() => createMockSwitches(), []);
  const gateway = useMemo(() => createMockCoachGateway(switches), [switches]);
  const state = useSyncExternalStore(switches.subscribe, switches.get);

  const items: CoachMenuItem[] = [
    { id: 'preview', label: 'Preview card states', icon: 'view-grid-outline', onPress: onOpenPreview, hint: 'Opens every state of the workout card, with nothing sent' },
    {
      id: 'fail-request',
      label: 'Mock: next request fails',
      icon: 'wifi-off',
      checked: state.failNextRequest,
      onPress: () => switches.set({ failNextRequest: !state.failNextRequest }),
      hint: 'Preview only: makes the coach fail once, to look at the error state',
    },
    {
      id: 'fail-apply',
      label: 'Mock: next apply fails',
      icon: 'alert-octagon-outline',
      checked: state.failNextApply,
      onPress: () => switches.set({ failNextApply: !state.failNextApply }),
      hint: 'Preview only: makes the next apply fail once, to look at the error state',
    },
    {
      id: 'fail-reject',
      label: 'Mock: next dismiss fails',
      icon: 'close-octagon-outline',
      checked: state.failNextReject,
      onPress: () => switches.set({ failNextReject: !state.failNextReject }),
      hint: 'Preview only: makes the next dismiss fail once, to look at the error state',
    },
    {
      id: 'waiting-one',
      label: 'Mock: a workout is waiting',
      icon: 'timer-sand',
      checked: state.waiting === 1,
      onPress: () => switches.set({ waiting: state.waiting === 1 ? 0 : 1 }),
      hint: 'Preview only: Start over, and the screen finds one workout proposed earlier',
    },
    {
      id: 'waiting-two',
      label: 'Mock: two workouts are waiting',
      icon: 'timer-sand',
      checked: state.waiting === 2,
      onPress: () => switches.set({ waiting: state.waiting === 2 ? 0 : 2 }),
      hint: 'Preview only: Start over, and the screen finds two workouts proposed earlier to choose from',
    },
  ];

  return (
    <CoachScreen
      gateway={gateway}
      openingFor={openingFor}
      onBack={onBack}
      coachContext={coachContext}
      menuItems={items}
      active={active}
      onApplied={onApplied}
    />
  );
}
