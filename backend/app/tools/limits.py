"""Bounds on what the tools read and return, so no result can grow without limit."""

# exercises returned by search_exercises
MAX_SEARCH_RESULTS = 10
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
# A proposal's duration estimate: each set takes this long, plus its rest (or
# DEFAULT_REST_SECONDS when the proposal gives none).
SET_SECONDS = 45
DEFAULT_REST_SECONDS = 90
