"""Bounds on what the tools read and return, so no result can grow without limit."""

# exercises returned by search_exercises
MAX_SEARCH_RESULTS = 10
# exercises returned for one workout plan or session
MAX_EXERCISES = 30
# sets returned for one exercise of a workout session
MAX_SETS = 15
# characters of free text (notes, descriptions); longer text is cut
MAX_TEXT_LENGTH = 500
# tool calls run from one model turn; the rest are answered with an error
MAX_CALLS_PER_TURN = 5
