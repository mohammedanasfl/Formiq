"""Tests for the recovery rules (app.guidance.recovery): rest windows, discomfort,
warning signs and sleep. Pure functions: no database, no clock, no model."""

import math
import re
from datetime import datetime, timedelta, timezone

import pytest

from app.guidance.recovery import (
    AREA_MUSCLES,
    REST_HOURS,
    SORE_REST_HOURS,
    WARNING_SIGN_NAMES,
    Discomfort,
    MuscleStatus,
    SafetyStatus,
    TrainedMuscle,
    discomfort_notices,
    flag_for_professional,
    general_recovery_items,
    muscle_recovery,
    safety_status,
    sleep_item,
    urgent_care_notice,
    withholds_guidance,
)
from app.guidance.sources import SOURCES, SourceId
from app.schemas.exercise import MuscleRole
from app.schemas.recovery_summary import BodyArea, DiscomfortKind, WarningSign

PRIMARY = MuscleRole.PRIMARY
SECONDARY = MuscleRole.SECONDARY
SORENESS = DiscomfortKind.SORENESS
PAIN = DiscomfortKind.PAIN
KNOWN_INJURY = DiscomfortKind.KNOWN_INJURY
DONE = datetime(2026, 10, 14, 18, 30, tzinfo=timezone.utc)

# The muscle groups seeded in the catalog (migrations b84c61ea69bf and 620eafb9c204).
SEEDED_MUSCLE_GROUPS = [
    "Chest",
    "Upper Back",
    "Lats",
    "Lower Back",
    "Shoulders",
    "Front Deltoid",
    "Rear Deltoid",
    "Biceps",
    "Triceps",
    "Forearms",
    "Core",
    "Obliques",
    "Glutes",
    "Quadriceps",
    "Hamstrings",
    "Calves",
    "Abductors",
    "Adductors",
    "Neck",
]


def trained(*pairs):
    return [TrainedMuscle(muscle, role) for muscle, role in pairs]


def by_muscle(recoveries):
    return {recovery.muscle: recovery for recovery in recoveries}


# rest windows


def test_a_primary_muscle_rests_48_hours_from_completion():
    [recovery] = muscle_recovery(trained(("Quadriceps", PRIMARY)), [], DONE)
    assert recovery.muscle == "Quadriceps"
    assert recovery.role is PRIMARY
    assert recovery.status is MuscleStatus.REST
    assert recovery.rest_hours == REST_HOURS == 48
    assert recovery.rest_until == DONE + timedelta(hours=48)
    assert recovery.rest_until.tzinfo is timezone.utc
    assert "48 hours" in recovery.reasons[0]
    assert recovery.source_ids == (SourceId.ACSM_POSITION_2011,)


def test_a_secondary_only_muscle_is_also_worked_with_no_window():
    [recovery] = muscle_recovery(trained(("Triceps", SECONDARY)), [], DONE)
    assert recovery.status is MuscleStatus.ALSO_WORKED
    assert recovery.role is SECONDARY
    assert recovery.rest_hours is None
    assert recovery.rest_until is None
    assert "no rest window" in recovery.reasons[0]


@pytest.mark.parametrize("order", [(PRIMARY, SECONDARY), (SECONDARY, PRIMARY)])
def test_a_muscle_is_primary_if_it_is_primary_in_any_counted_exercise(order):
    recoveries = muscle_recovery(trained(*[("Chest", role) for role in order]), [], DONE)
    assert len(recoveries) == 1
    assert recoveries[0].role is PRIMARY
    assert recoveries[0].status is MuscleStatus.REST


def test_only_the_muscles_it_is_given_get_a_window():
    # warm-up and cool-down exercises are left out by the caller: nothing counted, nothing rests
    assert muscle_recovery([], [], DONE) == ()


def test_the_trained_muscles_keep_the_order_they_were_given():
    muscles = ("Chest", "Quadriceps", "Biceps", "Lats")
    recoveries = muscle_recovery(trained(*[(name, PRIMARY) for name in muscles]), [], DONE)
    assert [recovery.muscle for recovery in recoveries] == list(muscles)


def test_the_completion_time_is_an_argument_and_a_naive_one_stays_naive():
    naive = datetime(2026, 10, 14, 18, 30)
    [recovery] = muscle_recovery(trained(("Chest", PRIMARY)), [], naive)
    assert recovery.rest_until == naive + timedelta(hours=48)
    assert recovery.rest_until.tzinfo is None


# soreness: 0-3 changes nothing, 4-6 gives 72 hours, 7 and above also lists the warning signs


