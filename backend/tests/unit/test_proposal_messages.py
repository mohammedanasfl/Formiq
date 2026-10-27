"""The words of a proposal's refusals that the app reads.

The API's errors carry text (`detail`) and no code, and the app tells an approval's 409s apart by key
phrases in it, in this order (frontend/src/coach/coachErrors.ts): so each refusal must contain its own
phrase and none that is read earlier as another reason. Rewording one of them is a change to the
contract with the app, not an edit of a sentence."""

import pytest

from app.services import plan_proposal_service as service

# (the phrase the app looks for, the refusal), in the order the app checks them
READ_IN_ORDER = [
    ("expired", service.EXPIRED),
    ("rejected", service.REJECTED_PROPOSAL),
    ("already approved", service.APPROVED_PLAN_CHANGED),
    ("replaces", service.REPLACED_PLAN_CHANGED),
    ("different version", service.CHANGED),
]


@pytest.mark.parametrize("position", range(len(READ_IN_ORDER)))
def test_each_refusal_has_its_phrase_and_no_phrase_read_before_it(position):
    phrase, message = READ_IN_ORDER[position]

    assert phrase in message.lower()
    for earlier, _ in READ_IN_ORDER[:position]:
        assert earlier not in message.lower(), (earlier, message)


def test_a_rejection_that_is_refused_is_not_read_as_an_approval_refusal():
    # the app reads a rejection's 409 by its call, not by its text; these are still not mistaken
    for message in (service.REJECTION_CHANGED, service.APPROVED_NOT_REJECTABLE):
        assert "expired" not in message.lower()
