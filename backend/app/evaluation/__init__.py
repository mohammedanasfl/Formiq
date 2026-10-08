"""Deterministic evaluation of the coach: a dataset of cases, a runner that runs
them through the coach and observes the result, evaluators that judge it, and a
regression summary. Separate from the coach: nothing here changes how it
behaves."""

from app.evaluation.dataset import CASES
from app.evaluation.evaluators import (
    EVALUATORS,
    EXPECTED_LIMITS,
    HARD,
    INVARIANTS,
    evaluate_case,
    live_expectations,
)
from app.evaluation.fixtures import Fixtures, create_fixtures
from app.evaluation.models import (
    CaseResult,
    EvalCase,
    EvaluationRunResult,
    ExecutionResult,
)
from app.evaluation.report import format_report, summarize
from app.evaluation.runner import run_case

__all__ = [
    "CASES",
    "EVALUATORS",
    "EXPECTED_LIMITS",
    "HARD",
    "INVARIANTS",
    "CaseResult",
    "EvalCase",
    "EvaluationRunResult",
    "ExecutionResult",
    "Fixtures",
    "create_fixtures",
    "evaluate_case",
    "format_report",
    "live_expectations",
    "run_case",
    "summarize",
]
