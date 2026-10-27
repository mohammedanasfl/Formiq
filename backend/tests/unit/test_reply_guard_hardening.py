"""The reply guard holds a reply to Formiq's records, whatever the wording, quoting or punctuation
(Phase 2.7). Adversarial regressions for what the Phase 2.6 live pass found.

- A quoted or ampersand name defeated the change-claim check: "I have adjusted your "Core & Abs
  Focus" workout to ..." passed, and so did the same sentence with an unquoted name of three
  words: the pattern allowed two words between "your" and "workout". The claims are now
  classified on a normalized reply in which every workout name is one word (the turn's known
  names, quoted spans, capitalised names before "workout" or "plan"): normalize_claims.
- Three truthful statements about a proposal awaiting approval ("The harder version I proposed is
  currently awaiting your approval") were rejected as claims of a new version, each costing a
  model request. A word for a new or changed workout is now a claim unless its sentence says the
  workout awaits approval AND Formiq's record of that proposal supports the word
  (pending_descriptors); a first-person "I created / I just updated" is always a claim.
- "plan 6 has been updated" was backed by an approval of plan 5.

The facts are given to reply_problem() directly (app.agent.trust.Lifecycle and the rest), so what
these pin is the rule, whatever model wrote the words: no model, no database. Scripted words are
not evidence of how Gemini words things; only a live pass is.
"""

import pytest

from app.agent.graph import COACH_INSTRUCTIONS
from app.agent.policy import pending_descriptors, pending_proposal_names, workout_names
from app.agent.trust import (
    REPLY_CLAIMS_APPLIED,
    REPLY_CLAIMS_CHANGE,
    REPLY_CLAIMS_CREATION,
    REPLY_CLAIMS_NEW_PROPOSAL,
    REPLY_CLAIMS_PROPOSAL,
    REPLY_DENIES_PENDING,
    REPLY_DENIES_PENDING_ELSEWHERE,
    REPLY_PRESENTS_REFUSED,
    Lifecycle,
    normalize_claims,
    reply_problem,
)
from app.ai import ToolCall, ToolResult

TOOLS = ("propose_workout_plan", "get_pending_proposal")
PLAN = "Core & Abs Focus"
HARDER = "Core & Abs Focus (Harder)"
SHORTER = "Shorter Core & Abs Focus"
KNOWN = (PLAN, HARDER, SHORTER)


def check(reply, lifecycle=None, *, names=KNOWN, **facts):
    return reply_problem(
        reply,
        COACH_INSTRUCTIONS,
        TOOLS,
        lifecycle=lifecycle if lifecycle is not None else Lifecycle(),
        workout_names=names,
        **facts,
    )


def pending_record(name=HARDER, revision="ADJUST", changed=(), added=(), removed=()):
    """What the turn read of the proposal awaiting approval (get_pending_proposal), as results."""
    output = {
        "name": name,
        "coverage": {"complete": True},
        # a new workout replaces no plan: no revision, nothing to compare with
        "revision": None
        if revision is None
        else {"kind": revision, "replaces_plan_id": 5, "replaces_plan_name": PLAN},
        "changes": None
        if revision is None
        else {
            "compared_with_plan_id": 5,
            "compared_with_plan_name": PLAN,
            "added": [dict(item) for item in added],
            "removed": [dict(item) for item in removed],
            "changed": [dict(item) for item in changed],
        },
    }
    return [ToolResult(ToolCall(name="get_pending_proposal", arguments={}), {"output": output})]


def more_sets(name="Bird Dog"):
    return {"exercise_name": name, "before": "3 sets of 12 reps, 90 s rest", "after": "4 sets of 12 reps, 90 s rest"}


# --- 1. quoted names, in any quotation style ---

QUOTES = [
    ('"', '"'),
    ("“", "”"),
    ("„", "“"),
    ("«", "»"),
    ("‘", "’"),
    ("`", "`"),
    ("", ""),
]
QUOTE_IDS = ["straight", "curly", "low-high", "guillemets", "single curly", "backticks", "unquoted"]


def quoted(text, name, quote):
    return text.replace("{n}", f"{quote[0]}{name}{quote[1]}")


