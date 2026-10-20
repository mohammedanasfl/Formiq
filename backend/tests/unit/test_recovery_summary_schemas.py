import json
from datetime import datetime, timezone
from typing import Literal, get_args, get_origin

import pytest
from pydantic import BaseModel, ValidationError

from app.guidance.foods import DietPattern, PreferenceStatus
from app.guidance.nutrition import GoalCategory
from app.guidance.recovery import MuscleStatus, SafetyStatus
from app.schemas import (
    Allergen,
    BodyArea,
    DiscomfortKind,
    DiscomfortReport,
    EstimateRange,
    Estimates,
    ExerciseStatus,
    FoodSuggestions,
    Guidance,
    MuscleRecoveryPlan,
    ProfileValuesUsed,
    RecoverySummaryRequest,
    RecoverySummaryResponse,
    SafetySummary,
    WarningSign,
)

COMPLETED_AT = datetime(2026, 10, 17, 10, 30, tzinfo=timezone.utc)
REST_UNTIL = datetime(2026, 10, 19, 10, 30, tzinfo=timezone.utc)

TOP_LEVEL_KEYS = [
    "session_id",
    "completed_at",
    "hours_since_completed",
    "safety",
    "calculated",
    "estimates",
    "guidance",
    "missing_data",
    "sources",
]

KNEE_PAIN = {"area": "KNEES", "kind": "PAIN", "severity": 5}


def distinct_reports(count):
    """count discomfort reports, each with its own (area, kind)."""
    pairs = [(area, kind) for kind in DiscomfortKind for area in BodyArea]
    return [{"area": area, "kind": kind, "severity": 3} for area, kind in pairs[:count]]


def rejected(model, data):
    """The errors of validating data, which must be rejected."""
    with pytest.raises(ValidationError) as caught:
        model.model_validate(data)
    return caught.value.errors()


# --- the request ---------------------------------------------------------------------


def test_request_accepts_an_empty_body():
    request = RecoverySummaryRequest.model_validate({})

    assert request.discomfort == []
    assert request.warning_signs == []
    assert request.avoid_allergens == []


def test_request_can_be_built_without_arguments():
    assert RecoverySummaryRequest() == RecoverySummaryRequest.model_validate({})


def test_request_instances_do_not_share_their_lists():
    first = RecoverySummaryRequest()
    second = RecoverySummaryRequest()

    first.discomfort.append(DiscomfortReport.model_validate(KNEE_PAIN))
    first.warning_signs.append(WarningSign.DARK_URINE)
    first.avoid_allergens.append(Allergen.MILK)

    assert second.discomfort == []
    assert second.warning_signs == []
    assert second.avoid_allergens == []


def test_request_accepts_a_full_body():
    request = RecoverySummaryRequest.model_validate(
        {
            "discomfort": [KNEE_PAIN],
            "warning_signs": ["DARK_URINE"],
            "avoid_allergens": ["PEANUTS", "MILK"],
        }
    )

    assert request.discomfort[0].area is BodyArea.KNEES
    assert request.discomfort[0].kind is DiscomfortKind.PAIN
    assert request.discomfort[0].severity == 5
    assert request.warning_signs == [WarningSign.DARK_URINE]
    assert request.avoid_allergens == [Allergen.PEANUTS, Allergen.MILK]


@pytest.mark.parametrize(
    "extra", ["user_id", "notes", "description", "message", "allergies", "fluid_ml"]
)
def test_request_rejects_unknown_fields(extra):
    errors = rejected(RecoverySummaryRequest, {extra: "anything"})

    assert [(error["loc"], error["type"]) for error in errors] == [((extra,), "extra_forbidden")]


@pytest.mark.parametrize("extra", ["notes", "description", "user_id", "text"])
def test_discomfort_report_rejects_unknown_fields(extra):
    errors = rejected(DiscomfortReport, {**KNEE_PAIN, extra: "my knee hurts"})

    assert [(error["loc"], error["type"]) for error in errors] == [((extra,), "extra_forbidden")]


def test_unknown_field_inside_a_discomfort_item_is_rejected_through_the_request():
    errors = rejected(RecoverySummaryRequest, {"discomfort": [{**KNEE_PAIN, "notes": "x"}]})

    assert [error["loc"] for error in errors] == [("discomfort", 0, "notes")]


