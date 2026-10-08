"""Approvals of write proposals, and the gate a write must pass.

    proposal registered -> PENDING --user rejects--> REJECTED
                              |------expires------> EXPIRED
                              '--user approves----> APPROVED --expires--> EXPIRED
                                                       |
                                                    consumed --> CONSUMED (once)

Only an ApprovalEvent changes an approval: the application's record that the
user approved or rejected this exact proposal, as it was shown to them (its
binding), at Formiq's own interaction boundary. Nothing else approves: not the
model's text or calls, not the conversation history, not a tool result, not a
flag in the proposal, and not silence. The gate looks up the approval itself,
so an approval object made anywhere else is ignored.

authorize() says whether a write may run now; consume() is the same check
that also uses the approval up, once, atomically. A future write tool would
run only after consume() allows it. Every check fails closed: a missing,
mismatched, pending, rejected, expired, used or stale approval, a changed
proposal or a safety flag is a refusal, never a fallback to "approved".

ApprovalStore keeps its records in memory, per instance: it is this phase's
reference implementation of the contract, for tests, not
production persistence. A real write path would keep proposals and
approvals in the database with the same rules (and unique ids enforced there).
"""

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from app.agent.safety import SafetyAssessment
from app.approvals.access import Access, access_of
from app.approvals.proposal import WriteProposal, reserved_name, safety_of


class ApprovalState(StrEnum):
    # a read, which runs without approval
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CONSUMED = "consumed"


class ApprovalSource(StrEnum):
    """Where an approval event came from. Only the user's own action at
    Formiq's interaction boundary can approve; the others are named so a claim
    from them can be refused and recorded as what it is."""

    USER_ACTION = "user_action"
    MODEL = "model"
    CONVERSATION_HISTORY = "conversation_history"
    TOOL_RESULT = "tool_result"


class UserDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class AuthorizationFailure(StrEnum):
    PROPOSAL_NOT_FOUND = "proposal_not_found"
    PROPOSAL_ALREADY_REGISTERED = "proposal_already_registered"
    MALFORMED_PROPOSAL = "malformed_proposal"
    WRONG_USER = "wrong_user"
    APPROVAL_NOT_FOUND = "approval_not_found"
    APPROVAL_FOR_ANOTHER_PROPOSAL = "approval_for_another_proposal"
    UNTRUSTED_SOURCE = "untrusted_source"
    REPLAYED_EVENT = "replayed_event"
    ALREADY_DECIDED = "already_decided"
    NOT_APPROVED = "not_approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CONSUMED = "consumed"
    PROPOSAL_CHANGED = "proposal_changed"
    STALE_RESOURCE = "stale_resource"
    SAFETY_BLOCKED = "safety_blocked"


def approval_needed(name: str) -> ApprovalState:
    """NOT_REQUIRED for Formiq's reads; any other operation starts PENDING and
    runs only once the user approves it."""
    return ApprovalState.NOT_REQUIRED if access_of(name) is Access.READ else ApprovalState.PENDING


@dataclass(frozen=True)
class ApprovalEvent:
    """The application's record of the user's decision on one proposal."""

    event_id: str
    approval_id: str
    proposal_id: str
    # the trusted user of the request that carried the decision
    user_id: int
    # the binding of the proposal as the user was shown it
    binding: str
    decision: UserDecision
    source: ApprovalSource


@dataclass(frozen=True)
class Authorization:
    """The gate's answer: allowed, or why not."""

    allowed: bool
    state: ApprovalState | None
    failure: AuthorizationFailure | None = None


def refused(failure: AuthorizationFailure, state: ApprovalState | None = None) -> Authorization:
    return Authorization(False, state, failure)


@dataclass
class _Approval:
    approval_id: str
    proposal: WriteProposal
    binding: str
    state: ApprovalState = ApprovalState.PENDING
    events: set[str] = field(default_factory=set)


