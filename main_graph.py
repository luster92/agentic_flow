"""Graph-native Clawflow CLI using the shared runtime."""

from __future__ import annotations

import asyncio
import logging
import os

from dotenv import load_dotenv

from agents.router import Router
from agents.worker import Worker
from core.checkpoint import CheckpointManager
from core.config_loader import ConfigLoader
from core.event_bus import Event, EventBus, EventType
from core.runtime import GraphRuntime
from core.state import AgentState
from engine.hitl import HITLManager
from engine.persona import PersonaManager
from utils.history_manager import HistoryManager
from utils.key_manager import ensure_api_keys
from utils.semantic_cache import SemanticCache

LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "http://localhost:4000")
HISTORY_DIR = os.getenv("HISTORY_DIR", "history")
CONTEXT_WINDOW = int(os.getenv("CONTEXT_WINDOW_SIZE", "20"))


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
        litellm_base_url=LITELLM_BASE_URL,
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
                print("Request stopped by the approval gate. Use the API or legacy CLI to resume HITL.")
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