@pytest.mark.parametrize("quote", QUOTES, ids=QUOTE_IDS)
@pytest.mark.parametrize("name", KNOWN)
@pytest.mark.parametrize(
    "template",
    [
        "I have adjusted your {n} workout to set the Cable Woodchop to 20 kg.",
        "I've updated your {n} plan so the Cable Woodchop is 20 kg.",
        "I just revised your {n} routine.",
        "I rescheduled your {n} session for Saturday.",
        "I have moved your {n} workout to Saturday.",
    ],
)
def test_a_change_claim_is_caught_whatever_the_workout_is_called_and_however_it_is_quoted(
    template, name, quote
):
    reply = quoted(template, name, quote)

    # in a turn that proposed something, and in one that did not
    assert check(reply, proposed=True) == REPLY_CLAIMS_CHANGE, reply
    assert check(reply) == REPLY_CLAIMS_CHANGE, reply
    # and with no record of the name: quoting or capitals alone are enough
    assert check(reply, names=()) == REPLY_CLAIMS_CHANGE, reply


@pytest.mark.parametrize("quote", QUOTES, ids=QUOTE_IDS)
@pytest.mark.parametrize("name", KNOWN)
@pytest.mark.parametrize(
    "template",
    [
        "I've updated {n} so the Cable Woodchop is 20 kg.",
        "I have adjusted {n} to use 20 kg.",
        "I applied the changes to {n}.",
    ],
)
def test_a_workout_named_as_the_object_of_a_change_is_a_change_claim(template, name, quote):
    assert check(quoted(template, name, quote), proposed=True) == REPLY_CLAIMS_CHANGE


@pytest.mark.parametrize("quote", QUOTES, ids=QUOTE_IDS)
@pytest.mark.parametrize("name", KNOWN)
@pytest.mark.parametrize(
    "template",
    [
        "{n} is now saved for Friday.",
        "{n} has been applied.",
        "Your {n} workout is saved.",
        "{n} is all set.",
    ],
)
def test_a_proposal_is_never_called_saved_whatever_its_name_looks_like(template, name, quote):
    lifecycle = Lifecycle(plans_read=frozenset({5}))

    assert check(quoted(template, name, quote), lifecycle, proposed=True) == REPLY_CLAIMS_APPLIED


def test_a_name_of_more_than_two_words_no_longer_slips_between_your_and_workout():
    """The pattern read at most two words there: "your lower-body workout"."""
    for name in ("Core Abs Focus", "Upper Body Strength", "Total Body Burn Express", "Push Pull Legs Day"):
        assert check(f"I have adjusted your {name} workout to set it to 20 kg.", names=()) == (
            REPLY_CLAIMS_CHANGE
        ), name


# --- 2. ampersands, punctuation and parentheses in names ---

AWKWARD = [
    "Core & Abs Focus (Harder)",
    "Upper/Lower Split: Day 1 (Push)",
    "Bob's Burn-Out #2",
    "Legs + Glutes!",
    "Full-Body 30' Express",
    "Arms, Shoulders & Back",
    "Core&Abs Focus",
    "Mon–Wed Strength (Week 2)",
]


@pytest.mark.parametrize("name", AWKWARD)
@pytest.mark.parametrize("quote", [('"', '"'), ("", "")], ids=["quoted", "unquoted"])
def test_ampersands_punctuation_and_parentheses_in_a_name_decide_nothing(name, quote):
    known = (name,)
    change = quoted("I have adjusted your {n} workout to set the Cable Woodchop to 20 kg.", name, quote)
    state = quoted("Your {n} workout is saved for Friday.", name, quote)

    assert check(change, names=known, proposed=True) == REPLY_CLAIMS_CHANGE, change
    assert check(state, names=known, proposed=True) == REPLY_CLAIMS_APPLIED, state
    # the truth about the same workout, in the same punctuation, passes
    truth = quoted("I have proposed changes to your {n} workout; they await your approval.", name, quote)
    assert check(truth, names=known, proposed=True) is None, truth