def test_validation_errors_carry_a_location_message_and_type():
    errors = rejected(RecoverySummaryRequest, {"warning_signs": ["NOT_A_SIGN"], "extra": 1})

    assert errors
    for error in errors:
        assert error["loc"]
        assert error["msg"]
        assert error["type"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("area", "knees"),
        ("area", "Knees"),
        ("area", "HEAD"),
        ("area", ""),
        ("area", 1),
        ("area", None),
        ("kind", "pain"),
        ("kind", "ACHE"),
        ("kind", None),
    ],
)
def test_discomfort_report_rejects_values_that_are_not_enum_members(field, value):
    errors = rejected(DiscomfortReport, {**KNEE_PAIN, field: value})

    assert [error["loc"] for error in errors] == [(field,)]


@pytest.mark.parametrize("value", ["dark_urine", "Dark_Urine", "FEVER", "", 1, None])
def test_request_rejects_a_warning_sign_that_is_not_an_enum_member(value):
    errors = rejected(RecoverySummaryRequest, {"warning_signs": [value]})

    assert [error["loc"] for error in errors] == [("warning_signs", 0)]


@pytest.mark.parametrize("value", ["milk", "Milk", "GLUTEN", "", 1, None])
def test_request_rejects_an_allergen_that_is_not_an_enum_member(value):
    errors = rejected(RecoverySummaryRequest, {"avoid_allergens": [value]})

    assert [error["loc"] for error in errors] == [("avoid_allergens", 0)]


@pytest.mark.parametrize("severity", [0, 1, 5, 9, 10])
def test_severity_accepts_integers_from_0_to_10(severity):
    report = DiscomfortReport.model_validate({**KNEE_PAIN, "severity": severity})

    assert report.severity == severity


@pytest.mark.parametrize("severity", [-1, 11, 100, 5.5, 5.0, "5", "five", True, False, None])
def test_severity_rejects_anything_but_an_integer_from_0_to_10(severity):
    errors = rejected(DiscomfortReport, {**KNEE_PAIN, "severity": severity})

    assert [error["loc"] for error in errors] == [("severity",)]


def test_severity_is_required():
    errors = rejected(DiscomfortReport, {"area": "KNEES", "kind": "PAIN"})

    assert [(error["loc"], error["type"]) for error in errors] == [(("severity",), "missing")]


@pytest.mark.parametrize(
    ("raw", "accepted"),
    [
        ('{"area": "KNEES", "kind": "PAIN", "severity": 5}', True),
        ('{"area": "KNEES", "kind": "PAIN", "severity": 0}', True),
        ('{"area": "KNEES", "kind": "PAIN", "severity": "5"}', False),
        ('{"area": "KNEES", "kind": "PAIN", "severity": 5.5}', False),
        ('{"area": "KNEES", "kind": "PAIN", "severity": true}', False),
        ('{"area": "KNEES", "kind": "PAIN", "severity": 11}', False),
    ],
)
def test_severity_is_strict_when_the_body_is_parsed_from_json_too(raw, accepted):
    if accepted:
        assert DiscomfortReport.model_validate_json(raw).severity == json.loads(raw)["severity"]
    else:
        with pytest.raises(ValidationError):
            DiscomfortReport.model_validate_json(raw)


def test_request_rejects_a_duplicate_warning_sign():
    errors = rejected(RecoverySummaryRequest, {"warning_signs": ["DARK_URINE", "DARK_URINE"]})

    assert [error["loc"] for error in errors] == [("warning_signs",)]


def test_request_rejects_a_duplicate_allergen():
    errors = rejected(RecoverySummaryRequest, {"avoid_allergens": ["MILK", "SOY", "MILK"]})

    assert [error["loc"] for error in errors] == [("avoid_allergens",)]


def test_request_rejects_the_same_area_and_kind_twice_even_with_another_severity():
    errors = rejected(
        RecoverySummaryRequest,
        {"discomfort": [KNEE_PAIN, {**KNEE_PAIN, "severity": 9}]},
    )

    assert [error["loc"] for error in errors] == [("discomfort",)]