@pytest.mark.parametrize("severity", [0, 1, 3])
def test_mild_soreness_changes_nothing(severity):
    sore = [Discomfort(BodyArea.FRONT_THIGHS, SORENESS, severity)]
    assert muscle_recovery(trained(("Quadriceps", PRIMARY)), sore, DONE) == muscle_recovery(
        trained(("Quadriceps", PRIMARY)), [], DONE
    )
    assert safety_status([], sore) is SafetyStatus.OK
    assert discomfort_notices(sore) == ()


@pytest.mark.parametrize("severity", [4, 5, 6])
def test_moderate_soreness_gives_that_muscle_72_hours(severity):
    sore = [Discomfort(BodyArea.FRONT_THIGHS, SORENESS, severity)]
    recoveries = by_muscle(
        muscle_recovery(trained(("Quadriceps", PRIMARY), ("Chest", PRIMARY)), sore, DONE)
    )
    quadriceps = recoveries["Quadriceps"]
    assert quadriceps.status is MuscleStatus.REST
    assert quadriceps.rest_hours == SORE_REST_HOURS == 72
    assert quadriceps.rest_until == DONE + timedelta(hours=72)
    assert f"soreness of {severity} out of 10" in quadriceps.reasons[0]
    assert SourceId.CHEUNG_DOMS_2003 in quadriceps.source_ids
    # a muscle that is not sore keeps its 48 hours
    assert recoveries["Chest"].rest_hours == 48
    assert safety_status([], sore) is SafetyStatus.CAUTION
    assert discomfort_notices(sore) == ()


@pytest.mark.parametrize("severity", [7, 8, 10])
def test_severe_soreness_gives_72_hours_and_lists_the_warning_signs(severity):
    sore = [Discomfort(BodyArea.CHEST, SORENESS, severity)]
    [recovery] = muscle_recovery(trained(("Chest", PRIMARY)), sore, DONE)
    assert recovery.rest_hours == 72
    [notice] = discomfort_notices(sore)
    assert notice.code == "SEVERE_SORENESS"
    for name in WARNING_SIGN_NAMES.values():
        assert name in notice.text
    assert safety_status([], sore) is SafetyStatus.CAUTION


def test_the_soreness_boundaries_are_3_4_6_and_7():
    def hours(severity):
        sore = [Discomfort(BodyArea.CHEST, SORENESS, severity)]
        return muscle_recovery(trained(("Chest", PRIMARY)), sore, DONE)[0].rest_hours

    assert [hours(severity) for severity in (3, 4, 6, 7)] == [48, 72, 72, 72]
    notices = [
        bool(discomfort_notices([Discomfort(BodyArea.CHEST, SORENESS, severity)]))
        for severity in (3, 4, 6, 7)
    ]
    assert notices == [False, False, False, True]
    statuses = [
        safety_status([], [Discomfort(BodyArea.CHEST, SORENESS, severity)])
        for severity in (3, 4, 6, 7)
    ]
    assert statuses == [SafetyStatus.OK] + [SafetyStatus.CAUTION] * 3


def test_soreness_in_a_secondary_muscle_gives_it_a_window_too():
    sore = [Discomfort(BodyArea.ARMS, SORENESS, 5)]
    recoveries = by_muscle(muscle_recovery(trained(("Triceps", SECONDARY)), sore, DONE))
    assert recoveries["Triceps"].status is MuscleStatus.REST
    assert recoveries["Triceps"].role is SECONDARY
    assert recoveries["Triceps"].rest_hours == 72


def test_the_most_severe_soreness_of_a_muscle_counts():
    mixed = [
        Discomfort(BodyArea.KNEES, SORENESS, 3),
        Discomfort(BodyArea.FRONT_THIGHS, SORENESS, 5),
        Discomfort(BodyArea.KNEES, SORENESS, 2),
    ]
    recoveries = by_muscle(muscle_recovery(trained(("Quadriceps", PRIMARY)), mixed, DONE))
    assert recoveries["Quadriceps"].rest_hours == 72
    assert "soreness of 5 out of 10" in recoveries["Quadriceps"].reasons[0]


# pain and a known injury are for a professional: no rest timing, no return-to-training time


@pytest.mark.parametrize("kind", [PAIN, KNOWN_INJURY])
@pytest.mark.parametrize("severity", [0, 1, 5, 10])
def test_pain_or_a_known_injury_sends_the_muscle_to_a_professional(kind, severity):
    reported = [Discomfort(BodyArea.FRONT_THIGHS, kind, severity)]
    [recovery] = muscle_recovery(trained(("Quadriceps", PRIMARY)), reported, DONE)
    assert recovery.status is MuscleStatus.SEE_PROFESSIONAL
    assert recovery.rest_hours is None
    assert recovery.rest_until is None
    assert recovery.role is PRIMARY
    assert safety_status([], reported) is SafetyStatus.CAUTION


