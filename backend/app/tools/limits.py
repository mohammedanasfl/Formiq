"""Bounds on what the tools read and return, so no result can grow without limit."""

# exercises returned by search_exercises. 15, not 10: of the 36 warm-up and cool-down
# searches for one muscle the catalog allows, 11 had more than 10 matches and 5 have
# more than 15 (a search always says when it was cut: SearchExercisesOutput.note)
MAX_SEARCH_RESULTS = 15
# exercises a search that found none for its section names, which match its other
# filters but are used for another section (a rowing machine exercise a search
# for the main workout does not return, but the warm-up uses)
MAX_OTHER_USE_MATCHES = 3
# equipment names a search may say the user has
MAX_SEARCH_EQUIPMENT = 20
# an exercise's instruction steps returned by get_exercise (each cut to
# MAX_TEXT_LENGTH)
MAX_INSTRUCTION_STEPS = 12
# exercises returned for one workout plan or session
MAX_EXERCISES = 30
# plans listed by list_workout_plans, and the main exercises named for each
MAX_LISTED_PLANS = 20
MAX_LISTED_PLAN_EXERCISES = 8
# catalog exercises a refused proposal suggests, for each thing to correct
MAX_SUGGESTIONS = 3
# sets returned for one exercise of a workout session
MAX_SETS = 15
# characters of free text (notes, descriptions); longer text is cut
MAX_TEXT_LENGTH = 500
# Tool calls run from one model turn; the rest are answered with an error (the
# coach graph rejects a turn that requests more than 20 calls). Enough for what
# a new workout needs in one round: the profile, the current plan, the last
# workout, the proposal awaiting approval and the plans list, and the
# warm-up, main and cool-down searches. With 5, a model that batched what the
# instructions ask lost the sixth call to this limit, and a round to it. With 8, a leg day
# searched by movement pattern (three main searches, with the three reads and the warm-up
# and cool-down searches) used every call, so a lookup by name or one more search lost the
# cool-down search (live QA, 2026-10-19); 10 leaves two spare.
MAX_EXECUTED_TOOL_CALLS_PER_TURN = 10

# A workout plan the coach proposes (propose_workout_plan): Formiq's coaching
# bounds, tighter than the plan columns' own limits.
MAX_PROPOSED_EXERCISES = 10
MAX_PROPOSED_SETS = 10
MAX_PROPOSED_REPS = 30
MAX_PROPOSED_REST_SECONDS = 300
# how many days after today a proposed plan may be scheduled
MAX_PROPOSAL_DAYS_AHEAD = 14
# equipment the user cannot use, by name: enough to name every piece the catalog
# lists (12), for a user with none at all
MAX_UNAVAILABLE_EQUIPMENT = 20
# A proposal's warm-up and cool-down: 1 to MAX_SECTION_ACTIVITIES light
# activities each, of 1 to MAX_ACTIVITY_SETS sets of reps or of a timed hold or
# bout, and at most MAX_SECTION_MINUTES each by the estimate below.
MAX_SECTION_ACTIVITIES = 5
MAX_ACTIVITY_SETS = 3
MAX_ACTIVITY_REPS = 20
MIN_ACTIVITY_SECONDS = 10
MAX_ACTIVITY_SECONDS = 600
# A held stretch is held this long at most in a set (the catalog's own doses are 20
# to 30 seconds); more time is more sets. A product guardrail, not a medical rule.
MAX_STRETCH_HOLD_SECONDS = 60
MAX_SECTION_MINUTES = 15
# A proposal's duration estimate: each set takes this long (or its own duration,
# when timed), plus its rest. A set of reps takes SECONDS_PER_REP a rep when
# that is longer: more than 15 reps. A main exercise without a rest gets
# DEFAULT_REST_SECONDS; warm-up and cool-down activities have none.
SET_SECONDS = 45
SECONDS_PER_REP = 3
DEFAULT_REST_SECONDS = 90
# A proposal's completeness (app.tools.completeness). Its main workout holds at
# least MIN_FULL_BODY_EXERCISES main exercises for the whole body, or
# MIN_FOCUSED_EXERCISES for one part of it; at least MIN_SHORT_SESSION_EXERCISES
# when the user has under SHORT_SESSION_MINUTES. Only an exercise of at least
# MIN_COUNTED_SETS sets counts. These are minimums, not targets.
SHORT_SESSION_MINUTES = 30
MIN_FULL_BODY_EXERCISES = 4
MIN_FOCUSED_EXERCISES = 3
MIN_SHORT_SESSION_EXERCISES = 2
MIN_COUNTED_SETS = 2
# The warm-up of a session that is not short lasts at least this long, by the
# duration estimate above.
MIN_WARM_UP_MINUTES = 3
# Given the minutes the user has, a proposal takes at least half of them, but
# never needs to take more than this.
MAX_REQUIRED_MINUTES = 45
