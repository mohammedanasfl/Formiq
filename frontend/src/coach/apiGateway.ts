import {
  approveProposal,
  deviceTimeZone,
  getPendingProposals,
  rejectProposal,
  sendCoachMessage,
  type Session,
} from '../api';
import type { CoachGateway } from './gateway';

// The gateway of the connected app: the four things the AI Coach screen asks, answered by the Formiq backend for
// the signed-in user (src/api/coach.ts). Every method rejects with an ApiError when it fails, which the screen
// turns into a sentence (coachErrors.ts). It keeps no conversation: the screen sends the earlier turns each time.
export function createApiCoachGateway(session: Session): CoachGateway {
  return {
    // the device's time zone goes with every message: the coach's "tomorrow" is the user's own
    send: (request) => sendCoachMessage(session, { ...request, timeZone: deviceTimeZone() }),
    pending: () => getPendingProposals(session),
    approve: (proposal) => approveProposal(session, proposal),
    reject: (proposal) => rejectProposal(session, proposal),
  };
}
