import asyncio
import logging
from typing import Annotated, Any, Dict, List, Literal, Optional
from typing_extensions import TypedDict
from pydantic import BaseModel, Field

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.runnables import RunnableConfig

from .redis_events import halt_manager
from .state import AgentState as CoreAgentState

logger = logging.getLogger(__name__)

# ── 1. State Definition ──
class AgentState(TypedDict):
    """LangGraph 기반 에이전트 상태 (Unified with core.state)"""
    messages: Annotated[list[BaseMessage], "add_messages"]
    next: str  # supervisor가 라우팅할 다음 에이전트
    halt_requested: bool  # Halt mechanism flag
    internal_data: dict[str, Any]  # for scratchpad / HITL modifications
    core_state: CoreAgentState # Pydantic v2 unified state reference

# ── 2. Agents ──
async def supervisor_node(state: AgentState):
    """
    작업의 성격을 분석하여 적절한 에이전트(Worker, Critic 등)에게 라우팅합니다.
    """
    next_agent = "worker"
        
    if state.get("halt_requested"):
        next_agent = "END"
        
    return {"next": next_agent}

async def worker_node(state: AgentState):
    """
    실제 작업을 수행하는 핵심 에이전트 노드.
    (향후 agents/worker.py 연동)
    """
    return {"messages": [AIMessage(content="Worker 에이전트: 요청하신 작업을 처리 중입니다.")]}

# ── 3. Edge Logic ──
def router_edge(state: AgentState, config: RunnableConfig) -> Literal["worker", "__end__"]:
    """Supervisor의 결정에 따라 라우팅"""
    thread_id = config.get("configurable", {}).get("thread_id", "")
    
    if thread_id and halt_manager.is_halt_requested(thread_id):
        logger.warning(f"🛑 라우팅 엣지에서 Halt 요청 감지됨. 세션 {thread_id} 종료.")
        return "__end__"
        
    if state.get("halt_requested"):
        return "__end__"
        
    next_node = state.get("next", "worker")
    if next_node == "END":
        return "__end__"
    return next_node

# ── 4. Graph Construction ──
from psycopg_pool import AsyncConnectionPool

def build_graph():
    builder = StateGraph(AgentState)
    
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("worker", worker_node)
    
    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges("supervisor", router_edge)
    
    # 각 노드에서 작업 완료 후 종료되거나 supervisor로 복귀할 수 있음
    builder.add_edge("worker", END)
    
    return builder

# ── 5. Runtime Interface ──
async def get_compiled_graph(pool: AsyncConnectionPool):
    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()
    graph = build_graph()
    # HITL (Pause) 설정: worker 직전에 일시 정지 (예시)
    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["worker"]
    )
