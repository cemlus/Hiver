"""LangGraph wiring for the agent. Orchestration only -- no business logic lives here.

The graph is deliberately boring: three nodes, each a pass-through to a function in `src/core`
that is already tested on its own.

    START -> route -> respond -> finalize -> END

Classification, cue extraction, the escalation policy, retrieval, drafting and validation all stay
in `src/core`. Nothing in this module decides anything: there are no conditional edges, because the
handoff path is already core behaviour -- `respond()` returns an escalated state untouched, so
"skip drafting when escalating" is a property of the policy, not of the graph.

Dependencies (the LLM, the retriever, thresholds) are injected by closure, so the graph state stays
pure data and the same compiled graph can be reused across requests.
"""
from __future__ import annotations

from typing import Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from src.contracts import AgentOutput, AgentState, RetrievedExample, SupportRequest, finalize
from src.core.respond import respond
from src.core.route import route
from src.ports.protocols import LLMClient

Retriever = Callable[[str], tuple[RetrievedExample, ...]]


class GraphState(TypedDict, total=False):
    """What flows between nodes: the request in, the working state, the finished output."""
    request: SupportRequest
    state: AgentState
    output: AgentOutput


def build_graph(llm: LLMClient, *, retriever: Retriever, system: str = "agent",
                confidence_threshold: float = 0.0, union_cues: bool = True,
                max_attempts: int = 2, max_chars: int = 280,
                model_versions: dict[str, str] | None = None):
    """Compile the graph. Every argument is a dependency; none of them is a decision."""

    def route_node(graph_state: GraphState) -> GraphState:
        return {"state": route(graph_state["request"], llm,
                               confidence_threshold=confidence_threshold, union_cues=union_cues)}

    def respond_node(graph_state: GraphState) -> GraphState:
        return {"state": respond(graph_state["state"], llm, retriever=retriever,
                                 max_attempts=max_attempts, max_chars=max_chars)}

    def finalize_node(graph_state: GraphState) -> GraphState:
        return {"output": finalize(graph_state["state"], system=system,
                                   model_versions=model_versions)}

    graph = StateGraph(GraphState)
    graph.add_node("route", route_node)
    graph.add_node("respond", respond_node)
    graph.add_node("finalize", finalize_node)
    graph.add_edge(START, "route")
    graph.add_edge("route", "respond")
    graph.add_edge("respond", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


def run(request: SupportRequest, llm: LLMClient, *, retriever: Retriever, **kwargs) -> AgentOutput:
    """One request through the graph. Equivalent to route -> respond -> finalize by hand."""
    compiled = build_graph(llm, retriever=retriever, **kwargs)
    return compiled.invoke({"request": request})["output"]


__all__ = ["build_graph", "run", "GraphState"]
