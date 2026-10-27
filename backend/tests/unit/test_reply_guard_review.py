"""The reply guard against an adversarial review (Phase 2.7).

An independent review ran about 750 replies through reply_problem() under the five fact sets a turn
can be in (a proposal made; nothing in play; a proposal awaiting approval, explained or not; a proposal
refused; a plan approved), looking for the replies a model could plausibly write that are FALSE and pass
(a lie reaching the user), and the ones that are TRUE and are refused (an unnecessary, paid retry). What
held: quote styles, "&" and parentheses, apostrophes and digits in names, hedges at the start of a
sentence, plan ids. What did not is below, each as the exact reply and the facts it was written under.

Not fixed on purpose, and why (each is pinned by an older test or a live incident, and costs a retry,
never a false claim): "I've created / set / added ... your workout" after a proposal is refused as a
change claim; "Done! ..." is a claim (Done and All set are completions with nothing said of what);
"I added Bird Dog because it needs no bench" about a pending card is refused as a change the record does
not show (the live B5 reply said "I've updated your workout so nothing needs a bench" of a card it had
not changed, in the same words); an unsupported statement such as "I proposed a harder version earlier;
it's awaiting your approval" remains a claim, but the same statement is truthful and accepted when a
current pending record supports the harder version (the 2026-10-17 live reply had no such evidence beside
an unchanged card); "Your profile has been updated since March" is a claim that data changed.

No model, no database: scripted words under given facts.
"""

import pytest

from app.agent.graph import COACH_INSTRUCTIONS
from app.agent.policy import pending_descriptors
from app.agent.trust import (
    REPLY_CLAIMS_APPLIED,
    REPLY_CLAIMS_APPROVAL,
    REPLY_CLAIMS_CHANGE,
    REPLY_CLAIMS_CREATION,
    REPLY_CLAIMS_NEW_PROPOSAL,
    REPLY_CLAIMS_PROPOSAL,
    REPLY_CLAIMS_UNRECORDED_CHANGE,
    REPLY_DENIES_PENDING,
    REPLY_PRESENTS_REFUSED,
    Lifecycle,
    reply_problem,
)
from app.ai import ToolCall, ToolResult

TOOLS = ("propose_workout_plan", "get_pending_proposal")
PLAN = "Core & Abs Focus"
READ = Lifecycle(plans_read=frozenset({5}))
REFUSED = Lifecycle(refused=True)
APPROVED = Lifecycle(plans_read=frozenset({5}), approved_plans=frozenset({5}))
ANY_LIE = (
    REPLY_CLAIMS_APPLIED,
    REPLY_CLAIMS_CHANGE,
    REPLY_CLAIMS_APPROVAL,
    REPLY_CLAIMS_CREATION,
    REPLY_CLAIMS_PROPOSAL,
    REPLY_CLAIMS_NEW_PROPOSAL,
    REPLY_CLAIMS_UNRECORDED_CHANGE,
    REPLY_PRESENTS_REFUSED,
    REPLY_DENIES_PENDING,
)


def check(reply, lifecycle=None, *, names=(PLAN,), **facts):
    return reply_problem(
        reply,
        COACH_INSTRUCTIONS,
        TOOLS,
        lifecycle=lifecycle if lifecycle is not None else Lifecycle(),
        workout_names=names,
        **facts,
    )


def record(name="Core & Abs Focus (Harder)", before="3 sets of 12 reps, 90 s rest", after="4 sets of 12 reps, 90 s rest"):
    output = {
        "name": name,
        "coverage": {"complete": True},
        "revision": {"kind": "ADJUST", "replaces_plan_id": 5, "replaces_plan_name": PLAN},
        "changes": {"added": [], "removed": [], "changed": [{"exercise_name": "Bird Dog", "before": before, "after": after}]},
    }
    return [ToolResult(ToolCall(name="get_pending_proposal", arguments={}), {"output": output})]


# --- false negatives: a lie that passed ---