def test_request_accepts_one_area_with_different_kinds():
    request = RecoverySummaryRequest.model_validate(
        {
            "discomfort": [
                {"area": "KNEES", "kind": "SORENESS", "severity": 4},
                {"area": "KNEES", "kind": "PAIN", "severity": 2},
                {"area": "KNEES", "kind": "KNOWN_INJURY", "severity": 0},
            ]
        }
    )

    assert len(request.discomfort) == 3


def test_request_accepts_the_same_kind_in_different_areas():
    request = RecoverySummaryRequest.model_validate(
        {"discomfort": [KNEE_PAIN, {**KNEE_PAIN, "area": "HIPS"}]}
    )

    assert len(request.discomfort) == 2


def test_request_caps_discomfort_at_10_items():
    ten = distinct_reports(10)

    assert len(RecoverySummaryRequest.model_validate({"discomfort": ten}).discomfort) == 10

    errors = rejected(RecoverySummaryRequest, {"discomfort": distinct_reports(11)})

    assert [(error["loc"], error["type"]) for error in errors] == [(("discomfort",), "too_long")]


def test_request_accepts_every_warning_sign_and_every_allergen_once():
    request = RecoverySummaryRequest.model_validate(
        {
            "warning_signs": [sign.value for sign in WarningSign],
            "avoid_allergens": [allergen.value for allergen in Allergen],
        }
    )

    assert len(request.warning_signs) == 7
    assert len(request.avoid_allergens) == 9


def test_request_caps_warning_signs_and_allergens_at_the_number_of_values():
    # More items than there are values can only repeat one, and is cut off by the cap
    # before any duplicate is looked for.
    too_many_signs = [*(sign.value for sign in WarningSign), "DARK_URINE"]
    too_many_allergens = [*(allergen.value for allergen in Allergen), "MILK"]

    assert [
        (error["loc"], error["type"])
        for error in rejected(RecoverySummaryRequest, {"warning_signs": too_many_signs})
    ] == [(("warning_signs",), "too_long")]
    assert [
        (error["loc"], error["type"])
        for error in rejected(RecoverySummaryRequest, {"avoid_allergens": too_many_allergens})
    ] == [(("avoid_allergens",), "too_long")]


def test_request_caps_are_pinned_in_its_json_schema():
    properties = RecoverySummaryRequest.model_json_schema()["properties"]

    assert properties["discomfort"]["maxItems"] == 10
    assert properties["warning_signs"]["maxItems"] == 7
    assert properties["avoid_allergens"]["maxItems"] == 9


def test_request_lists_must_be_lists():
    for field in ("discomfort", "warning_signs", "avoid_allergens"):
        assert rejected(RecoverySummaryRequest, {field: "KNEES"})
        assert rejected(RecoverySummaryRequest, {field: None})


def leaf_types(annotation):
    """The types a field is made of once lists and unions are looked through."""
    args = get_args(annotation)
    if not args:
        return {annotation}
    leaves = set()
    for arg in args:
        leaves |= leaf_types(arg)
    return leaves


def test_request_has_no_field_that_could_carry_free_text():
    # Only enums, an int and the discomfort report are accepted: no str anywhere.
    accepted = {DiscomfortReport, int, BodyArea, DiscomfortKind, WarningSign, Allergen}
    for model in (RecoverySummaryRequest, DiscomfortReport):
        for name, field in model.model_fields.items():
            leaves = leaf_types(field.annotation)
            assert leaves <= accepted, f"{model.__name__}.{name}: {leaves}"
    assert set(RecoverySummaryRequest.model_fields) == {
        "discomfort",
        "warning_signs",
        "avoid_allergens",
    }
    assert set(DiscomfortReport.model_fields) == {"area", "kind", "severity"}


# --- the response --------------------------------------------------------------------


def estimate(low=18, high=29):
    return {
        "low": low,
        "high": high,
        "unit": "g",
        "basis": "0.25-0.40 g/kg x 72.0 kg recorded body weight",
        "applies_if": None,
        "assumptions": ["A healthy adult."],
        "source_ids": ["ISSN_PROTEIN_2017"],
    }


def note(code="HYDRATION_MEALS", text="Drink with meals and to thirst."):
    return {"code": code, "text": text, "source_ids": ["ACSM_FLUID_2007"]}


