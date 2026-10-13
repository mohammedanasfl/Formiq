"""The write boundary: which operations would change Formiq data, what a
proposed change is, and the approval a change needs before it may run.

A model's proposal is never an authorization. Formiq's one write, creating a
workout plan the coach proposed, goes through this package: only the user's own
approval of the exact proposal lets it run, once. The package holds the rules
and reaches no data: the proposals waiting for approval are kept in the
database by app.services.plan_proposal_service.
"""

from app.approvals.access import (
    PROPOSAL_ACTIONS,
    READ_ACTIONS,
    WRITE_ACTIONS,
    Access,
    WriteAction,
    access_of,
    is_write_action,
)
from app.approvals.audit import audit_metadata
from app.approvals.proposal import (
    MalformedProposal,
    ProposalDraft,
    ProposalTerms,
    ResourceRef,
    ResourceType,
    SafetyBlocked,
    WriteProposal,
    draft_from_call,
    propose,
    restore,
    safety_of,
)
from app.approvals.store import (
    ApprovalEvent,
    ApprovalSource,
    ApprovalState,
    ApprovalStore,
    Authorization,
    AuthorizationFailure,
    UserDecision,
    approval_needed,
    user_event,
)

__all__ = [
    "PROPOSAL_ACTIONS",
    "READ_ACTIONS",
    "WRITE_ACTIONS",
    "Access",
    "ApprovalEvent",
    "ApprovalSource",
    "ApprovalState",
    "ApprovalStore",
    "Authorization",
    "AuthorizationFailure",
    "MalformedProposal",
    "ProposalDraft",
    "ProposalTerms",
    "ResourceRef",
    "ResourceType",
    "SafetyBlocked",
    "UserDecision",
    "WriteAction",
    "WriteProposal",
    "access_of",
    "approval_needed",
    "audit_metadata",
    "draft_from_call",
    "is_write_action",
    "propose",
    "restore",
    "safety_of",
    "user_event",
]
