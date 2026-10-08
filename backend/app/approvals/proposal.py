"""A proposed write: what the user would be asked to approve. A proposal is a
description, never an authorization.

The model may describe a change (a ProposalDraft, from its call's arguments);
only Formiq makes it a WriteProposal, adding what the model cannot set: the
proposal's id, the trusted user from the request's runtime context, the
resource version it was based on, and when it expires. A draft that tries to
say who the user is or that the change is approved is malformed, and a request
the safety backstop flags gets no proposal at all.
"""

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Any, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.agent.safety import SafetyAssessment, assess_safety
from app.ai import ToolCall
from app.approvals.access import WriteAction

Scalar = bool | int | float | str


class ResourceType(StrEnum):
    PROFILE = "profile"
    WORKOUT_PLAN = "workout_plan"
    WORKOUT_SESSION = "workout_session"
    NUTRITION_LOG = "nutrition_log"
    USER_DATA = "user_data"


# What each action changes, and whether it names an existing resource (which
# then needs its id and the version the change was based on).
TARGETS: dict[WriteAction, tuple[ResourceType, bool]] = {
    WriteAction.CREATE_WORKOUT_PLAN: (ResourceType.WORKOUT_PLAN, False),
    WriteAction.MODIFY_WORKOUT_PLAN: (ResourceType.WORKOUT_PLAN, True),
    WriteAction.CANCEL_WORKOUT_PLAN: (ResourceType.WORKOUT_PLAN, True),
    WriteAction.RECORD_WORKOUT: (ResourceType.WORKOUT_SESSION, False),
    WriteAction.MODIFY_PROFILE: (ResourceType.PROFILE, False),
    WriteAction.RECORD_NUTRITION: (ResourceType.NUTRITION_LOG, False),
    WriteAction.DELETE_USER_DATA: (ResourceType.USER_DATA, False),
}

# Names that would claim identity or authority. Formiq sets the user and the
# proposal's id, and only an approval event approves, so none of them is ever a
# parameter, however it is spelled.
RESERVED = frozenset(
    {
        "user",
        "userid",
        "trusteduserid",
        "owner",
        "ownerid",
        "proposalid",
        "approvalid",
        "approved",
        "approval",
        "approvedby",
        "approve",
        "confirmed",
        "confirmation",
        "confirm",
        "authorized",
        "authorised",
        "authorization",
        "authorisation",
        "consent",
        "permission",
        "allowed",
        "state",
        "status",
        "version",
        "resourceversion",
    }
)

MAX_PARAMETERS = 20
MAX_VALUE_CHARS = 500
_NAME = re.compile(r"[a-z][a-z0-9_]{0,40}")


class MalformedProposal(ValueError):
    """The draft cannot be a proposal. The message names the problem, never a
    value."""


class SafetyBlocked(Exception):
    """The request, or the change itself, is safety-sensitive: no proposal."""

    def __init__(self, assessment: SafetyAssessment) -> None:
        super().__init__(f"safety-sensitive: {assessment.category}")
        self.assessment = assessment


def reserved_name(name: str) -> bool:
    """Whether the name claims identity or authority (RESERVED), however spelled."""
    return re.sub(r"[^a-z]", "", name.casefold()) in RESERVED