def test_a_muscle_sent_to_a_professional_is_given_no_return_to_training_time():
    reported = [
        Discomfort(BodyArea.KNEES, PAIN, 6),
        Discomfort(BodyArea.ELBOWS, KNOWN_INJURY, 2),
    ]
    recoveries = muscle_recovery(trained(("Quadriceps", PRIMARY)), reported, DONE)
    texts = [text for recovery in recoveries for text in recovery.reasons]
    texts += [notice.text for notice in discomfort_notices(reported)]
    assert texts
    for text in texts:
        assert not re.search(r"\d", text), text
        assert not re.search(r"\b(hours?|days?|weeks?|months?|minutes?)\b", text, re.I), text
    for recovery in recoveries:
        assert recovery.rest_hours is None and recovery.rest_until is None
        assert "doctor or physiotherapist" in " ".join(recovery.reasons)
    [notice] = discomfort_notices(reported)
    assert notice.code == "PAIN_OR_INJURY"
    assert "Formiq gives no time to return to training" in notice.text


def test_pain_outranks_soreness_and_a_rest_window():
    reported = [
        Discomfort(BodyArea.FRONT_THIGHS, SORENESS, 9),
        Discomfort(BodyArea.KNEES, PAIN, 2),
    ]
    recoveries = by_muscle(muscle_recovery(trained(("Quadriceps", PRIMARY)), reported, DONE))
    assert recoveries["Quadriceps"].status is MuscleStatus.SEE_PROFESSIONAL
    assert recoveries["Quadriceps"].rest_until is None


def test_pain_in_a_joint_covers_the_muscles_that_move_it():
    reported = [Discomfort(BodyArea.KNEES, PAIN, 5)]
    recoveries = by_muscle(muscle_recovery(trained(("Quadriceps", PRIMARY)), reported, DONE))
    assert set(recoveries) == {"Quadriceps", "Hamstrings", "Calves"}
    assert {recovery.status for recovery in recoveries.values()} == {MuscleStatus.SEE_PROFESSIONAL}


# a reported area that was not trained still appears


def test_a_painful_area_that_was_not_trained_still_appears_for_a_professional():
    reported = [Discomfort(BodyArea.NECK, PAIN, 4)]
    recoveries = muscle_recovery(trained(("Chest", PRIMARY)), reported, DONE)
    assert [recovery.muscle for recovery in recoveries] == ["Chest", "Neck"]
    neck = recoveries[1]
    assert neck.status is MuscleStatus.SEE_PROFESSIONAL
    assert neck.role is None
    assert neck.rest_hours is None and neck.rest_until is None
    assert neck.reasons[0] == "Not trained in this workout."


def test_a_sore_area_that_was_not_trained_still_gets_its_window():
    reported = [Discomfort(BodyArea.CALVES, SORENESS, 5)]
    [recovery] = muscle_recovery([], reported, DONE)
    assert recovery.muscle == "Calves"
    assert recovery.role is None
    assert recovery.status is MuscleStatus.REST
    assert recovery.rest_hours == 72
    assert recovery.rest_until == DONE + timedelta(hours=72)
    assert recovery.reasons[0] == "Not trained in this workout."


def test_mild_soreness_in_an_area_that_was_not_trained_adds_nothing():
    reported = [Discomfort(BodyArea.CALVES, SORENESS, 3)]
    assert muscle_recovery([], reported, DONE) == ()


def test_reported_muscles_follow_the_trained_ones_in_the_order_reported():
    reported = [Discomfort(BodyArea.NECK, PAIN, 3), Discomfort(BodyArea.HIPS, PAIN, 3)]
    recoveries = muscle_recovery(trained(("Chest", PRIMARY), ("Glutes", PRIMARY)), reported, DONE)
    assert [recovery.muscle for recovery in recoveries] == [
        "Chest",
        "Glutes",
        "Neck",
        "Abductors",
        "Adductors",
    ]
    assert recoveries[1].role is PRIMARY
    assert recoveries[1].status is MuscleStatus.SEE_PROFESSIONAL


# warning signs


@pytest.mark.parametrize("sign", list(WarningSign))
def test_any_warning_sign_means_seek_medical_care(sign):
    assert safety_status([sign], []) is SafetyStatus.SEEK_MEDICAL_CARE
    # whatever else was reported
    reported = [Discomfort(BodyArea.CHEST, SORENESS, 0)]
    assert safety_status([sign], reported) is SafetyStatus.SEEK_MEDICAL_CARE
    assert withholds_guidance(SafetyStatus.SEEK_MEDICAL_CARE) is True