def test_a_name_may_be_written_without_its_decoration_or_with_and_for_ampersand():
    for written in ("Core and Abs Focus", "core & abs focus", "CORE & ABS FOCUS", "Core & Abs  Focus", "Core & Abs Focus (Harder)"):
        assert check(f"I have adjusted your {written} workout to 20 kg.", names=(HARDER,)) == REPLY_CLAIMS_CHANGE


def test_normalizing_changes_only_what_the_claims_read_and_never_a_number_or_an_id():
    text = normalize_claims('Your "Core & Abs Focus (Harder)" workout takes about 40 minutes, id 0123456789abcdef0123456789abcdef.', KNOWN)

    assert text == "Your WORKOUTNAME workout takes about 40 minutes, id 0123456789abcdef0123456789abcdef."
    # a one-word name is an ordinary word as often as a name: collapsed only as it is written
    assert normalize_claims("Your strength workout.", ("Strength",)) == "Your strength workout."
    assert normalize_claims("Inferno is saved.", ("Inferno",)) == "WORKOUTNAME is saved."
    assert normalize_claims('"Unknown & Plan (v2)" has been applied.') == "WORKOUTNAME has been applied."


def test_a_reply_that_hides_an_internal_name_in_quotes_is_still_caught_on_the_reply_itself():
    assert check('Say "CANNOT_ANSWER" to continue.') is not None
    assert check("Use propose_workout_plan now.") is not None


def test_an_unknown_quoted_ampersand_name_cannot_bypass_an_applied_claim():
    reply = '**"Unknown & Plan: Phase (v2)"** has been applied.'

    assert check(reply, names=()) == REPLY_CLAIMS_APPLIED


# --- 3. adjusted, updated, saved, applied, proposed, awaiting approval ---


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ("Your workout was adjusted.", REPLY_CLAIMS_APPLIED),
        ("Your plan has been updated for Saturday.", REPLY_CLAIMS_APPLIED),
        ("Your workout is saved.", REPLY_CLAIMS_APPLIED),
        ("The changes are applied.", REPLY_CLAIMS_APPLIED),
        ("It is approved and in place.", REPLY_CLAIMS_APPLIED),
        # said by the coach: never true, whatever the turn did
        ("I have updated your workout.", REPLY_CLAIMS_CHANGE),
        ("I saved your plan.", REPLY_CLAIMS_CHANGE),
        ("I've applied your plan.", REPLY_CLAIMS_CHANGE),
    ],
)
def test_after_a_proposal_nothing_is_adjusted_updated_saved_or_applied(reply, expected):
    assert check(reply, Lifecycle(plans_read=frozenset({5})), proposed=True) == expected


@pytest.mark.parametrize(
    "reply",
    [
        "I have proposed moving your workout to Saturday. It awaits your approval in Formiq.",
        "I've proposed a harder version of your workout: it is awaiting your approval.",
        "I proposed one more set on each exercise. Review it and approve it in Formiq when you are ready.",
        "Your workout is unchanged until you approve the proposal.",
    ],
)
def test_after_a_proposal_proposed_and_awaiting_approval_are_the_truth(reply):
    assert check(reply, proposed=True) is None


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ("Your proposal is awaiting your approval in Formiq.", REPLY_CLAIMS_PROPOSAL),
        ("Review and approve it in Formiq.", REPLY_CLAIMS_PROPOSAL),
        ("I have proposed a new workout for you.", REPLY_CLAIMS_CREATION),
        ("I've drafted a revised plan for Saturday.", REPLY_CLAIMS_CREATION),
    ],
)
def test_with_nothing_proposed_and_nothing_pending_none_of_it_is_the_truth(reply, expected):
    assert check(reply) == expected


# --- 4. a proposal call that was refused or failed, then a false success claim ---

