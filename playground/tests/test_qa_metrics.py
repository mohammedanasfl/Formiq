"""The QA pass's aggregation: turn summaries are printed by the playground and
read back from a saved log, and a log of several models is never mixed."""

import json
import logging

import pytest
import qa_metrics
import server

from app.observability import TurnRecorder
from app.observability.trajectory import SCHEMA


def summary(turn_id, model="gemini-test", total=1000, requests=2, outcome="not_attempted"):
    recorder = TurnRecorder(turn_id)
    recorder.model = model
    for number in range(requests):
        started = recorder.model_request_started(round=number, kind="open", offered=11)
        recorder.model_request_completed(
            started, duration_ms=100 * (number + 1), usage={"total_tokens": total},
            model_reported=model, requested_calls=0, responded=True,
        )
    recorder.proposal(outcome)
    recorder.finish("success")
    return recorder.summary()


def log_of(*summaries):
    lines = ["INFO: noise before", "127.0.0.1 - GET /health"]
    lines += [qa_metrics.MARKER + json.dumps(item) for item in summaries]
    lines += ["WARNING: the coach reached 5 rounds", qa_metrics.MARKER + "{not json"]
    return lines


def test_the_summaries_are_read_from_a_log_and_other_lines_are_ignored():
    found = qa_metrics.read_summaries(log_of(summary("a"), summary("b")))

    assert [item["turn_id"] for item in found] == ["a", "b"]
    assert all(item["schema"] == SCHEMA for item in found)


def test_a_pass_is_aggregated_with_its_samples_and_denominators(tmp_path, capsys):
    path = tmp_path / "server.log"
    path.write_text("\n".join(log_of(summary("a", total=1000), summary("b", total=3000))))

    qa_metrics.main([str(path)])

    report = json.loads(capsys.readouterr().out)
    assert report["turns"] == 2 and report["models"] == ["gemini-test"]
    assert report["per_turn"]["tokens_total"]["n"] == 2
    assert report["tokens"]["estimated"] is False
    assert report["request_completed"]["denominator"] == "all turns"


def test_a_log_of_several_models_is_refused_unless_one_is_chosen(tmp_path, capsys):
    path = tmp_path / "server.log"
    path.write_text("\n".join(log_of(summary("a", model="gemini-a"), summary("b", model="gemini-b"))))

    with pytest.raises(SystemExit, match="several models"):
        qa_metrics.main([str(path)])

    qa_metrics.main([str(path), "--model", "gemini-b"])
    assert json.loads(capsys.readouterr().out)["models"] == ["gemini-b"]


def test_the_playground_prints_each_turns_summary_without_content(capsys):
    logger = logging.getLogger("app.observability.trajectory")
    before = (list(logger.handlers), logger.level, logger.propagate, logger.disabled)
    try:
        server.log_turn_summaries()
        recorder = TurnRecorder("printed")
        recorder.finish("success")
        recorder.log_summary()
    finally:
        logger.handlers[:] = before[0]
        logger.level, logger.propagate, logger.disabled = before[1:]

    (printed,) = [line for line in capsys.readouterr().out.splitlines() if line.startswith(qa_metrics.MARKER)]
    assert json.loads(printed.removeprefix(qa_metrics.MARKER))["turn_id"] == "printed"