def test_every_warning_sign_has_a_name_for_the_user():
    assert set(WARNING_SIGN_NAMES) == set(WarningSign)


def test_safety_status_is_ok_without_warning_signs_or_discomfort():
    assert safety_status([], []) is SafetyStatus.OK
    assert safety_status(iter(()), iter(())) is SafetyStatus.OK
    assert withholds_guidance(SafetyStatus.OK) is False
    assert withholds_guidance(SafetyStatus.CAUTION) is False


def test_another_caution_makes_the_status_caution_but_never_overrides_a_warning_sign():
    assert safety_status([], [], other_cautions=True) is SafetyStatus.CAUTION
    assert (
        safety_status([WarningSign.DARK_URINE], [], other_cautions=True)
        is SafetyStatus.SEEK_MEDICAL_CARE
    )


def test_the_urgent_notice_names_only_the_reported_signs_and_withholds_the_rest():
    notice = urgent_care_notice([WarningSign.DARK_URINE, WarningSign.CHEST_PAIN])
    assert notice.code == "SEEK_MEDICAL_CARE"
    # named in the order of the list, not the order reported
    assert "You reported: chest pain, dark urine." in notice.text
    assert "seek medical care now" in notice.text
    assert "numbness" not in notice.text
    assert "no nutrition, hydration or recovery timing" in notice.text
    assert notice.source_ids == (SourceId.CDC_RHABDO, SourceId.ACSM_POSITION_2011)


# the area to muscle map


def test_every_body_area_maps_to_catalog_muscle_groups():
    assert set(AREA_MUSCLES) == set(BodyArea)
    assert len(BodyArea) == 16
    for area, muscles in AREA_MUSCLES.items():
        assert muscles, area
        assert len(set(muscles)) == len(muscles), area
        assert set(muscles) <= set(SEEDED_MUSCLE_GROUPS), (area, muscles)


def test_the_catalog_has_these_19_muscle_groups():
    assert len(SEEDED_MUSCLE_GROUPS) == len(set(SEEDED_MUSCLE_GROUPS)) == 19


def test_a_knee_stands_for_the_muscles_that_move_it():
    assert AREA_MUSCLES[BodyArea.KNEES] == ("Quadriceps", "Hamstrings", "Calves")
    assert AREA_MUSCLES[BodyArea.FRONT_THIGHS] == ("Quadriceps",)


# sleep


@pytest.mark.parametrize("hours", [0.5, 3, 6, 6.5, 6.9])
def test_self_reported_sleep_under_7_hours_gets_an_item(hours):
    item = sleep_item(hours)
    assert item is not None
    assert item.code == "SLEEP_BELOW_RECOMMENDED"
    assert item.source_ids == (SourceId.AASM_SLEEP_2015,)
    assert "self-reported, not measured" in item.text
    assert "7 or more hours" in item.text
    assert f"{hours:g} hours" in item.text


@pytest.mark.parametrize("hours", [7, 7.5, 8, 10, 16])
def test_sleep_that_meets_the_recommendation_gets_no_item(hours):
    assert sleep_item(hours) is None


@pytest.mark.parametrize("hours", [None, 0, -1, 16.5, 24, 100, math.nan, math.inf])
def test_sleep_that_is_missing_or_not_credible_is_ignored(hours):
    assert sleep_item(hours) is None


# a flagged note turns the muscles it covers over to a professional


NOTE_REASON = "A note on this workout mentions pain: see a doctor or physiotherapist."


def test_flagging_turns_the_named_muscles_to_a_professional_with_no_window():
    worked = trained(("Quadriceps", PRIMARY), ("Chest", PRIMARY), ("Triceps", SECONDARY))
    recoveries = muscle_recovery(worked, [], DONE)
    flagged = by_muscle(flag_for_professional(recoveries, ["Quadriceps", "Triceps"], NOTE_REASON))
    for name in ("Quadriceps", "Triceps"):
        assert flagged[name].status is MuscleStatus.SEE_PROFESSIONAL
        assert flagged[name].rest_hours is None and flagged[name].rest_until is None
        assert flagged[name].reasons[-1] == NOTE_REASON
    # the earlier reasons stay, the role is kept, and the sources are the entry's own
    original = by_muscle(recoveries)
    assert flagged["Quadriceps"].reasons[:-1] == original["Quadriceps"].reasons
    assert flagged["Quadriceps"].role is PRIMARY and flagged["Triceps"].role is SECONDARY
    assert flagged["Quadriceps"].source_ids == original["Quadriceps"].source_ids
    assert flagged["Triceps"].source_ids == original["Triceps"].source_ids


