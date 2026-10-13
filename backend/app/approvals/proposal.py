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
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Any, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.agent.safety import SafetyAssessment, assess_safety
from app.ai import ToolCall
from app.approvals.access import WriteAction

Scalar = bool | int | float | str
# A list of flat records, such as the exercises of a new workout plan: one
# level of nesting, under the same name and size rules as the parameters.
Records = list[dict[str, Scalar]]
# a parameter value as a WriteProposal holds it: a records value is frozen into
# a tuple of each record's sorted (name, value) pairs
Value = Scalar | tuple[tuple[tuple[str, Scalar], ...], ...]


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
MAX_RECORDS = 20
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
    parameters: dict[str, Scalar | Records] = Field(default_factory=dict, max_length=MAX_PARAMETERS)

    @model_validator(mode="after")
    def check(self) -> Self:
        _, names_a_resource = TARGETS[self.action]
        if names_a_resource and self.target_id is None:
            raise ValueError(f"{self.action} needs the id of the resource it changes")
        if not names_a_resource and self.target_id is not None:
            raise ValueError(f"{self.action} does not change an existing resource")
        for name, value in self.parameters.items():
            _check_parameter(name, value)
            if isinstance(value, list):
                if len(value) > MAX_RECORDS:
                    raise ValueError(f"{name} has more than {MAX_RECORDS} records")
                for record in value:
                    if len(record) > MAX_PARAMETERS:
                        raise ValueError(f"a record of {name} has too many values")
                    for key, item in record.items():
                        _check_parameter(key, item)
        return self


def _check_parameter(name: str, value: Any) -> None:
    if not _NAME.fullmatch(name):
        raise ValueError("a parameter name must be lower_snake_case")
    if reserved_name(name):
        raise ValueError(f"{name} is set by Formiq, never in a proposal")
    if isinstance(value, str) and len(value) > MAX_VALUE_CHARS:
        raise ValueError(f"{name} is longer than {MAX_VALUE_CHARS} characters")


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
    parameters: tuple[tuple[str, Value], ...]
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
        return _texts(self.parameters)

    def names(self) -> list[str]:
        """Every parameter name, the records' own included."""
        return [name for name, _ in _pairs(self.parameters)]

    def values(self) -> dict[str, Any]:
        """The parameters as plain data, records as lists of dicts."""
        return {
            name: [dict(record) for record in value] if isinstance(value, tuple) else value
            for name, value in self.parameters
        }


def _pairs(parameters: tuple[tuple[str, Value], ...]) -> list[tuple[str, Scalar]]:
    """Every (name, value) pair, the records' own included."""
    pairs: list[tuple[str, Scalar]] = []
    for name, value in parameters:
        if isinstance(value, tuple):
            pairs += [pair for record in value for pair in record]
        else:
            pairs.append((name, value))
    return pairs


def _texts(parameters: tuple[tuple[str, Value], ...]) -> list[str]:
    return [value for _, value in _pairs(parameters) if isinstance(value, str)]


def _typed(value: Value) -> list[Any]:
    # 1, 1.0 and True compare equal in Python: their types keep them apart
    if isinstance(value, tuple):
        return ["records", [[[key, _typed(item)] for key, item in record] for record in value]]
    return [type(value).__name__, value]


def _frozen(value: Scalar | Records) -> Value:
    if isinstance(value, list):
        return tuple(tuple(sorted(record.items())) for record in value)
    return value


@dataclass(frozen=True)
class ProposalTerms:
    """When a proposal is made, and how long it may wait for the user's
    approval: Formiq's clock and the time to live, a product decision
    (app.api.dependencies), given by the caller."""

    clock: Callable[[], datetime]
    ttl: timedelta


def restore(
    *,
    proposal_id: str,
    trusted_user_id: int,
    action: WriteAction,
    parameters: dict[str, Scalar | Records],
    created_at: datetime,
    expires_at: datetime,
) -> WriteProposal:
    """A stored new-resource proposal (no target id, no version), as propose()
    made it: parameters are its values() as they were stored. Its binding is
    the original's only if nothing about it changed, so a stored proposal that
    was altered no longer matches the binding it was shown with."""
    resource_type, _ = TARGETS[action]
    return WriteProposal(
        proposal_id=proposal_id,
        trusted_user_id=trusted_user_id,
        action=action,
        target=ResourceRef(resource_type),
        parameters=tuple(sorted((name, _frozen(value)) for name, value in parameters.items())),
        resource_version=None,
        created_at=created_at,
        expires_at=expires_at,
    )


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
    parameters = tuple(sorted((name, _frozen(value)) for name, value in draft.parameters.items()))
    flagged = safety_of(request, _texts(parameters))
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
