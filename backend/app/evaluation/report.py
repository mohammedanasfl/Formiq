"""The regression summary of a set of evaluated cases."""

from collections.abc import Iterable

from app.evaluation.models import CaseResult, EvaluationRunResult, Failure


def summarize(results: Iterable[CaseResult]) -> EvaluationRunResult:
    """The run's totals. A case with a known gap is expected to fail: it counts
    as passed while it does, and is reported as fixed once it passes."""
    results = list(results)
    failures: list[Failure] = []
    summary: dict[str, tuple[int, int]] = {}
    known_gaps, fixed_gaps = [], []
    passed = 0
    for case in results:
        for result in case.results:
            ok, failed = summary.get(result.name, (0, 0))
            summary[result.name] = (ok + result.passed, failed + (not result.passed))
        if case.known_gap is not None:
            (known_gaps if not case.passed else fixed_gaps).append(case.case_id)
            passed += not case.passed
            continue
        if case.passed:
            passed += 1
        failures += [
            Failure(case.case_id, result.name, result.expected, result.actual, result.reason)
            for result in case.failures
        ]
    return EvaluationRunResult(
        total_cases=len(results),
        passed=passed,
        failed=len(results) - passed,
        failures=tuple(failures),
        evaluator_summary=dict(sorted(summary.items())),
        known_gaps=tuple(known_gaps),
        fixed_gaps=tuple(fixed_gaps),
    )


def format_failure(failure: Failure) -> str:
    return (
        f"FAIL\n"
        f"case: {failure.case_id}\n"
        f"evaluator: {failure.evaluator}\n"
        f"expected: {failure.expected}\n"
        f"actual: {failure.actual}\n"
        f"reason: {failure.reason}"
    )


def format_report(run: EvaluationRunResult) -> str:
    lines = [
        (
            f"cases: {run.total_cases}  passed: {run.passed}  failed: {run.failed}  "
            f"pass rate: {run.pass_rate:.1%}"
        )
    ]
    if run.known_gaps:
        lines.append(f"known gaps (expected to fail): {', '.join(run.known_gaps)}")
    if run.fixed_gaps:
        lines.append(f"known gaps that now pass (update the case): {', '.join(run.fixed_gaps)}")
    lines += [format_failure(failure) for failure in run.failures]
    return "\n\n".join(lines)