def test_flagging_leaves_the_other_muscles_and_the_order_as_they_were():
    worked = trained(("Quadriceps", PRIMARY), ("Chest", PRIMARY), ("Lats", PRIMARY))
    recoveries = muscle_recovery(worked, [], DONE)
    flagged = flag_for_professional(recoveries, ["Chest"], NOTE_REASON)
    assert [recovery.muscle for recovery in flagged] == ["Quadriceps", "Chest", "Lats"]
    assert flagged[0] == recoveries[0] and flagged[2] == recoveries[2]
    assert flagged[1] != recoveries[1]
    assert flagged[0].rest_hours == 48 and flagged[2].rest_until == DONE + timedelta(hours=48)


def test_flagging_adds_no_muscle_that_has_no_recovery():
    recoveries = muscle_recovery(trained(("Chest", PRIMARY)), [], DONE)
    assert flag_for_professional(recoveries, ["Neck", "Quadriceps"], NOTE_REASON) == recoveries
    assert flag_for_professional(recoveries, [], NOTE_REASON) == recoveries
    assert flag_for_professional((), ["Chest"], NOTE_REASON) == ()


def test_flagging_takes_any_iterable_and_returns_a_tuple_without_changing_its_input():
    recoveries = muscle_recovery(trained(("Chest", PRIMARY), ("Lats", PRIMARY)), [], DONE)
    snapshot = tuple(recoveries)
    flagged = flag_for_professional(iter(recoveries), (name for name in ["Lats"]), NOTE_REASON)
    assert isinstance(flagged, tuple)
    assert recoveries == snapshot
    assert by_muscle(flagged)["Lats"].status is MuscleStatus.SEE_PROFESSIONAL


def test_flagging_twice_adds_the_reason_once():
    recoveries = muscle_recovery(trained(("Chest", PRIMARY)), [], DONE)
    once = flag_for_professional(recoveries, ["Chest"], NOTE_REASON)
    twice = flag_for_professional(once, ["Chest"], NOTE_REASON)
    assert twice == once
    assert once[0].reasons.count(NOTE_REASON) == 1


def test_flagging_a_muscle_already_for_a_professional_keeps_its_reasons_and_adds_the_new_one():
    reported = [Discomfort(BodyArea.CHEST, PAIN, 3)]
    [pain] = muscle_recovery(trained(("Chest", PRIMARY)), reported, DONE)
    [flagged] = flag_for_professional([pain], ["Chest"], NOTE_REASON)
    assert flagged.status is MuscleStatus.SEE_PROFESSIONAL
    assert flagged.reasons == (*pain.reasons, NOTE_REASON)
    assert flagged.rest_hours is None and flagged.rest_until is None


def test_a_sore_muscle_that_is_flagged_loses_its_72_hour_window():
    sore = [Discomfort(BodyArea.CHEST, SORENESS, 5)]
    [recovery] = muscle_recovery(trained(("Chest", PRIMARY)), sore, DONE)
    assert recovery.rest_hours == 72
    [flagged] = flag_for_professional([recovery], ["Chest"], NOTE_REASON)
    assert flagged.status is MuscleStatus.SEE_PROFESSIONAL
    assert flagged.rest_hours is None and flagged.rest_until is None


# general guidance


def test_the_general_recovery_items_are_fixed_text_with_sources():
    items = general_recovery_items()
    assert [item.code for item in items] == ["GENTLE_MOVEMENT", "SPREAD_PROTEIN"]
    registered = {source.id for source in SOURCES}
    for item in items:
        assert item.source_ids and set(item.source_ids) <= registered
        assert not re.search(r"\d", item.text)
    assert general_recovery_items() == items


def test_every_source_the_recovery_rules_cite_is_registered():
    registered = {source.id for source in SOURCES}
    reported = [
        Discomfort(BodyArea.CHEST, SORENESS, 8),
        Discomfort(BodyArea.KNEES, PAIN, 3),
    ]
    cited = set()
    worked = trained(("Chest", PRIMARY), ("Biceps", SECONDARY))
    for recovery in muscle_recovery(worked, reported, DONE):
        cited.update(recovery.source_ids)
    for notice in discomfort_notices(reported):
        cited.update(notice.source_ids)
    cited.update(urgent_care_notice(list(WarningSign)).source_ids)
    assert cited and cited <= registered