@pytest.mark.parametrize(
    "reply",
    [
        "Your **Core & Abs Focus** workout has been saved.",
        "Your *Core & Abs Focus* workout has been saved.",
        "'Core & Abs Focus' is now saved for Friday.",
        "I have adjusted your _Core & Abs Focus_ workout to 20 kg.",
        "Your __Core & Abs Focus__ workout has been updated.",
        "Your workout is **saved** for Friday.",
        "I've **saved** your workout.",
        "I've **approved** it.",
        "**All set!**",
        "Your `Core & Abs Focus` workout has been saved.",
    ],
)
def test_markdown_around_a_name_or_a_verb_hides_nothing(reply):
    """Gemini bolds routinely and the instructions never forbid it."""
    assert check(reply, proposed=True) in ANY_LIE, reply


@pytest.mark.parametrize(
    "reply",
    [
        "Your workout has been saved, so you can start whenever you're ready.",
        "Your workout has been saved and will appear in your schedule on Friday.",
        "Your workout is saved, not pending.",
        "Your plan is saved, which means you can train on Friday.",
    ],
)
def test_a_hedge_after_a_claim_does_not_unsay_it(reply):
    assert check(reply, proposed=True) == REPLY_CLAIMS_APPLIED, reply


@pytest.mark.parametrize(
    "reply",
    [
        "Once you approve it, your workout will be saved.",
        "Your workout is saved if you approve it.",
        "It is saved only once you approve it.",
        "Approve it and your workout is saved.",
        "Your workout will not be saved until you approve it.",
        "No changes were made to your plan.",
        "No changes have been made to your saved workout.",
        "None of your plans were changed.",
    ],
)
def test_a_hedge_before_a_claim_or_a_condition_after_it_still_says_nothing_was_done(reply):
    assert check(reply, READ, awaiting_approval=True, explaining=True, recorded_changes=[]) is None, reply


@pytest.mark.parametrize(
    "reply",
    [
        "Your workout for Friday has been saved.",
        "Your workout's been updated.",
        "Your plan's been saved.",
        "Your plan's now saved.",
        "I've saved it for you.",
        "I've gone ahead and saved your workout.",
        "I've confirmed it.",
        "I've scheduled it for Friday.",
        "Your workout is now set for Friday.",
        "Your workout is now live.",
        "Your plan is on your calendar.",
        "Your workout has been pushed to Saturday.",
        "Saved!",
        "Locked in!",
        "All set, done! Your changes are in.",
    ],
)
def test_more_shapes_of_saved_are_held_to_the_records_after_a_proposal(reply):
    assert check(reply, proposed=True) in ANY_LIE, reply


@pytest.mark.parametrize(
    "reply",
    [
        "I've approved this for you.",
        "I've gone ahead and approved it.",
        "I approved that.",
        "I've approved Core & Abs Focus for you.",
    ],
)
def test_the_coach_never_approved_anything_in_any_wording(reply):
    assert check(reply, proposed=True) == REPLY_CLAIMS_APPROVAL, reply
    assert check(reply) == REPLY_CLAIMS_APPROVAL, reply


@pytest.mark.parametrize(
    "reply",
    [
        "I've moved it to Saturday.",
        "I've rescheduled it for Saturday.",
        "I've logged it.",
        "I've started your workout session.",
        "I've saved it for you.",
    ],
)
def test_the_coach_changed_nothing_when_no_proposal_was_made(reply):
    assert check(reply) == REPLY_CLAIMS_CHANGE, reply


@pytest.mark.parametrize(
    "reply",
    [
        "I swapped the squats for lunges.",
        "I removed the squats.",
        "I made it harder.",
        "I shortened it to 30 minutes.",
        "I changed the day to Saturday.",
        "The squats were replaced with lunges.",
        "I replaced the bench press.",
    ],
)
def test_a_change_said_in_the_simple_past_is_a_claim_when_nothing_was_proposed(reply):
    # nothing in play, after a refusal, and with a proposal waiting that the user did not ask about
    assert check(reply) in ANY_LIE, reply
    assert check(reply, REFUSED) in ANY_LIE, reply
    assert check(reply, awaiting_approval=True) in ANY_LIE, reply


@pytest.mark.parametrize("reply", ["I made it harder.", "I took out the burpees.", "I put in a rest day."])
def test_the_same_in_the_words_that_explain_a_pending_proposal_is_refused_when_the_record_shows_no_change(
    reply,
):
    assert check(reply, awaiting_approval=True, explaining=True, recorded_changes=()) in ANY_LIE, reply