REFUSED = Lifecycle(refused=True)


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        # the two the live pass caught after Formiq refused a proposal
        (
            'I have updated the proposal to schedule your "Core & Abs Focus" workout for Saturday, '
            "October 31 instead, keeping the same exercises. You can review and approve this updated "
            "proposal in Formiq.",
            REPLY_CLAIMS_CHANGE,
        ),
        (
            'I have proposed moving your "Core & Abs Focus" workout to Saturday, October 31 instead. '
            "You can review and approve this in Formiq.",
            REPLY_CLAIMS_PROPOSAL,
        ),
        ("Here is the updated workout, moved to Saturday.", REPLY_CLAIMS_CREATION),
        ("Done: I moved it. Take a look at the card below.", None),
        ("I've put together a new version for you, see below.", REPLY_CLAIMS_CREATION),
    ],
)
def test_a_refused_proposal_is_no_evidence_that_one_exists(reply, expected):
    problem = check(reply, REFUSED)

    if expected is None:
        # not a claim of the older kinds: the refused-proposal rule holds it
        assert problem in (
            REPLY_PRESENTS_REFUSED,
            REPLY_CLAIMS_PROPOSAL,
            REPLY_CLAIMS_CREATION,
            REPLY_CLAIMS_CHANGE,
        ), reply
    else:
        assert problem == expected, reply


@pytest.mark.parametrize(
    "reply",
    [
        "I couldn't make that change: Formiq did not accept it. Which day would you like?",
        "That move didn't go through, so nothing was proposed. Tell me the exact day and I will try again.",
        "I wasn't able to do that. Do you want Saturday or Sunday?",
    ],
)
def test_after_a_refused_proposal_saying_so_is_allowed(reply):
    assert check(reply, REFUSED) is None


def test_a_failed_proposal_is_as_good_as_a_refused_one():
    """A call that errored is a result without an output, like a refusal: the graph's fact is the
    same (lifecycle.refused), so nothing is presented."""
    from app.agent.graph import lifecycle_of, proposal_attempted
    from app.agent.graph import CoachContext
    from tests.coach import fake_provider

    failed = [
        ToolResult(
            ToolCall(name="propose_workout_plan", arguments={"name": "X"}),
            {"error": {"code": "TOOL_ERROR", "message": "a plan cannot be proposed here"}},
        )
    ]
    context = CoachContext(user_id=1, provider=fake_provider(), tools=object())  # type: ignore[arg-type]

    assert proposal_attempted(failed)
    assert lifecycle_of(context, failed, failed).refused is True


def test_a_refused_attempt_does_not_erase_an_independently_read_pending_record():
    record = pending_record(HARDER, changed=[more_sets()])
    reply = "The harder version I proposed is currently awaiting your approval."

    assert (
        check(
            reply,
            REFUSED,
            awaiting_approval=True,
            names=workout_names(record),
            pending_support=pending_descriptors(record),
        )
        is None
    )
    # Without the successful pending-record evidence, the same words remain unsupported.
    assert (
        check(
            reply,
            REFUSED,
            awaiting_approval=True,
            explaining=True,
            names=workout_names(record),
        )
        == REPLY_CLAIMS_NEW_PROPOSAL
    )


def test_pending_evidence_for_one_named_plan_does_not_support_another_named_plan():
    pending = pending_record("Plan B (Harder)", changed=[more_sets()])
    facts = {
        "awaiting_approval": True,
        "explaining": True,
        "recorded_changes": [],
        "names": ("Plan A", "Plan B", "Plan B (Harder)"),
        "pending_support": pending_descriptors(pending),
        "pending_names": pending_proposal_names(pending),
    }

    assert check('The harder version of "Plan B" is awaiting your approval.', **facts) is None
    assert (
        check('The harder version of "Plan A" is awaiting your approval.', **facts)
        == REPLY_CLAIMS_NEW_PROPOSAL
    )
    assert check('If you approve "Plan B", it will be applied.', **facts) is None


# --- 5. a pending proposal followed by a false applied claim ---


@pytest.mark.parametrize(
    "reply",
    [
        "Yes, it's saved and your plan has been updated.",
        "Your plan is now updated to Saturday.",
        "That's applied: your workout is on Saturday now.",
        "All set, done! Your changes are in.",
        "Your workout has been scheduled for Saturday.",
        "The proposal was approved and your plan is locked in.",
    ],
)
@pytest.mark.parametrize("explaining", [True, False])
def test_a_proposal_awaiting_approval_is_never_said_to_be_applied(reply, explaining):
    problem = check(
        reply, Lifecycle(plans_read=frozenset({5})), awaiting_approval=True,
        explaining=explaining, recorded_changes=[],
    )  # fmt: skip

    assert problem == REPLY_CLAIMS_APPLIED, reply


