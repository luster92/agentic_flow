"""LangGraph entry points for Clawflow.

`create_orchestration_graph` is the shared runtime for new CLI/API code.
`get_compiled_graph` preserves the legacy Postgres-checkpoint example until all
transports have migrated to dependency injection.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal
from typing_extensions import TypedDict

from langchain_core.messages import BaseMessage, AIMessage
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langchain_core.runnables import RunnableConfig
from psycopg_pool import AsyncConnectionPool

from .redis_events import halt_manager
from .state import AgentState as CoreAgentState
from .orchestration_graph import OrchestrationDependencies, OrchestrationGraph

logger = logging.getLogger(__name__)


def create_orchestration_graph(
    dependencies: OrchestrationDependencies,
    *,
    checkpointer=None,
):
    """Compile the production-oriented shared orchestration graph.

    Transport layers should construct adapters for Router, Worker, cloud model,
    cache, approval, and persistence, then invoke this factory.
    """
    return OrchestrationGraph(dependencies).compile(checkpointer=checkpointer)


# ---------------------------------------------------------------------------
# Legacy graph retained for compatibility while CLI/API migration is ongoing.
# ---------------------------------------------------------------------------
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], "add_messages"]
    next: str
    halt_requested: bool
    internal_data: dict[str, Any]
    core_state: CoreAgentState


async def supervisor_node(state: AgentState):
    next_agent = "END" if state.get("halt_requested") else "worker"
    return {"next": next_agent}


async def worker_node(state: AgentState):
    return {"messages": [AIMessage(content="Worker 에이전트: 요청하신 작업을 처리 중입니다.")]}


def router_edge(state: AgentState, config: RunnableConfig) -> Literal["worker", "__end__"]:
    thread_id = config.get("configurable", {}).get("thread_id", "")
    if thread_id and halt_manager.is_halt_requested(thread_id):
        logger.warning("Halt requested for session %s", thread_id)
        return "__end__"
    if state.get("halt_requested") or state.get("next") == "END":
        return "__end__"
    return "worker"


def build_graph():
    """Build the deprecated placeholder graph.

    New code must use `create_orchestration_graph` instead.
    """
    builder = StateGraph(AgentState)
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("worker", worker_node)
    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges("supervisor", router_edge)
    builder.add_edge("worker", END)
    return builder


async def get_compiled_graph(pool: AsyncConnectionPool):
    """Compile the legacy graph with a Postgres checkpointer."""
    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()
    return build_graph().compile(
        checkpointer=checkpointer,
        interrupt_before=["worker"],
    )