def minimal_response():
    return {
        "session_id": 7,
        "completed_at": COMPLETED_AT,
        "hours_since_completed": 1.5,
        "safety": {"status": "OK", "notices": []},
        "calculated": {
            "duration_minutes": None,
            "duration_plausible": False,
            "exercises": [],
            "completed_sets": 0,
            "total_reps": 0,
            "volume_kg": None,
            "muscles_trained": [],
            "profile_values_used": None,
        },
        "estimates": {},
        "guidance": {},
        "missing_data": [],
        "sources": [],
    }


def full_response():
    return {
        "session_id": 7,
        "completed_at": COMPLETED_AT,
        "hours_since_completed": 1.5,
        "safety": {
            "status": "CAUTION",
            "notices": [
                {
                    "code": "PAIN_OR_INJURY",
                    "message": "You reported pain or a known injury.",
                    "source_ids": [],
                }
            ],
        },
        "calculated": {
            "duration_minutes": 55.0,
            "duration_plausible": True,
            "exercises": [
                {
                    "session_exercise_id": 11,
                    "exercise_id": 3,
                    "name": "Barbell Squat",
                    "section": "MAIN_WORKOUT",
                    "status": "TRAINED",
                    "sets_logged": 3,
                    "completed_sets": 3,
                    "total_reps": 24,
                    "volume_kg": 1920.0,
                    "average_rpe": 7.5,
                },
                {
                    "session_exercise_id": 12,
                    "exercise_id": 4,
                    "name": "Plank",
                    "section": "COOL_DOWN",
                    "status": "LOGGED_WITHOUT_SETS",
                    "sets_logged": 0,
                    "completed_sets": 0,
                    "total_reps": 0,
                    "volume_kg": None,
                    "average_rpe": None,
                },
                {
                    "session_exercise_id": 13,
                    "exercise_id": 5,
                    "name": "Bench Press",
                    "section": "MAIN_WORKOUT",
                    "status": "SKIPPED",
                    "sets_logged": 2,
                    "completed_sets": 0,
                    "total_reps": 0,
                    "volume_kg": None,
                    "average_rpe": None,
                },
            ],
            "completed_sets": 3,
            "total_reps": 24,
            "volume_kg": 1920.0,
            "muscles_trained": [
                {
                    "muscle": "Quadriceps",
                    "role": "PRIMARY",
                    "completed_sets": 3,
                    "exercises": ["Barbell Squat"],
                }
            ],
            "profile_values_used": {
                "weight_kg": 72.0,
                "age": 29,
                "bmi": 23.5,
                "goal": "build_muscle",
                "goal_category": "BUILD_MUSCLE",
                "dietary_preference": "vegetarian",
                "sleep_hours": 6.0,
            },
        },
        "estimates": {
            "post_workout_protein_g": estimate(18, 29),
            "daily_protein_g": estimate(115, 144),
            "daily_carbohydrate_g": estimate(216, 360),
            "rapid_refuel_carbohydrate_g_per_hour": {
                **estimate(72, 86),
                "applies_if": "another demanding session within 8 hours",
            },
            "active_energy_kcal": estimate(160, 330),
        },
        "guidance": {
            "post_workout_carbohydrate": [note("CARBOHYDRATE_WITH_PROTEIN")],
            "hydration": [note("HYDRATION_MEALS"), note("HYDRATION_URINE_CHECK")],
            "fluid_loss_measured": False,
            "sleep": note("SLEEP_BELOW_RECOMMENDED"),
            "recovery": {
                "muscles": [
                    {
                        "muscle": "Quadriceps",
                        "role": "PRIMARY",
                        "status": "REST",
                        "rest_hours": 48,
                        "rest_until": REST_UNTIL,
                        "reasons": ["Trained as a main muscle in this workout."],
                        "source_ids": ["ACSM_POSITION_2011"],
                    },
                    {
                        "muscle": "Glutes",
                        "role": "SECONDARY",
                        "status": "ALSO_WORKED",
                        "rest_hours": None,
                        "rest_until": None,
                        "reasons": ["Worked as a supporting muscle only."],
                        "source_ids": [],
                    },
                    {
                        "muscle": "Hamstrings",
                        "role": None,
                        "status": "SEE_PROFESSIONAL",
                        "rest_hours": None,
                        "rest_until": None,
                        "reasons": ["Not trained in this workout.", "Pain was reported here."],
                        "source_ids": [],
                    },
                ],
                "general": [note("GENTLE_MOVEMENT"), note("SPREAD_PROTEIN")],
            },
            "food_suggestions": {
                "preference_status": "APPLIED",
                "dietary_pattern": "VEGETARIAN",
                "allergens_excluded": ["PEANUTS", "MILK"],
                "items": [
                    {
                        "name": "Lentils, cooked",
                        "serving": "1 cup (198 g)",
                        "protein_g": 17.9,
                        "carbohydrate_g": 39.9,
                        "suits": ["VEGAN", "VEGETARIAN", "EGGETARIAN", "PESCATARIAN"],
                        "contains": [],
                        "allergens": [],
                        "source_id": "USDA_FDC",
                    }
                ],
                "caveats": ["Check labels: allergies are not recorded."],
            },
        },
        "missing_data": [{"field": "profile.sleep_hours", "effect": "No sleep note is given."}],
        "sources": [
            {
                "id": "ISSN_PROTEIN_2017",
                "citation": "Jager R, et al. J Int Soc Sports Nutr. 2017;14:20.",
                "url": "https://doi.org/10.1186/s12970-017-0177-8",
            }
        ],
    }


