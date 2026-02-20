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

logger = logging.getLogger(__name__)

# ── 1. State Definition ──
class AgentState(TypedDict):
    """LangGraph 기반 에이전트 상태"""
    messages: Annotated[list[BaseMessage], "add_messages"]
    next: str  # supervisor가 라우팅할 다음 에이전트
    halt_requested: bool  # Halt mechanism flag
    internal_data: dict[str, Any]  # for scratchpad / HITL modifications

# ── 2. Agents (Mocks/Stubs for logic) ──
async def supervisor_node(state: AgentState):
    """
    고객의 의도를 분류하여 최적의 에이전트에게 라우팅합니다.
    (Tier 1, 2, 3, Sales, Billing)
    """
    messages = state.get("messages", [])
    last_msg = messages[-1].content.lower() if messages else ""
    
    # Simple rule-based routing for demonstration
    if "결제" in last_msg or "환불" in last_msg or "billing" in last_msg:
        next_agent = "billing"
    elif "구매" in last_msg or "할인" in last_msg or "sales" in last_msg:
        next_agent = "sales"
    elif "어려운" in last_msg or "에러" in last_msg or "버그" in last_msg:
        next_agent = "tier3"
    elif "도움" in last_msg:
        next_agent = "tier2"
    else:
        next_agent = "tier1"
        
    if state.get("halt_requested"):
        next_agent = "END"
        
    return {"next": next_agent}

async def tier1_node(state: AgentState):
    # Tier 1 일반 문의 처리
    return {"messages": [AIMessage(content="Tier 1 에이전트: 일반적인 문의를 도와드리겠습니다.")]}

async def tier2_node(state: AgentState):
    # Tier 2 기술 지원 처리
    return {"messages": [AIMessage(content="Tier 2 에이전트: 상세 기술 지원을 도와드리겠습니다.")]}

async def tier3_node(state: AgentState):
    # Tier 3 심층 기술 지원 처리
    return {"messages": [AIMessage(content="Tier 3 에이전트: 심층 기술 이슈를 분석해 드리겠습니다.")]}

async def sales_node(state: AgentState):
    # Sales 영업 처리
    return {"messages": [AIMessage(content="Sales 에이전트: 구매 및 업그레이드 안내를 도와드리겠습니다.")]}

async def billing_node(state: AgentState):
    # Billing 결제 처리
    return {"messages": [AIMessage(content="Billing 에이전트: 결제 및 환불 처리를 도와드리겠습니다.")]}

# ── 3. Edge Logic ──
def router_edge(state: AgentState, config: RunnableConfig) -> Literal["tier1", "tier2", "tier3", "sales", "billing", "__end__"]:
    """Supervisor의 결정에 따라 라우팅"""
    thread_id = config.get("configurable", {}).get("thread_id", "")
    
    if thread_id and halt_manager.is_halt_requested(thread_id):
        logger.warning(f"🛑 라우팅 엣지에서 Halt 요청 감지됨. 세션 {thread_id} 종료.")
        return "__end__"
        
    if state.get("halt_requested"):
        return "__end__"
        
    next_node = state.get("next", "tier1")
    if next_node == "END":
        return "__end__"
    return next_node

# ── 4. Graph Construction ──
from psycopg_pool import AsyncConnectionPool

def build_graph():
    builder = StateGraph(AgentState)
    
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("tier1", tier1_node)
    builder.add_node("tier2", tier2_node)
    builder.add_node("tier3", tier3_node)
    builder.add_node("sales", sales_node)
    builder.add_node("billing", billing_node)
    
    # HITL: Billing 승인 전 interrupt 지점 추가
    # 예를 들어, "billing" 노드 실행 직전에 대기
    # 이건 builder.compile(interrupt_before=["billing"]) 로 처리
    
    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges("supervisor", router_edge)
    
    # 각 노드에서 작업 완료 후 종료되거나 supervisor로 복귀할 수 있음
    builder.add_edge("tier1", END)
    builder.add_edge("tier2", END)
    builder.add_edge("tier3", END)
    builder.add_edge("sales", END)
    builder.add_edge("billing", END)
    
    return builder

# ── 5. Runtime Interface ──
async def get_compiled_graph(pool: AsyncConnectionPool):
    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()
    graph = build_graph()
    # HITL (Pause) 설정: billing과 sales 직전에 일시 정지
    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["billing", "sales"]
    )
