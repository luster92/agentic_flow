"""Shared graph runtime used by CLI and API transports."""

from __future__ import annotations

import logging
import os
from typing import Any

from openai import AsyncOpenAI

from agents.router import Router
from agents.worker import Worker
from core.checkpoint import CheckpointManager
from core.event_bus import Event, EventBus, EventType
from core.graph import create_orchestration_graph
from core.orchestration_graph import OrchestrationDependencies
from core.routing_schema import RoutingDecision
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
        self.graph = self._build_graph()

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

    async def approval_check(self, decision: RoutingDecision, request: str) -> bool:
        if not decision.requires_human_approval:
            return True
        await self.hitl.suspend(
            self.state,
            decision.reason or "High-risk operation requires approval",
            {"request": request[:500], "routing": decision.model_dump(mode="json")},
        )
        return False

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
                approval_check=self.approval_check,
                result_hook=self.result_hook,
            )
        )

    def reset(self) -> None:
        self.history.clear()
        self.state = AgentState()
        self.graph = self._build_graph()

    async def invoke(self, request: str) -> dict[str, Any]:
        self.history.add_message("user", request)
        self.state.increment_turn()
        return await self.graph.ainvoke({"request": request})