def test_response_has_exactly_the_documented_top_level_keys():
    for data in (minimal_response(), full_response()):
        dumped = RecoverySummaryResponse.model_validate(data).model_dump(mode="json")

        assert list(dumped) == TOP_LEVEL_KEYS


def test_minimal_response_has_empty_estimates_and_guidance():
    dumped = RecoverySummaryResponse.model_validate(minimal_response()).model_dump(mode="json")

    assert dumped["estimates"] == {
        "post_workout_protein_g": None,
        "daily_protein_g": None,
        "daily_carbohydrate_g": None,
        "rapid_refuel_carbohydrate_g_per_hour": None,
        "active_energy_kcal": None,
    }
    assert dumped["guidance"] == {
        "post_workout_carbohydrate": [],
        "hydration": [],
        "fluid_loss_measured": False,
        "sleep": None,
        "recovery": None,
        "food_suggestions": None,
    }
    assert dumped["calculated"]["profile_values_used"] is None


def test_full_response_serialises_to_json_with_dates_in_iso_format():
    response = RecoverySummaryResponse.model_validate(full_response())

    dumped = response.model_dump(mode="json")
    json.dumps(dumped)

    assert isinstance(dumped["completed_at"], str)
    assert datetime.fromisoformat(dumped["completed_at"]) == COMPLETED_AT
    window = dumped["guidance"]["recovery"]["muscles"][0]["rest_until"]
    assert isinstance(window, str)
    assert datetime.fromisoformat(window) == REST_UNTIL


def test_full_response_keeps_amounts_as_numbers_not_strings():
    dumped = RecoverySummaryResponse.model_validate(full_response()).model_dump(mode="json")

    item = dumped["guidance"]["food_suggestions"]["items"][0]
    assert item["protein_g"] == 17.9
    assert item["carbohydrate_g"] == 39.9
    assert dumped["estimates"]["active_energy_kcal"]["low"] == 160
    assert dumped["calculated"]["volume_kg"] == 1920.0
    assert dumped["hours_since_completed"] == 1.5


def test_full_response_keeps_all_five_estimates_and_the_conditional_one_says_when():
    dumped = RecoverySummaryResponse.model_validate(full_response()).model_dump(mode="json")

    assert all(dumped["estimates"][name] is not None for name in dumped["estimates"])
    refuel = dumped["estimates"]["rapid_refuel_carbohydrate_g_per_hour"]
    assert refuel["applies_if"] == "another demanding session within 8 hours"


def test_exercise_status_has_the_three_documented_values():
    assert {status.value for status in ExerciseStatus} == {
        "TRAINED",
        "LOGGED_WITHOUT_SETS",
        "SKIPPED",
    }


def test_response_round_trips_through_its_own_json():
    response = RecoverySummaryResponse.model_validate(full_response())

    again = RecoverySummaryResponse.model_validate_json(response.model_dump_json())

    assert again == response