# --- 6. a successful approval, then a truthful confirmation ---

APPROVED = Lifecycle(plans_read=frozenset({5}), approved_plans=frozenset({5}))


@pytest.mark.parametrize(
    "reply",
    [
        "Yes, your workout is saved for Friday, 30 October.",
        "Your plan has been updated to Friday.",
        "Your changes are applied.",
        'Yes, "Core & Abs Focus" is saved and scheduled for Friday.',
        "Your Core & Abs Focus workout has been updated.",
        "Plan 5 is saved and updated for Friday.",
    ],
)
def test_a_saved_plan_an_approval_made_may_be_called_saved_updated_and_applied(reply):
    assert check(reply, APPROVED) is None, reply


def test_even_after_an_approval_the_coach_did_not_do_it_itself():
    assert check("I've saved your workout.", APPROVED) == REPLY_CLAIMS_CHANGE
    assert check('I have updated your "Core & Abs Focus" workout.', APPROVED) == REPLY_CLAIMS_CHANGE


# --- 7. a truthful pending statement must not cost a retry ---

LIVE_TRUE = [
    # the three the Phase 2.6 live pass rejected, word for word
    "I proposed a harder version earlier; it's awaiting your approval. You can review it in Formiq.",
    "No, it hasn't saved yet. The harder version I proposed is currently awaiting your approval. "
    "You can review and approve it directly in Formiq to update your saved plan.",
    "No, it has not saved yet. The harder version of your Core & Abs Focus workout is currently "
    "awaiting your approval in Formiq. Once you review and approve it there, it will replace your saved plan.",
    "No, it has not been saved yet. The shorter version of your workout is currently proposed and "
    "awaiting your approval in Formiq. You can review and approve it there whenever you are ready, "
    "which will replace your saved plan.",
]


def record_for(reply):
    """The record of a proposal the reply truthfully describes."""
    if "shorter" in reply:
        return pending_record(SHORTER, removed=[{"exercise_name": "Cable Woodchop"}])
    return pending_record(HARDER, changed=[more_sets()])


@pytest.mark.parametrize("reply", LIVE_TRUE, ids=["earlier", "38", "39", "85"])
@pytest.mark.parametrize("explaining", [True, False])
def test_the_truthful_statements_the_live_pass_rejected_are_not(reply, explaining):
    record = record_for(reply)

    problem = check(
        reply,
        awaiting_approval=True,
        explaining=explaining,
        recorded_changes=[],
        names=workout_names(record),
        pending_support=pending_descriptors(record),
    )

    assert problem is None, reply


@pytest.mark.parametrize("reply", LIVE_TRUE, ids=["earlier", "38", "39", "85"])
def test_the_same_statements_are_still_claims_when_the_record_does_not_support_them(reply):
    """No pending proposal read (no support), or one that is not harder or shorter: the words are
    the model's own, and the strict check stands."""
    unrelated = pending_record("Core & Abs Focus", changed=[])
    for evidence in (frozenset(), pending_descriptors(unrelated)):
        problem = check(
            reply, awaiting_approval=True, explaining=True, recorded_changes=[], pending_support=evidence
        )
        assert problem == REPLY_CLAIMS_NEW_PROPOSAL, (reply, evidence)


@pytest.mark.parametrize(
    "reply",
    [
        "Not yet: the updated workout is waiting for your approval in Formiq.",
        "The proposal for Saturday is still pending approval.",
        "It is not saved yet, it needs your approval.",
        "Nothing is saved until you approve it, and the revised plan is awaiting that.",
        "Your changed plan is awaiting your approval. Once you approve it, it will be saved.",
    ],
)
def test_other_truthful_ways_to_say_a_revision_is_waiting_pass_once_without_a_retry(reply):
    record = pending_record(changed=[more_sets()])

    assert check(
        reply, awaiting_approval=True, explaining=True, recorded_changes=[],
        names=workout_names(record), pending_support=pending_descriptors(record),
    ) is None, reply  # fmt: skip