@pytest.mark.parametrize(
    "reply",
    [
        "You have no proposals at the moment.",
        "There's nothing for you to approve.",
        "No workout is awaiting approval.",
        "I couldn't find a proposal awaiting your approval.",
        "Nothing has been proposed yet.",
        "No proposal awaits your approval.",
        "There are no proposals.",
        "I don't see any proposal for you.",
    ],
)
def test_more_ways_to_say_there_is_no_proposal_are_false_when_one_waits(reply):
    problem = check(reply, awaiting_approval=True, explaining=True, recorded_changes=[])

    assert problem == REPLY_DENIES_PENDING, reply


@pytest.mark.parametrize(
    "reply",
    [
        "Your workout is now harder.",
        "I increased the sets to 4 for you.",
        "Press approve and it's yours.",
        "It's ready for your approval.",
        "Check the app for the new version.",
        "Click confirm to save it.",
    ],
)
def test_after_a_refused_proposal_none_of_these_presents_a_workout(reply):
    assert check(reply, REFUSED) in ANY_LIE, reply


@pytest.mark.parametrize(
    ("name", "reply"),
    [
        ("Inferno", "Inferno is now saved for Friday."),
        ("Inferno", "I saved Inferno for you."),
        ("Tabata", "Tabata has been updated."),
        ("Café Cardio", "Café Cardio is now saved for Friday."),
        ("Upper Body Strength & Power Day (Week 3 of the 12 week programme)", "Upper Body Strength & Power Day is saved for Friday."),
        ("Mon–Wed Strength (Week 2: heavy singles and doubles, then back-off sets)", "Mon–Wed Strength is saved for Friday."),
    ],
)
def test_one_word_unicode_and_long_names_are_read_as_names(name, reply):
    assert check(reply, proposed=True, names=(name,)) in ANY_LIE, reply


# --- false positives: a truth that was refused ---


@pytest.mark.parametrize(
    "reply",
    [
        "Nothing has been saved yet, and your proposal is awaiting your approval.",
        "I haven't changed your saved plan, and the proposal is awaiting your approval.",
        "You haven't approved it yet, so it's still pending your approval.",
        "I don't want to rush you, but the proposal is still waiting for your approval.",
        "There is nothing saved, but the proposal is pending.",
    ],
)
@pytest.mark.parametrize("explaining", [True, False])
def test_a_negation_beside_the_truth_is_not_a_denial(reply, explaining):
    """"Nothing" and "awaiting your approval" in one sentence, across a comma, is what a truthful reply says
    most naturally."""
    problem = check(reply, awaiting_approval=True, explaining=explaining, recorded_changes=[])

    assert problem is None, reply


@pytest.mark.parametrize(
    "reply",
    [
        "The harder version awaits your approval.",
        "The harder version waits for your approval.",
        "The harder version requires your approval.",
        "The harder version is ready for your approval.",
        "The harder version is only a proposal.",
        "The updated workout is below and awaits your approval.",
        "The harder version is not saved yet.",
        "The harder version hasn't been saved yet.",
    ],
)
def test_more_words_for_a_proposal_that_waits_are_a_reference_to_it(reply):
    seen = record()

    problem = check(
        reply,
        awaiting_approval=True,
        explaining=True,
        recorded_changes=[],
        pending_support=pending_descriptors(seen),
    )

    assert problem is None, reply


@pytest.mark.parametrize(
    "reply",
    [
        "Would you like me to make a new proposal for tomorrow?",
        "I can put together a new proposal if you'd like.",
        "If you'd like, I can propose a lighter workout and you can approve it in Formiq.",
        "I can't approve it for you; you approve proposals in the app.",
        "Formiq refused my proposal because it would leave the workout unchanged.",
        "The old proposal expired.",
        "Do you want me to try a different proposal?",
    ],
)
def test_ordinary_talk_of_proposals_is_no_presentation_of_one(reply):
    assert check(reply) is None, reply


def test_a_past_proposal_is_no_presentation_of_one():
    assert check("Your approved proposal is now saved as your plan for Friday.", APPROVED) is None