def models_in(annotation):
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return {annotation}
    found = set()
    for arg in get_args(annotation):
        found |= models_in(arg)
    return found


def all_models(root):
    """root and every model its fields lead to."""
    seen = set()
    pending = [root]
    while pending:
        model = pending.pop()
        if model in seen:
            continue
        seen.add(model)
        for field in model.model_fields.values():
            pending.extend(models_in(field.annotation))
    return seen


def test_every_response_model_rejects_unknown_fields():
    models = all_models(RecoverySummaryResponse)

    assert len(models) >= 15
    for model in models:
        assert model.model_config.get("extra") == "forbid", model.__name__


def test_response_rejects_a_misspelt_field_at_any_depth():
    data = full_response()
    data["guidance"]["recovery"]["muscles"][0]["rest_hour"] = 48

    errors = rejected(RecoverySummaryResponse, data)

    assert ("guidance", "recovery", "muscles", 0, "rest_hour") in [
        error["loc"] for error in errors
    ]


def test_estimate_range_rejects_a_low_above_its_high():
    errors = rejected(EstimateRange, estimate(30, 18))

    assert [error["type"] for error in errors] == ["value_error"]


def test_estimate_range_accepts_equal_ends():
    assert EstimateRange.model_validate(estimate(20, 20)).low == 20


def test_estimates_reject_a_low_above_its_high_inside_a_response():
    data = full_response()
    data["estimates"]["daily_protein_g"] = estimate(144, 115)

    errors = rejected(RecoverySummaryResponse, data)

    assert errors[0]["loc"][:2] == ("estimates", "daily_protein_g")


def test_estimates_default_to_none():
    assert Estimates().model_dump() == {
        "post_workout_protein_g": None,
        "daily_protein_g": None,
        "daily_carbohydrate_g": None,
        "rapid_refuel_carbohydrate_g_per_hour": None,
        "active_energy_kcal": None,
    }


def test_guidance_never_says_fluid_loss_was_measured():
    assert Guidance().fluid_loss_measured is False
    assert Guidance(fluid_loss_measured=False).fluid_loss_measured is False
    for value in (True, 1, "true"):
        errors = rejected(Guidance, {"fluid_loss_measured": value})
        assert [error["loc"] for error in errors] == [("fluid_loss_measured",)]


def test_withheld_guidance_is_empty_lists_and_nones():
    assert Guidance().model_dump(mode="json") == {
        "post_workout_carbohydrate": [],
        "hydration": [],
        "fluid_loss_measured": False,
        "sleep": None,
        "recovery": None,
        "food_suggestions": None,
    }


def test_guidance_instances_do_not_share_their_lists():
    first = Guidance()
    first.hydration.append(Guidance.model_validate({"hydration": [note()]}).hydration[0])

    assert Guidance().hydration == []


def plan(status, rest_hours=None, rest_until=None, role="PRIMARY"):
    return {
        "muscle": "Quadriceps",
        "role": role,
        "status": status,
        "rest_hours": rest_hours,
        "rest_until": rest_until,
        "reasons": [],
        "source_ids": [],
    }


@pytest.mark.parametrize(
    "data",
    [
        plan("REST", 48, REST_UNTIL),
        plan("REST", 72, REST_UNTIL, role=None),
        plan("ALSO_WORKED", role="SECONDARY"),
        plan("SEE_PROFESSIONAL"),
        plan("SEE_PROFESSIONAL", role=None),
    ],
)
def test_muscle_recovery_plan_accepts_a_window_only_for_rest(data):
    assert MuscleRecoveryPlan.model_validate(data).status == data["status"]


@pytest.mark.parametrize(
    "data",
    [
        # a painful area never carries a return-to-training time
        plan("SEE_PROFESSIONAL", 48, REST_UNTIL),
        plan("SEE_PROFESSIONAL", 48, None),
        plan("SEE_PROFESSIONAL", None, REST_UNTIL),
        plan("ALSO_WORKED", 48, REST_UNTIL, role="SECONDARY"),
        plan("ALSO_WORKED", None, REST_UNTIL, role="SECONDARY"),
        plan("ALSO_WORKED", 48, None, role="SECONDARY"),
        # a muscle that rests has both
        plan("REST"),
        plan("REST", 48, None),
        plan("REST", None, REST_UNTIL),
    ],
)
def test_muscle_recovery_plan_rejects_a_window_that_does_not_fit_its_status(data):
    errors = rejected(MuscleRecoveryPlan, data)

    assert [error["type"] for error in errors] == ["value_error"]


