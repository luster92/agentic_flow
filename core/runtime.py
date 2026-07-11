"""Shared graph runtime used by CLI and API transports."""

from __future__ import annotations

import logging
import os
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from openai import AsyncOpenAI

from agents.router import Router
from agents.worker import Worker
from core.checkpoint import CheckpointManager
from core.event_bus import Event, EventBus, EventType
from core.graph import create_orchestration_graph
from core.orchestration_graph import OrchestrationDependencies
from core.state import AgentState, CheckpointType
from engine.hitl import HITLManager
from engine.persona import PersonaManager
from utils.history_manager import HistoryManager
from utils.semantic_cache import SemanticCache

logger = logging.getLogger("clawflow.runtime")


class GraphRuntime:
    """Own graph adapters and mutable state for one conversation session."""

    def __init__(
        self,
        *,
        router: Router,
        worker: Worker,
        history: HistoryManager,
        state: AgentState,
        cache: SemanticCache,
        checkpoint: CheckpointManager,
        hitl: HITLManager,
        persona: PersonaManager,
        events: EventBus,
        litellm_base_url: str | None = None,
        graph_checkpointer=None,
    ) -> None:
        self.router = router
        self.worker = worker
        self.history = history
        self.state = state
        self.cache = cache
        self.checkpoint = checkpoint
        self.hitl = hitl
        self.persona = persona
        self.events = events
        self.litellm_base_url = litellm_base_url or os.getenv(
            "LITELLM_BASE_URL", "http://localhost:4000"
        )
        self.graph_checkpointer = graph_checkpointer or InMemorySaver()
        self.graph = self._build_graph()

    @property
    def graph_config(self) -> dict[str, Any]:
        return {"configurable": {"thread_id": self.state.session_id}}

    async def cloud_call(
        self,
        task: str,
        context: list[dict] | None,
        model_alias: str,
    ) -> str:
        client = AsyncOpenAI(base_url=self.litellm_base_url, api_key="not-needed")
        system = self.persona.get_system_prompt() if self.persona.current else (
            "You are a senior software architect. Return an accurate, executable, "
            "well-structured response."
        )
        messages = [{"role": "system", "content": system}]
        messages.extend(context or [])
        messages.append({"role": "user", "content": task})
        try:
            response = await client.chat.completions.create(
                model=model_alias,
                messages=messages,
                temperature=self.persona.get_temperature() if self.persona.current else 0.4,
                max_tokens=4096,
            )
            return response.choices[0].message.content or "[ERROR] Empty cloud response"
        except Exception as exc:
            logger.exception("Cloud call failed for %s", model_alias)
            return f"[ERROR] {model_alias} failed: {exc}"

    async def result_hook(self, result: dict[str, Any]) -> None:
        response = result.get("final_response", "")
        routing = result.get("routing", {})
        alias = result.get("model_alias", "semantic-cache")
        if response:
            self.history.add_message(
                "assistant",
                response,
                metadata={
                    "handler": alias,
                    "routing": routing,
                    "escalation_reason": result.get("escalation_reason", ""),
                    "approval_action": result.get("approval_action", ""),
                    "graph_runtime": True,
                },
            )

        self.state.conversation_history = self.history.get_context()
        self.state.increment_step()
        self.checkpoint.save_checkpoint(
            self.state,
            CheckpointType.MILESTONE,
            label="graph-task-complete",
        )
        await self.events.publish(
            Event(
                type=EventType.AGENT_RESPONSE,
                source="graph-orchestrator",
                payload={
                    "session_id": self.state.session_id,
                    "response": response[:500],
                    "model_alias": alias,
                    "routing": routing,
                    "approval_action": result.get("approval_action", ""),
                },
            )
        )

    def _build_graph(self):
        return create_orchestration_graph(
            OrchestrationDependencies(
                router=self.router,
                worker=self.worker,
                cloud_call=self.cloud_call,
                context_provider=self.history.get_context,
                cache_get=self.cache.get,
                cache_put=self.cache.put,
                result_hook=self.result_hook,
            ),
            checkpointer=self.graph_checkpointer,
        )

    @staticmethod
    def _normalize_result(result: dict[str, Any]) -> dict[str, Any]:
        interrupts = result.get("__interrupt__") or ()
        if interrupts:
            first = interrupts[0]
            value = getattr(first, "value", first)
            return {
                **{k: v for k, v in result.items() if k != "__interrupt__"},
                "status": "pending_approval",
                "approved": None,
                "interrupt": value,
            }
        return {**result, "status": "completed"}

    def reset(self) -> None:
        self.history.clear()
        self.state = AgentState()
        self.graph_checkpointer = InMemorySaver()
        self.graph = self._build_graph()

    async def invoke(self, request: str) -> dict[str, Any]:
        self.history.add_message("user", request)
        self.state.increment_turn()
        result = await self.graph.ainvoke(
            {"request": request},
            config=self.graph_config,
        )
        return self._normalize_result(result)

    async def resume(
        self,
        action: str,
        modified_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_action = action.strip().lower()
        if normalized_action not in {"approve", "reject", "modify"}:
            raise ValueError("action must be one of: approve, reject, modify")
        result = await self.graph.ainvoke(
            Command(
                resume={
                    "action": normalized_action,
                    "modified_data": modified_data or {},
                }
            ),
            config=self.graph_config,
        )
        return self._normalize_result(result)

    async def graph_state(self) -> dict[str, Any]:
        snapshot = await self.graph.aget_state(self.graph_config)
        interrupts: list[Any] = []
        for task in snapshot.tasks or ():
            for item in getattr(task, "interrupts", ()):
                interrupts.append(getattr(item, "value", item))
        return {
            "values": dict(snapshot.values or {}),
            "next": list(snapshot.next or ()),
            "pending_interrupts": interrupts,
            "status": "pending_approval" if interrupts else "idle",
        }
