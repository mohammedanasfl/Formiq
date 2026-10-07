"""What the coach's trace records about a tool call and its result: counts,
sizes, names and codes, never the arguments' values or the result's data."""

import json
from typing import Any

from app.agent.policy import data_status
from app.ai import ToolCall

# the tools that read the trusted user's own data
_USER_SCOPED = frozenset({"get_user_profile", "get_workout_plan", "get_workout_session"})


def call_metadata(call: ToolCall) -> dict[str, Any]:
    """The call's shape: which arguments it has, not what they say."""
    names = sorted(str(name) for name in call.arguments)
    return {
        "argument_names": names,
        "id_arguments": sum(name.endswith("_id") for name in names),
        "user_scoped": call.name in _USER_SCOPED,
        "user_id_argument": "user_id" in call.arguments,
    }


def result_metadata(result: dict[str, Any]) -> dict[str, Any]:
    """The result's shape: its status, size and error code, not its data."""
    output, error = result.get("output"), result.get("error")
    metadata: dict[str, Any] = {
        "data_status": data_status(result),
        "output_chars": len(json.dumps(result, default=str)),
    }
    if isinstance(output, dict):
        metadata["truncated"] = bool(output.get("truncated"))
        counts = [len(value) for value in output.values() if isinstance(value, list)]
        if counts:
            metadata["result_count"] = sum(counts)
    if isinstance(error, dict):
        metadata["error_code"] = str(error.get("code"))[:50]
    return metadata