@pytest.mark.parametrize(
    "reply",
    [
        # a word the record does not back, though the sentence says it awaits approval
        "The easier version I proposed is awaiting your approval.",
        "The lighter version of your workout is waiting for your approval.",
        # the coach saying it made or changed one, in the same sentence as the truth
        "I've created a new harder version that is awaiting your approval.",
        "I just updated it and it awaits your approval.",
        "I have now adjusted the plan; the harder version is pending your approval.",
        # a new version said to be ready, with nothing about waiting
        "Your updated plan is ready.",
        "Here is the harder version of your workout.",
        "Approve the new version in Formiq.",
    ],
)
def test_a_lie_is_not_excused_by_a_true_sentence_beside_it(reply):
    record = pending_record(changed=[more_sets()])  # a harder, revised proposal

    problem = check(
        reply, awaiting_approval=True, explaining=True, recorded_changes=[],
        names=workout_names(record), pending_support=pending_descriptors(record),
    )  # fmt: skip

    assert problem is not None, reply


def test_what_a_record_supports_is_its_name_what_it_is_and_the_direction_of_its_changes():
    harder = pending_descriptors(pending_record(HARDER, changed=[more_sets()]))
    shorter = pending_descriptors(pending_record(SHORTER, removed=[{"exercise_name": "x"}]))
    lighter = pending_descriptors(
        pending_record("Core", changed=[{"exercise_name": "Woodchop", "before": "3 sets of 10 reps at 20 kg", "after": "3 sets of 10 reps at 15 kg"}])
    )
    mixed = pending_descriptors(
        pending_record(
            "Core",
            changed=[
                {"exercise_name": "Bird Dog", "before": "3 sets of 12 reps, 90 s rest", "after": "4 sets of 10 reps, 90 s rest"}
            ],
        )
    )
    new = pending_descriptors(pending_record("Fresh Legs", revision=None))
    alternative = pending_descriptors(pending_record("Other", revision="ALTERNATIVE"))

    assert {"harder", "revised", "updated", "core", "abs", "focus"} <= harder
    assert "easier" not in harder and "shorter" not in harder
    assert {"shorter", "easier"} <= shorter and "harder" not in shorter
    assert {"lighter", "easier"} <= lighter and "harder" not in lighter
    # more sets but fewer reps: neither harder nor easier is the record's to say
    assert not ({"harder", "easier", "longer", "shorter"} & mixed) and {"revised", "updated"} <= mixed
    assert {"new", "fresh", "another"} <= new and "updated" not in new
    assert {"alternative", "different", "updated"} <= alternative
    assert pending_descriptors([]) == frozenset()


# --- 8. no proposal for this target, and none anywhere ---

ELSEWHERE = Lifecycle(others_awaiting=1)


@pytest.mark.parametrize(
    "reply",
    [
        "There is no proposal awaiting approval for this workout.",
        "Nothing is pending for this plan right now.",
        "I don't have a proposal waiting for it.",
        'No pending proposal for your "Core & Abs Focus" workout.',
        "The proposal for this workout has expired.",
    ],
)
def test_no_proposal_for_this_workout_is_a_true_statement_when_others_wait(reply):
    assert check(reply, ELSEWHERE) is None, reply


@pytest.mark.parametrize(
    "reply",
    [
        "You don't have any proposals awaiting approval.",
        "There is nothing pending.",
        "No pending proposals.",
        "You have no proposals waiting for review.",
        "Your proposal has expired.",
        "That proposal was rejected.",
        "The proposal is no longer available.",
    ],
)
def test_no_proposals_anywhere_is_false_when_another_plans_waits(reply):
    assert check(reply, ELSEWHERE) == REPLY_DENIES_PENDING_ELSEWHERE, reply


@pytest.mark.parametrize(
    "reply",
    [
        "There is no proposal awaiting approval for this workout.",
        "You don't have a proposal waiting for approval.",
        "Your proposal has expired.",
        "That proposal was rejected, so nothing is waiting.",
        "The proposal is no longer available.",
        "It never went through.",
        "That proposal is gone.",
    ],
)
def test_no_proposal_at_all_is_false_when_this_one_awaits_approval(reply):
    assert check(reply, awaiting_approval=True, explaining=True, recorded_changes=[]) == REPLY_DENIES_PENDING, reply


