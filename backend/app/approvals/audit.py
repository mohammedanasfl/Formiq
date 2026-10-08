"""What a write proposal's approval and authorization may record for
observability: identifiers Formiq generated, names and states, never the
change's values, the user's data, the conversation, the instructions or the
model's reasoning (the Phase 4.8 rules, through safe_metadata)."""

from app.approvals.proposal import WriteProposal
from app.approvals.store import ApprovalSource, ApprovalState, Authorization
from app.observability import safe_metadata
from app.observability.tracing import Metadata


def audit_metadata(
    proposal: WriteProposal,
    *,
    state: ApprovalState | None,
    source: ApprovalSource | None,
    authorization: Authorization | None,
) -> Metadata:
    return safe_metadata(
        {
            "proposal_id": proposal.proposal_id,
            "write_action": proposal.action,
            "target_type": proposal.target.type,
            "trusted_user_id": proposal.trusted_user_id,
            "approval_state": state,
            "approval_source": source,
            "proposal_version": proposal.resource_version,
            "authorization": None
            if authorization is None
            else ("allowed" if authorization.allowed else "denied"),
            "rejection_reason": authorization.failure if authorization else None,
        }
    )
