import { useMemo } from 'react';

import type { Session, WorkoutPlan } from '../api';
import type { CoachContext } from '../shell/routes';
import { createApiCoachGateway } from './apiGateway';
import { CoachScreen } from './CoachScreen';
import type { CoachMenuItem } from './CoachMenu';
import { coachOpening } from './opening';

type ConnectedCoachScreenProps = {
  // who is signed in: the coach acts for them, with their token
  session: Session;
  onBack: () => void;
  // set when the tab was opened from a workout ("Edit with AI")
  coachContext?: CoachContext | null;
  active?: boolean;
  // after the backend confirmed a workout was saved: the plan it answered with
  onApplied?: (plan: WorkoutPlan) => void;
  // when given, the menu offers the static page of every card state (a development aid: nothing is sent)
  onOpenPreview?: () => void;
};

// The AI Coach screen on the Formiq backend: the coach's answers come from POST /coach/message, and a workout is
// saved only when the person applies it and the backend's approval route says so.
export function ConnectedCoachScreen({ session, onBack, coachContext, active, onApplied, onOpenPreview }: ConnectedCoachScreenProps) {
  const gateway = useMemo(() => createApiCoachGateway(session), [session]);
  const menuItems = useMemo<CoachMenuItem[]>(
    () =>
      onOpenPreview
        ? [{ id: 'preview', label: 'Preview card states', icon: 'view-grid-outline', onPress: onOpenPreview, hint: 'Opens every state of the workout card, with nothing sent' }]
        : [],
    [onOpenPreview],
  );

  return (
    <CoachScreen
      gateway={gateway}
      openingFor={coachOpening}
      onBack={onBack}
      coachContext={coachContext}
      menuItems={menuItems}
      active={active}
      onApplied={onApplied}
    />
  );
}
