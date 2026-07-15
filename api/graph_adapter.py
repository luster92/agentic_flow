"""FastAPI adapter for the shared Clawflow graph runtime."""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass, field
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

from agents.router import Router
from agents.worker import Worker
from core.checkpoint import CheckpointManager
from core.config_loader import ConfigLoader
from core.event_bus import EventBus
from core.runtime import GraphRuntime
from core.state import AgentState
from engine.hitl import HITLManager
from engine.persona import PersonaManager
from utils.history_manager import HistoryManager
from utils.semantic_cache import SemanticCache

_SAFE_SESSION = re.compile(r"[^a-zA-Z0-9_.-]+")


@dataclass(slots=True)
class GraphSessionRegistry:
    """Create and retain one isolated GraphRuntime per API conversation."""

    history_dir: str = field(default_factory=lambda: os.getenv("HISTORY_DIR", "history"))
    context_window: int = field(
        default_factory=lambda: int(os.getenv("CONTEXT_WINDOW_SIZE", "20"))
    )
    litellm_base_url: str = field(
        default_factory=lambda: os.getenv("LITELLM_BASE_URL", "http://localhost:4000")
    )
    router: Router | None = None
    worker: Worker | None = None
    cache: SemanticCache | None = None
    checkpoint: CheckpointManager | None = None
    events: EventBus | None = None
    graph_checkpointer: Any | None = None
    _sessions: dict[str, GraphRuntime] = field(default_factory=dict, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    async def start(self, pg_pool: AsyncConnectionPool | None = None) -> None:
        os.makedirs(self.history_dir, exist_ok=True)
        self.router = self.router or Router(base_url=self.litellm_base_url)
        self.worker = self.worker or Worker(base_url=self.litellm_base_url)
        self.cache = self.cache or SemanticCache()
        self.checkpoint = self.checkpoint or CheckpointManager(db_dir=self.history_dir)
        self.events = self.events or EventBus()
        if self.graph_checkpointer is None and pg_pool is not None:
            self.graph_checkpointer = AsyncPostgresSaver(pg_pool)
            await self.graph_checkpointer.setup()
        await self.events.start()

    async def close(self) -> None:
        if self.events:
            await self.events.stop()
        self._sessions.clear()

    async def get(self, thread_id: str) -> GraphRuntime:
        session_key = self._normalize_thread_id(thread_id)
        existing = self._sessions.get(session_key)
        if existing:
            return existing

        async with self._lock:
            existing = self._sessions.get(session_key)
            if existing:
                return existing
            runtime = self._create_runtime(session_key)
            self._sessions[session_key] = runtime
            return runtime

    async def invoke(self, thread_id: str, request: str) -> dict[str, Any]:
        runtime = await self.get(thread_id)
        return await runtime.invoke(request)

    async def resume(
        self,
        thread_id: str,
        action: str,
        modified_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        runtime = await self.get(thread_id)
        return await runtime.resume(action, modified_data)

    async def state(self, thread_id: str) -> dict[str, Any]:
        runtime = await self.get(thread_id)
        graph_state = await runtime.graph_state()
        return {
            "session": runtime.state.model_dump(mode="json"),
            "graph": graph_state,
        }

    def _create_runtime(self, session_key: str) -> GraphRuntime:
        if not all((self.router, self.worker, self.cache, self.checkpoint, self.events)):
            raise RuntimeError("GraphSessionRegistry.start() must run before use")

        history = HistoryManager(
            project_name=f"api-{session_key}",
            base_dir=self.history_dir,
            context_window=self.context_window,
        )
        state = AgentState(session_id=session_key)
        config_loader = ConfigLoader()
        persona = PersonaManager(config_loader=config_loader)
        hitl = HITLManager(checkpoint_manager=self.checkpoint)
        return GraphRuntime(
            router=self.router,
            worker=self.worker,
            history=history,
            state=state,
            cache=self.cache,
            checkpoint=self.checkpoint,
            hitl=hitl,
            persona=persona,
            events=self.events,
            litellm_base_url=self.litellm_base_url,
            graph_checkpointer=self.graph_checkpointer,
        )

    @staticmethod
    def _normalize_thread_id(thread_id: str) -> str:
        raw_thread_id = thread_id.strip()
        if not _SAFE_SESSION.sub("", raw_thread_id):
            raise ValueError("thread_id must contain at least one valid character")
        normalized = _SAFE_SESSION.sub("-", raw_thread_id)[:100]
        return normalized
