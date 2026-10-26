"""Aggregates the coach turns of a live QA pass. LOCAL DEVELOPMENT ONLY.

The playground prints one `coach_turn_summary {json}` line per coach turn (the
safe summary of app.observability.trajectory: tool counts, tokens, latency, the
retry round, the events as codes, never content). This reads those lines from a
saved server log and prints the pass's medians, p90s and rates, each with its
sample count and what it is a rate of:

    cd backend
    .venv/bin/python ../playground/qa_metrics.py SERVER_LOG [--model gemini-3.5-flash-lite]

--model keeps only the turns of that model, so runs on different models are
never mixed: without it, a log of several models is refused. A pass's request
ids (turn_id) are the ones the playground returns in X-Playground-Request-Id.
"""

import argparse
import json
import sys
from pathlib import Path

PLAYGROUND = Path(__file__).resolve().parent
BACKEND = PLAYGROUND.parent / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.observability.trajectory import SCHEMA, aggregate  # noqa: E402

MARKER = "coach_turn_summary "


def read_summaries(lines) -> list[dict]:
    """The turn summaries among the log lines, in order; other lines are ignored."""
    found = []
    for line in lines:
        _, marker, text = line.partition(MARKER)
        if not marker:
            continue
        try:
            summary = json.loads(text)
        except ValueError:
            continue
        if isinstance(summary, dict) and summary.get("schema") == SCHEMA:
            found.append(summary)
    return found


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Aggregate a live QA pass's coach turns")
    parser.add_argument("log", type=Path, help="a saved playground server log")
    parser.add_argument("--model", help="keep only the turns of this model")
    args = parser.parse_args(argv)
    summaries = read_summaries(args.log.read_text(errors="replace").splitlines())
    if args.model:
        summaries = [s for s in summaries if s["model"] == args.model]
    models = {s["model"] for s in summaries}
    if len(models) > 1:
        raise SystemExit(
            f"The log holds turns of several models ({', '.join(sorted(map(str, models)))}): "
            "choose one with --model, so runs on different models are not compared."
        )
    if not summaries:
        raise SystemExit("No coach turn summaries found.")
    print(json.dumps(aggregate(summaries), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