class ProposalDraft(BaseModel):
    """What the model may describe of a change: the action, the resource it
    changes and the new values. Nothing about who or whether."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: WriteAction
    target_id: Annotated[int, Field(ge=1, le=2_147_483_647)] | None = None
    parameters: dict[str, Scalar] = Field(default_factory=dict, max_length=MAX_PARAMETERS)

    @model_validator(mode="after")
    def check(self) -> Self:
        _, names_a_resource = TARGETS[self.action]
        if names_a_resource and self.target_id is None:
            raise ValueError(f"{self.action} needs the id of the resource it changes")
        if not names_a_resource and self.target_id is not None:
            raise ValueError(f"{self.action} does not change an existing resource")
        for name, value in self.parameters.items():
            if not _NAME.fullmatch(name):
                raise ValueError("a parameter name must be lower_snake_case")
            if reserved_name(name):
                raise ValueError(f"{name} is set by Formiq, never in a proposal")
            if isinstance(value, str) and len(value) > MAX_VALUE_CHARS:
                raise ValueError(f"{name} is longer than {MAX_VALUE_CHARS} characters")
        return self


def draft_from_call(call: ToolCall) -> ProposalDraft:
    """The draft a model's call describes: its name is the action, target_id the
    resource, every other argument a parameter. MalformedProposal when it is
    not a valid draft, including when it names a user or claims approval."""
    arguments = dict(call.arguments)
    target_id = arguments.pop("target_id", None)
    try:
        return ProposalDraft(action=call.name, target_id=target_id, parameters=arguments)
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in item['loc']) or 'draft'}: {item['msg']}"
            for item in error.errors()
        )
        raise MalformedProposal(problems) from None


@dataclass(frozen=True)
class ResourceRef:
    type: ResourceType
    id: int | None = None


@dataclass(frozen=True)
class WriteProposal:
    """A change Formiq could ask the user to approve. It authorizes nothing."""

    proposal_id: str
    # from the request's runtime context, never from the model or the draft
    trusted_user_id: int
    action: WriteAction
    target: ResourceRef
    # sorted (name, value) pairs
    parameters: tuple[tuple[str, Scalar], ...]
    # the version of the target the change was based on, when it has one
    resource_version: str | None
    created_at: datetime
    expires_at: datetime

    def binding(self) -> str:
        """What an approval approves: everything material about the change, as
        one digest. Any change to the user, action, target, values or version
        gives another binding, which no earlier approval covers."""
        material = {
            "proposal_id": self.proposal_id,
            "user": self.trusted_user_id,
            "action": str(self.action),
            "target": [str(self.target.type), self.target.id],
            "parameters": [[name, _typed(value)] for name, value in self.parameters],
            "version": self.resource_version,
        }
        text = json.dumps(material, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode()).hexdigest()

    def text_values(self) -> list[str]:
        return [value for _, value in self.parameters if isinstance(value, str)]


def _typed(value: Scalar) -> list[Any]:
    # 1, 1.0 and True compare equal in Python: their types keep them apart
    return [type(value).__name__, value]


def safety_of(request: SafetyAssessment, texts: list[str]) -> SafetyAssessment:
    """The request's assessment, or the first flag the deterministic backstop
    raises on the change's own text."""
    if request.enforced:
        return request
    for text in texts:
        if (assessment := assess_safety(text)).enforced:
            return assessment
    return request


def propose(
    draft: ProposalDraft,
    *,
    trusted_user_id: int,
    request: SafetyAssessment,
    resource_version: str | None,
    now: datetime,
    ttl: timedelta,
) -> WriteProposal:
    """Formiq's proposal for the draft. The trusted user comes from the
    request's runtime context; request is the safety backstop's assessment of
    the user's message. SafetyBlocked when it or the change is flagged;
    MalformedProposal when a change to an existing resource has no version."""
    resource_type, names_a_resource = TARGETS[draft.action]
    parameters = tuple(sorted(draft.parameters.items()))
    flagged = safety_of(request, [v for _, v in parameters if isinstance(v, str)])
    if flagged.enforced:
        raise SafetyBlocked(flagged)
    if names_a_resource and resource_version is None:
        raise MalformedProposal(f"{draft.action} needs the version of the resource it changes")
    return WriteProposal(
        proposal_id=uuid.uuid4().hex,
        trusted_user_id=trusted_user_id,
        action=draft.action,
        target=ResourceRef(resource_type, draft.target_id),
        parameters=parameters,
        resource_version=resource_version,
        created_at=now,
        expires_at=now + ttl,
    )