def test_muscle_recovery_plan_rejects_an_unknown_status():
    assert rejected(MuscleRecoveryPlan, plan("rest", 48, REST_UNTIL))
    assert rejected(MuscleRecoveryPlan, plan("RESTING", 48, REST_UNTIL))


# --- the Literals stand for the app.guidance enums -----------------------------------


def literal_values(annotation):
    """The values of every Literal in an annotation, looking through unions."""
    if get_origin(annotation) is Literal:
        return set(get_args(annotation))
    values = set()
    for arg in get_args(annotation):
        values |= literal_values(arg)
    return values


@pytest.mark.parametrize(
    ("model", "field", "enum"),
    [
        (SafetySummary, "status", SafetyStatus),
        (MuscleRecoveryPlan, "status", MuscleStatus),
        (ProfileValuesUsed, "goal_category", GoalCategory),
        (FoodSuggestions, "preference_status", PreferenceStatus),
        (FoodSuggestions, "dietary_pattern", DietPattern),
    ],
)
def test_response_literal_values_are_exactly_the_guidance_enum_values(model, field, enum):
    # app.schemas cannot import app.guidance (it would be a cycle), so the response names
    # these as strings: this fails when either side changes alone.
    values = literal_values(model.model_fields[field].annotation)

    assert values
    assert values == {member.value for member in enum}


def test_response_accepts_the_guidance_enum_members_and_dumps_plain_strings():
    summary = SafetySummary(status=SafetyStatus.SEEK_MEDICAL_CARE, notices=[])
    plan_ = MuscleRecoveryPlan.model_validate(plan(MuscleStatus.SEE_PROFESSIONAL))
    values = ProfileValuesUsed(
        weight_kg=72.0,
        age=29,
        bmi=None,
        goal=None,
        goal_category=GoalCategory.UNRECOGNISED,
        dietary_preference=None,
        sleep_hours=None,
    )
    food = FoodSuggestions(
        preference_status=PreferenceStatus.NOT_SET,
        dietary_pattern=DietPattern.NO_RESTRICTION,
        allergens_excluded=[],
        items=[],
        caveats=[],
    )

    assert summary.model_dump(mode="json")["status"] == "SEEK_MEDICAL_CARE"
    assert plan_.model_dump(mode="json")["status"] == "SEE_PROFESSIONAL"
    assert values.model_dump(mode="json")["goal_category"] == "UNRECOGNISED"
    assert food.model_dump(mode="json")["preference_status"] == "NOT_SET"
    assert food.model_dump(mode="json")["dietary_pattern"] == "NO_RESTRICTION"


@pytest.mark.parametrize(
    ("model", "data"),
    [
        (SafetySummary, {"status": "ok", "notices": []}),
        (SafetySummary, {"status": "DANGER", "notices": []}),
        (
            FoodSuggestions,
            {
                "preference_status": "APPLIED",
                "dietary_pattern": "KETO",
                "allergens_excluded": [],
                "items": [],
                "caveats": [],
            },
        ),
    ],
)
def test_response_rejects_a_status_that_is_not_one_of_the_values(model, data):
    assert rejected(model, data)


# --- the response never echoes the user's text ---------------------------------------


def test_response_models_have_no_field_that_could_echo_what_the_user_wrote():
    forbidden = {"notes", "note", "description", "message_from_user", "input", "free_text"}
    names_by_model = {
        model.__name__: set(model.model_fields) for model in all_models(RecoverySummaryResponse)
    }

    for model_name, names in names_by_model.items():
        assert not names & forbidden, f"{model_name} has {names & forbidden}"

    # The only free-text fields of the response are Formiq's own fixed text:
    # SafetyNotice.message and GuidanceNote.text.
    assert {name for name, names in names_by_model.items() if "message" in names} == {
        "SafetyNotice"
    }
    assert {name for name, names in names_by_model.items() if "text" in names} == {
        "GuidanceNote"
    }