@pytest.mark.parametrize(
    "reply",
    [
        "Let me know when you're ready to try a different day.",
        "Tell me when you're ready and I'll try 40 minutes.",
        "Here are two options: Saturday or Sunday.",
        "Could you confirm it's for Friday?",
        "Which of the options below do you prefer?",
        "I couldn't change it: Formiq refused. Which day would you like?",
        "I changed nothing in your saved plan.",
    ],
)
def test_after_a_refused_proposal_asking_and_offering_choices_are_not_presenting(reply):
    assert check(reply, REFUSED) is None, reply


def test_a_lie_after_a_refusal_in_the_same_words_is_still_a_lie():
    assert check("Here is the updated workout.", REFUSED) is not None
    assert check("Review it and apply it when ready.", REFUSED) is not None


def test_the_saved_plan_may_be_called_current_beside_a_proposal_that_waits():
    reply = "Your current Friday workout is saved for Friday; the lighter version I've proposed is waiting for your approval."

    assert check(reply, READ, proposed=True) is None
    # but a workout that is not called the current one is the proposal's to be called saved
    assert check("Your Friday workout is saved for Friday.", READ, proposed=True) == REPLY_CLAIMS_APPLIED


@pytest.mark.parametrize(
    "reply",
    [
        "The workout is scheduled for Friday and awaits your approval.",
        "I've added a warm-up and a cool-down to your workout.",
        "I have added a short warm-up and a cool-down to your workout, and it awaits your approval.",
    ],
)
def test_describing_the_proposal_just_made_is_not_a_claim(reply):
    assert check(reply, proposed=True) is None, reply


def test_a_scheduled_that_does_not_say_it_awaits_approval_is_still_refused():
    assert check("The workout is scheduled for Friday.", proposed=True) == REPLY_CLAIMS_APPLIED


@pytest.mark.parametrize(
    ("record_name", "reply"),
    [
        ("Bicycle Crunch", "I added bicycle crunches to work your core."),
        ("Incline Push-Up", "I added incline push-ups."),
        ("Walking Lunge", "I added walking lunges for your legs."),
        ("Box Jump", "I added box jumps."),
    ],
)
def test_the_plural_of_a_recorded_exercise_is_the_exercise(record_name, reply):
    """"crunches" is "crunch" and "ups" is "up": the comparison of what the proposal records with what the
    reply names stems both the same way."""
    problem = check(reply, awaiting_approval=True, explaining=True, recorded_changes=[record_name])

    assert problem is None, reply


@pytest.mark.parametrize(
    "reply",
    [
        "There's no pending proposal for Friday.",
        "No proposal is pending for Monday's session.",
        "There is no proposal awaiting approval for today.",
        "No proposal is waiting for your Saturday session.",
    ],
)
def test_none_for_a_named_day_is_about_this_workout_not_the_user(reply):
    assert check(reply, Lifecycle(others_awaiting=1)) is None, reply


def test_none_anywhere_is_still_false_when_another_plans_proposal_waits():
    for reply in ("You have no proposals awaiting approval.", "There's nothing pending."):
        assert check(reply, Lifecycle(others_awaiting=1)) is not None, reply


# --- ordinary replies that use the words of a change without claiming one ---


@pytest.mark.parametrize(
    "reply",
    [
        "Progressive overload means gradually increasing the weight or reps over time.",
        "I changed my approach: let's focus on form first.",
        "I removed the guesswork: just do 3 sets of 10.",
        "I updated the way I explain this to keep it simple.",
        "I swapped notes with my colleagues on this: most coaches say 8 to 12 reps for size.",
        "I added a note about warming up: five minutes of light cardio helps.",
        "I made it simple: three exercises, three sets each.",
        "I shortened the explanation, but ask me if you want more detail.",
        "Your last session was on Monday: you completed 3 of 4 exercises.",
        "Your plan for today is Core & Abs Focus with Bird Dog and Band Pallof Press.",
        "Your saved workout for Friday has 5 exercises and takes about 21 minutes.",
        "I can adjust the sets if you'd like. How many would you prefer?",
        "That plan was scheduled for yesterday, so it is overdue.",
    ],
)
def test_the_words_of_a_change_in_an_ordinary_reply_are_no_claim_of_one(reply):
    """A claim is the coach saying it changed THE WORKOUT (its exercises, sets, day ...): "I removed the
    guesswork" and "I shortened the explanation" are the coach talking about its own words."""
    assert check(reply, READ) is None, reply
