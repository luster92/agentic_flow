"""Graph-native Clawflow CLI using the shared runtime."""

from __future__ import annotations

import asyncio
import logging
import os

from dotenv import load_dotenv

from agents.router import Router
from agents.worker import Worker
from core.checkpoint import CheckpointManager
from core.cli_controller import GraphCLIController
from core.config_loader import ConfigLoader
from core.event_bus import Event, EventBus, EventType
from core.planner import TaskPlanner
from core.runtime import GraphRuntime
from core.state import AgentState
from engine.adversarial import DebateLoop
from engine.hitl import HITLManager
from engine.persona import PersonaManager
from engine.sandbox import SandboxManager
from engine.tmux_integration import TmuxIntegration
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
    controller = GraphCLIController(
        runtime=runtime,
        history_dir=HISTORY_DIR,
        context_window=CONTEXT_WINDOW,
        planner=TaskPlanner(base_url=LITELLM_BASE_URL),
        debate=DebateLoop(persona_manager=persona, base_url=LITELLM_BASE_URL),
    )
    sandbox = SandboxManager()
    tmux_session = f"test-{state.session_id}"

    await sandbox.provision_container(state.session_id)
    await TmuxIntegration.create_session(tmux_session)
    await events.publish(
        Event(
            type=EventType.SESSION_START,
            source="graph-runtime",
            payload={"session_id": state.session_id, "proxy_url": LITELLM_BASE_URL},
        )
    )

    print("Clawflow Graph Runtime")
    print(GraphCLIController.help_text())
    print("Additional: !<command> runs in sandbox, /test <command> runs in tmux")

    try:
        while True:
            request = (await asyncio.to_thread(input, "\nYou > ")).strip()
            if not request:
                continue

            if request.startswith("!"):
                output = await sandbox.execute_in_sandbox(runtime.state.session_id, request[1:])
                print(f"\nSandbox >\n{output}")
                continue

            if request.startswith("/test "):
                command = request[6:].strip()
                await TmuxIntegration.run_test(tmux_session, command)
                await asyncio.sleep(1)
                print(f"\nTest >\n{await TmuxIntegration.get_test_output(tmux_session)}")
                continue

            command_result = await controller.handle(request)
            if command_result.handled:
                if command_result.output:
                    print(command_result.output)
                if command_result.should_exit:
                    break
                continue

            results = await controller.execute_request(request)
            for result in results:
                response = result.get("final_response") or result.get("error")
                if response:
                    print(f"\nAssistant > {response}")
                if result.get("status") == "pending_approval":
                    interrupt = result.get("interrupt") or {}
                    print(f"Approval required: {interrupt.get('reason', 'review required')}")
                    print("Use /approve, /reject, or /modify <replacement request>.")
                    break
    finally:
        try:
            await sandbox.teardown_container(runtime.state.session_id)
            await TmuxIntegration.kill_session(tmux_session)
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