def test_a_proposal_that_really_lapsed_may_be_said_to_have_lapsed():
    # nothing awaits approval and nothing else does: expired, rejected or replaced is the truth
    assert check("That proposal has expired. Shall I make a new one?") is None
    assert check("It was rejected, so there is nothing pending.") is None


# --- 9. several proposals, each for its own plan ---


MANY = Lifecycle(
    plans_read=frozenset({5, 6}), approved_plans=frozenset({5}), others_awaiting=1
)


@pytest.mark.parametrize(
    "reply",
    ["Plan 5 has been updated.", "Workout 5 is saved and applied.", "Your plan 5 changes are applied."],
)
def test_the_plan_an_approval_saved_may_be_called_updated(reply):
    assert check(reply, MANY) is None, reply


@pytest.mark.parametrize(
    "reply",
    [
        "Plan 6 has been updated.",
        "Workout 6 is saved and applied.",
        "Plans 5 and 6 have been updated.",
        "Your plan 6 changes are applied.",
    ],
)
def test_an_approval_of_one_plan_backs_nothing_said_of_another(reply):
    """With several plans, plan 5 was approved and plan 6's revision still awaits approval: the
    reply named plan 6, which no approval saved."""
    assert check(reply, MANY) == REPLY_CLAIMS_APPLIED, reply


def test_a_plan_the_turn_did_not_read_is_never_called_saved():
    assert check("Plan 9 is saved for Friday.", Lifecycle(plans_read=frozenset({5}))) == REPLY_CLAIMS_APPLIED
    assert check("Plan 5 is saved for Friday.", Lifecycle(plans_read=frozenset({5}))) is None


# --- 10. paraphrases that use none of the phrases the older patterns knew ---


@pytest.mark.parametrize(
    "reply",
    [
        "The change went through.",
        "It's now on your calendar for Saturday.",
        "Your workout has been added to your schedule.",
        "That is now part of your plan.",
        "Everything is in effect for Saturday.",
        "The update is live.",
        "I've put it on your calendar.",
        "I have added it to your schedule for Saturday.",
        "I've pencilled it into your week.",
    ],
)
def test_paraphrases_of_saved_are_held_to_the_records_too(reply):
    assert check(reply, Lifecycle(plans_read=frozenset({5})), awaiting_approval=True, explaining=True, recorded_changes=[]) in (
        REPLY_CLAIMS_APPLIED,
        REPLY_CLAIMS_CHANGE,
    ), reply
    assert check(reply, proposed=True) in (REPLY_CLAIMS_APPLIED, REPLY_CLAIMS_CHANGE), reply


@pytest.mark.parametrize(
    "reply",
    [
        "That proposal lapsed.",
        "The proposal timed out.",
        "It was discarded.",
        "The workout version was withdrawn.",
        "The proposal doesn't exist any more.",
        "It never got made.",
    ],
)
def test_paraphrases_of_there_is_no_proposal_are_held_to_the_records(reply):
    assert check(reply, awaiting_approval=True, explaining=True, recorded_changes=[]) == REPLY_DENIES_PENDING, reply


@pytest.mark.parametrize(
    "reply",
    [
        "Your workout is unchanged: the change has not been saved and still needs your approval.",
        "Once you approve it, the change will be saved.",
        "If you approve it, it is saved.",
        "It will go through when you approve it.",
        "Nothing has been saved yet.",
        "Your plan is not updated until you approve.",
        "It isn't saved yet.",
    ],
)
def test_sentences_that_say_it_is_not_done_are_not_claims_that_it_is(reply):
    assert check(reply, Lifecycle(plans_read=frozenset({5})), awaiting_approval=True, explaining=True, recorded_changes=[]) is None, reply


def test_an_ordinary_reply_about_a_named_workout_passes():
    for reply in (
        'Your "Core & Abs Focus" workout is for Monday, 26 October, with Bird Dog and Band Pallof Press.',
        "Core & Abs Focus has three main exercises and takes about 21 minutes.",
        "I'd suggest keeping Core & Abs Focus as it is this week.",
        "Would you like me to propose a harder version of your Core & Abs Focus workout?",
    ):
        assert check(reply, Lifecycle(plans_read=frozenset({5}))) is None, reply
