"""Bounds on what the tools read and return, so no result can grow without limit."""

# exercises returned by search_exercises
MAX_SEARCH_RESULTS = 10
# equipment names a search may say the user has
MAX_SEARCH_EQUIPMENT = 20
# an exercise's instruction steps returned by get_exercise (each cut to
# MAX_TEXT_LENGTH)
MAX_INSTRUCTION_STEPS = 12
# exercises returned for one workout plan or session
MAX_EXERCISES = 30
# sets returned for one exercise of a workout session
MAX_SETS = 15
# characters of free text (notes, descriptions); longer text is cut
MAX_TEXT_LENGTH = 500
# tool calls run from one model turn; the rest are answered with an error (the
# coach graph rejects a turn that requests more than 20 calls)
MAX_EXECUTED_TOOL_CALLS_PER_TURN = 5

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
MAX_SECTION_MINUTES = 15
# A proposal's duration estimate: each set takes this long (or its own duration,
# when timed), plus its rest. A main exercise without a rest gets
# DEFAULT_REST_SECONDS; warm-up and cool-down activities have none.
SET_SECONDS = 45
DEFAULT_REST_SECONDS = 90
