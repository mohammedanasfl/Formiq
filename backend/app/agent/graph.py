"""The coach graph: START -> coach -> END.

The model is given at run time through the graph's context, so one compiled
graph serves every request, and tests can give a fake model.
"""

from dataclasses import dataclass

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from app.agent.state import CoachState
from app.ai import GeminiProvider

COACH_INSTRUCTIONS = (
    "You are Formiq, an adaptive AI fitness coach. Answer the user's training and "
    "fitness questions clearly and concisely, in a supportive tone. You cannot see "
    "the user's profile, workouts or other Formiq data yet, so do not claim to know "
    "them or make them up; ask when you need details. You are not a medical "
    "professional: for pain, injuries or health conditions, recommend a qualified "
    "professional."
)


@dataclass(frozen=True)
class CoachContext:
    provider: GeminiProvider


def coach_node(state: CoachState, runtime: Runtime[CoachContext]) -> dict[str, str]:
    reply = runtime.context.provider.generate(state["message"], instructions=COACH_INSTRUCTIONS)
    return {"reply": reply}


def build_coach_graph() -> CompiledStateGraph:
    graph = StateGraph(CoachState, context_schema=CoachContext)
    graph.add_node("coach", coach_node)
    graph.add_edge(START, "coach")
    graph.add_edge("coach", END)
    return graph.compile()


coach_graph = build_coach_graph()