class ApprovalStore:
    """Proposals waiting for the user, their approvals, and the write gate.

    clock gives the current time and ttl how long a proposal may wait: both
    are given by the caller, so expiry is a product decision, not a constant
    here. Expiry is applied when an approval is next used; nothing runs in the
    background. Safe to share between threads.
    """

    def __init__(self, *, clock: Callable[[], datetime], ttl: timedelta) -> None:
        if ttl <= timedelta(0):
            raise ValueError("ttl must be positive")
        self.clock = clock
        self.ttl = ttl
        self._lock = threading.RLock()
        self._approvals: dict[str, _Approval] = {}
        self._by_proposal: dict[str, str] = {}

    def register(self, proposal: WriteProposal) -> Authorization | str:
        """Starts the proposal's approval as PENDING; returns its approval id,
        or the refusal. A proposal id is registered once."""
        if any(reserved_name(name) for name, _ in proposal.parameters):
            return refused(AuthorizationFailure.MALFORMED_PROPOSAL)
        with self._lock:
            if proposal.proposal_id in self._by_proposal:
                return refused(AuthorizationFailure.PROPOSAL_ALREADY_REGISTERED)
            approval_id = uuid.uuid4().hex
            self._approvals[approval_id] = _Approval(approval_id, proposal, proposal.binding())
            self._by_proposal[proposal.proposal_id] = approval_id
            return approval_id

    def record(self, event: ApprovalEvent) -> Authorization:
        """Applies the user's decision to a pending approval, when the event is
        the user's own, for this approval and this exact proposal."""
        with self._lock:
            approval = self._approvals.get(event.approval_id)
            if approval is None:
                return refused(AuthorizationFailure.APPROVAL_NOT_FOUND)
            if event.source is not ApprovalSource.USER_ACTION:
                return refused(AuthorizationFailure.UNTRUSTED_SOURCE, approval.state)
            if event.user_id != approval.proposal.trusted_user_id:
                return refused(AuthorizationFailure.WRONG_USER, approval.state)
            if event.proposal_id != approval.proposal.proposal_id:
                return refused(AuthorizationFailure.APPROVAL_FOR_ANOTHER_PROPOSAL, approval.state)
            if event.binding != approval.binding:
                # the user decided on something other than what is proposed
                return refused(AuthorizationFailure.PROPOSAL_CHANGED, approval.state)
            if event.event_id in approval.events:
                return refused(AuthorizationFailure.REPLAYED_EVENT, approval.state)
            self._expire(approval)
            if approval.state is not ApprovalState.PENDING:
                return refused(AuthorizationFailure.ALREADY_DECIDED, approval.state)
            approval.events.add(event.event_id)
            approval.state = (
                ApprovalState.APPROVED
                if event.decision is UserDecision.APPROVE
                else ApprovalState.REJECTED
            )
            return Authorization(event.decision is UserDecision.APPROVE, approval.state)

    def state(self, approval_id: str) -> ApprovalState | None:
        with self._lock:
            approval = self._approvals.get(approval_id)
            if approval is None:
                return None
            self._expire(approval)
            return approval.state

    def authorize(
        self,
        proposal: WriteProposal,
        approval_id: str,
        *,
        trusted_user_id: int,
        request: SafetyAssessment,
        current_version: str | None,
    ) -> Authorization:
        """Whether the write may run now, without using the approval up.

        trusted_user_id is the user of the request asking to run it, from its
        runtime context; request is the safety backstop's assessment of that
        request's message; current_version is the target's version now."""
        with self._lock:
            return self._check(proposal, approval_id, trusted_user_id, request, current_version)

    def consume(
        self,
        proposal: WriteProposal,
        approval_id: str,
        *,
        trusted_user_id: int,
        request: SafetyAssessment,
        current_version: str | None,
    ) -> Authorization:
        """authorize(), and when it allows the write, uses the approval up: the
        same approval never allows a second write."""
        with self._lock:
            authorization = self._check(
                proposal, approval_id, trusted_user_id, request, current_version
            )
            if authorization.allowed:
                self._approvals[approval_id].state = ApprovalState.CONSUMED
                return Authorization(True, ApprovalState.CONSUMED)
            return authorization

    def _check(
        self,
        proposal: WriteProposal,
        approval_id: str,
        trusted_user_id: int,
        request: SafetyAssessment,
        current_version: str | None,
    ) -> Authorization:
        if not isinstance(proposal, WriteProposal):
            return refused(AuthorizationFailure.MALFORMED_PROPOSAL)
        registered = self._by_proposal.get(proposal.proposal_id)
        if registered is None:
            return refused(AuthorizationFailure.PROPOSAL_NOT_FOUND)
        if proposal.trusted_user_id != trusted_user_id:
            return refused(AuthorizationFailure.WRONG_USER)
        approval = self._approvals.get(approval_id)
        if approval is None:
            return refused(AuthorizationFailure.APPROVAL_NOT_FOUND)
        if approval.proposal.trusted_user_id != trusted_user_id:
            return refused(AuthorizationFailure.WRONG_USER)
        if registered != approval_id:
            return refused(AuthorizationFailure.APPROVAL_FOR_ANOTHER_PROPOSAL)
        self._expire(approval)
        state = approval.state
        if state is not ApprovalState.APPROVED:
            failure = {
                ApprovalState.PENDING: AuthorizationFailure.NOT_APPROVED,
                ApprovalState.REJECTED: AuthorizationFailure.REJECTED,
                ApprovalState.EXPIRED: AuthorizationFailure.EXPIRED,
                ApprovalState.CONSUMED: AuthorizationFailure.CONSUMED,
            }.get(state, AuthorizationFailure.NOT_APPROVED)
            return refused(failure, state)
        if proposal.binding() != approval.binding:
            return refused(AuthorizationFailure.PROPOSAL_CHANGED, state)
        if current_version != approval.proposal.resource_version:
            # the target changed since the proposal was made: never overwrite it
            return refused(AuthorizationFailure.STALE_RESOURCE, state)
        if safety_of(request, approval.proposal.text_values()).enforced:
            return refused(AuthorizationFailure.SAFETY_BLOCKED, state)
        return Authorization(True, state)

    def _expire(self, approval: _Approval) -> None:
        if approval.state in (ApprovalState.PENDING, ApprovalState.APPROVED) and (
            self.clock() >= approval.proposal.expires_at
        ):
            approval.state = ApprovalState.EXPIRED


def user_event(
    approval_id: str,
    proposal: WriteProposal,
    decision: UserDecision,
    *,
    trusted_user_id: int,
) -> ApprovalEvent:
    """The event Formiq's interaction boundary records when the user, the
    request's trusted user, decides on the proposal they were shown."""
    return ApprovalEvent(
        event_id=uuid.uuid4().hex,
        approval_id=approval_id,
        proposal_id=proposal.proposal_id,
        user_id=trusted_user_id,
        binding=proposal.binding(),
        decision=decision,
        source=ApprovalSource.USER_ACTION,
    )

