"""Graph-native Clawflow CLI.

This is the migration target for ``main.py``. It runs Router, Worker,
HistoryManager, SemanticCache, checkpoint, HITL, and EventBus through the
shared LangGraph orchestration core instead of the procedural
``process_request`` function.
"""

from __future__ import annotations

import asyncio
import logging
import os

from dotenv import load_dotenv
from openai import AsyncOpenAI

from agents.router import Router
from agents.worker import Worker
from core.checkpoint import CheckpointManager
from core.config_loader import ConfigLoader
from core.event_bus import Event, EventBus, EventType
from core.graph import create_orchestration_graph
from core.orchestration_graph import OrchestrationDependencies
from core.routing_schema import RoutingDecision
from core.state import AgentState, CheckpointType
from engine.hitl import HITLManager
from engine.persona import PersonaManager
from utils.history_manager import HistoryManager
from utils.key_manager import ensure_api_keys
from utils.semantic_cache import SemanticCache

logger = logging.getLogger("clawflow.graph")

LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "http://localhost:4000")
HISTORY_DIR = os.getenv("HISTORY_DIR", "history")
CONTEXT_WINDOW = int(os.getenv("CONTEXT_WINDOW_SIZE", "20"))


class GraphRuntime:
    """Owns graph adapters and mutable CLI session state."""

    def __init__(
        self,
        router: Router,
        worker: Worker,
        history: HistoryManager,
        state: AgentState,
        cache: SemanticCache,
        checkpoint: CheckpointManager,
        hitl: HITLManager,
        persona: PersonaManager,
        events: EventBus,
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
        self.graph = self._build_graph()

    async def cloud_call(
        self,
        task: str,
        context: list[dict] | None,
        model_alias: str,
    ) -> str:
        client = AsyncOpenAI(base_url=LITELLM_BASE_URL, api_key="not-needed")
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

    async def result_hook(self, result: dict) -> None:
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

    async def invoke(self, request: str) -> dict:
        self.history.add_message("user", request)
        self.state.increment_turn()
        return await self.graph.ainvoke({"request": request})


async def main() -> None:
    ensure_api_keys()
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s │ %(levelname)-7s │ %(name)-22s │ %(message)s",
    )
    os.makedirs(HISTORY_DIR, exist_ok=True)

    config_loader = ConfigLoader()
    router = Router(base_url=LITELLM_BASE_URL)
    worker = Worker(base_url=LITELLM_BASE_URL)
    history = HistoryManager(
        project_name="default",
        base_dir=HISTORY_DIR,
        context_window=CONTEXT_WINDOW,
    )
    state = AgentState()
    cache = SemanticCache()
    checkpoint = CheckpointManager(db_dir=HISTORY_DIR)
    persona = PersonaManager(config_loader=config_loader)
    hitl = HITLManager(checkpoint_manager=checkpoint)
    events = EventBus()
    await events.start()

    runtime = GraphRuntime(
        router=router,
        worker=worker,
        history=history,
        state=state,
        cache=cache,
        checkpoint=checkpoint,
        hitl=hitl,
        persona=persona,
        events=events,
    )

    await events.publish(
        Event(
            type=EventType.SESSION_START,
            source="graph-runtime",
            payload={"session_id": state.session_id, "proxy_url": LITELLM_BASE_URL},
        )
    )

    print("Clawflow Graph Runtime")
    print("Commands: /exit, /clear, /status")
    try:
        while True:
            request = (await asyncio.to_thread(input, "\nYou > ")).strip()
            if not request:
                continue
            if request in {"/exit", "/quit"}:
                break
            if request == "/clear":
                runtime.reset()
                print("Session cleared.")
                continue
            if request == "/status":
                print(
                    f"session={runtime.state.session_id[:8]} "
                    f"turn={runtime.state.turn_number} step={runtime.state.step}"
                )
                continue

            result = await runtime.invoke(request)
            response = result.get("final_response") or result.get("error") or "[ERROR] No response"
            print(f"\nAssistant > {response}")
            if result.get("approved") is False:
                print("Request stopped by the approval gate. Use the legacy CLI to resume HITL.")
    finally:
        await events.publish(
            Event(
                type=EventType.SESSION_END,
                source="graph-runtime",
                payload={"session_id": runtime.state.session_id},
            )
        )
        await events.stop()


if __name__ == "__main__":
    asyncio.run(main())
