"""
AgenticFlow MCP Server — OpenClaw 통합용 상주형 서버
====================================================
FastMCP 기반의 MCP(Model Context Protocol) 서버입니다.
OpenClaw가 표준 프로토콜로 에이전트를 호출할 수 있게 합니다.

핵심 특징:
- 서버 시작 시 모델 warm-up (콜드 스타트 제거)
- 세션 기반 상태 관리 (사고 과정 유지)
- EventBus 연동 실시간 진행 상황 스트리밍
- 비동기 처리 (서버 논블로킹)

실행:
    python server.py                    # stdio 모드 (OpenClaw 연동)
    python server.py --transport sse    # SSE 모드 (디버깅용)
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import yaml
from dotenv import load_dotenv

from core.engine_mlx import MLXEngine, MLXConfig, EngineBackend
from core.event_bus import EventBus, Event, EventType
from utils.hardware_probe import HardwareProbe

# ── 환경 설정 ─────────────────────────────────────────────────
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-7s │ %(name)-20s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("mcp-server")

# ── 세션 데이터 ───────────────────────────────────────────────

@dataclass
class AgentSession:
    """에이전트 세션 상태."""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    topic: str = ""
    mode: str = "research"
    status: str = "idle"
    thought_trace: list[dict[str, Any]] = field(default_factory=list)
    result: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    step_count: int = 0

    def add_thought(self, step: str, content: str) -> None:
        """사고 과정을 기록합니다."""
        self.thought_trace.append({
            "step": step,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self.step_count += 1

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 딕셔너리."""
        return {
            "session_id": self.session_id,
            "topic": self.topic,
            "mode": self.mode,
            "status": self.status,
            "step_count": self.step_count,
            "created_at": self.created_at,
        }


# ── 서버 초기화 ───────────────────────────────────────────────

# 전역 상태
engine: MLXEngine | None = None
event_bus: EventBus | None = None
sessions: dict[str, AgentSession] = {}
probe = HardwareProbe()


def _load_mlx_config() -> MLXConfig:
    """config/m4_32gb.yaml에서 MLX 설정을 로드합니다."""
    config_path = os.path.join(
        os.path.dirname(__file__), "config", "m4_32gb.yaml"
    )
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            mlx_data = data.get("mlx", {})
            return MLXConfig.from_dict(mlx_data)
        except Exception as e:
            logger.warning(f"⚠️ Config load failed, using defaults: {e}")
    return MLXConfig()


# ── Lifecycle (lifespan context manager) ─────────────────────

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator


@asynccontextmanager
async def server_lifespan(app: "FastMCP") -> AsyncIterator[None]:  # type: ignore[name-defined]
    """서버 시작/종료 시 모델 로드/언로드."""
    global engine, event_bus

    logger.info("🚀 AgenticFlow MCP Server starting...")

    # 하드웨어 진단
    summary = probe.get_summary()
    logger.info(
        f"🔍 Hardware: {summary['chip']['brand']} | "
        f"RAM: {summary['memory']['total_gb']}GB | "
        f"GPU: {summary['chip']['gpu_cores']} cores"
    )

    # 이벤트 버스 초기화
    EventBus.reset()
    event_bus = EventBus()
    await event_bus.start()

    # MLX 엔진 초기화
    config = _load_mlx_config()
    engine = MLXEngine(
        config=config,
        litellm_base_url=os.getenv(
            "LITELLM_BASE_URL", "http://localhost:4000"
        ),
    )
    await engine.load()

    logger.info(
        f"✅ MCP Server ready | Backend: {engine.backend.value} | "
        f"Model: {config.main_model}"
    )

    yield  # 서버 실행 중

    # Shutdown
    if engine:
        await engine.unload()
    if event_bus:
        await event_bus.stop()
    logger.info("👋 MCP Server stopped")


# ── FastMCP 서버 인스턴스 ─────────────────────────────────────

try:
    from fastmcp import FastMCP  # type: ignore[import-untyped]
    mcp = FastMCP(
        "AgenticFlow-M4",
        instructions=(
            "AgenticFlow는 Mac Mini M4에서 구동되는 고성능 로컬 AI 에이전트입니다. "
            "심층 분석, 코드 리팩토링, 복잡한 계획 수립에 적합합니다. "
            "단순 질문에는 사용하지 마세요."
        ),
        lifespan=server_lifespan,
    )
    _MCP_AVAILABLE = True
except ImportError:
    mcp = None  # type: ignore[assignment]
    _MCP_AVAILABLE = False
    logger.warning("⚠️ fastmcp not installed — MCP server disabled")


# ── MCP Tools ─────────────────────────────────────────────────

@mcp.tool()
async def run_flow(
    topic: str,
    mode: str = "research",
    max_tokens: int = 2048,
) -> str:
    """에이전트 플로우를 실행합니다.

    Args:
        topic: 작업 주제 또는 질문
        mode: 실행 모드 (research | code | plan | analyze)
        max_tokens: 최대 생성 토큰 수

    Returns:
        에이전트의 최종 응답
    """
    if not engine:
        return "[ERROR] Engine not initialized"

    # 세션 생성
    session = AgentSession(topic=topic, mode=mode)
    sessions[session.session_id] = session
    session.status = "running"

    # 사고 과정 기록
    session.add_thought("init", f"Starting {mode} flow: {topic}")

    # 시스템 프롬프트 구성
    system_prompts: dict[str, str] = {
        "research": (
            "You are a senior research analyst. Analyze the given topic "
            "thoroughly with structured insights, pros/cons, and "
            "actionable recommendations."
        ),
        "code": (
            "You are an expert software engineer specializing in "
            "Python and TypeScript. Write clean, well-documented, "
            "production-ready code with proper error handling."
        ),
        "plan": (
            "You are a strategic project planner. Create detailed, "
            "phased implementation plans with timelines, dependencies, "
            "and risk assessments."
        ),
        "analyze": (
            "You are a systems analyst. Perform deep analysis of the "
            "given topic covering architecture, performance, security, "
            "and scalability aspects."
        ),
    }
    system_prompt = system_prompts.get(
        mode, system_prompts["research"]
    )

    session.add_thought("routing", f"Using {mode} system prompt")

    # 메모리 압박 체크
    if probe.should_fallback():
        session.add_thought(
            "warning",
            "Memory pressure detected — response may be shorter"
        )
        max_tokens = min(max_tokens, 1024)

    # 추론 실행
    session.add_thought("inference", "Generating response...")

    try:
        result = await engine.generate(
            prompt=topic,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
        )

        session.result = result.text
        session.status = "completed"
        session.add_thought(
            "done",
            f"Generated {result.tokens_generated} tokens "
            f"({result.tokens_per_second} tok/s, "
            f"{result.elapsed_ms:.0f}ms) "
            f"[{result.backend.value}]"
        )

        # 이벤트 발행
        if event_bus:
            await event_bus.publish(Event(
                type=EventType.AGENT_RESPONSE,
                source="mcp-server",
                payload={
                    "session_id": session.session_id,
                    "tokens": result.tokens_generated,
                    "tps": result.tokens_per_second,
                    "backend": result.backend.value,
                },
            ))

        return result.text

    except Exception as e:
        session.status = "failed"
        session.add_thought("error", str(e))
        logger.error(f"❌ Flow execution failed: {e}")
        return f"[ERROR] Flow execution failed: {e}"


@mcp.tool()
async def get_status(session_id: str) -> str:
    """세션 상태를 조회합니다.

    Args:
        session_id: 세션 UUID

    Returns:
        세션 상태 JSON 문자열
    """
    import json

    session = sessions.get(session_id)
    if not session:
        return json.dumps({"error": f"Session {session_id} not found"})

    return json.dumps(session.to_dict(), indent=2, ensure_ascii=False)


@mcp.tool()
async def get_thought_trace(
    session_id: str,
    limit: int = 20,
) -> str:
    """에이전트의 사고 과정(Thought Trace)을 조회합니다.

    Args:
        session_id: 세션 UUID
        limit: 최대 반환 항목 수

    Returns:
        사고 과정 로그
    """
    import json

    session = sessions.get(session_id)
    if not session:
        return json.dumps({"error": f"Session {session_id} not found"})

    trace = session.thought_trace[-limit:]
    return json.dumps(trace, indent=2, ensure_ascii=False)


@mcp.tool()
async def list_sessions() -> str:
    """활성 세션 목록을 반환합니다.

    Returns:
        세션 목록 JSON 문자열
    """
    import json

    session_list = [s.to_dict() for s in sessions.values()]
    return json.dumps(session_list, indent=2, ensure_ascii=False)


@mcp.tool()
async def get_hardware_info() -> str:
    """현재 하드웨어 정보 및 모델 추천을 반환합니다.

    Returns:
        하드웨어 정보 JSON 문자열
    """
    import json

    summary = probe.get_summary()
    if engine:
        summary["engine"] = engine.get_stats()

    return json.dumps(summary, indent=2, ensure_ascii=False)


@mcp.tool()
async def clear_session(session_id: str) -> str:
    """세션을 삭제합니다.

    Args:
        session_id: 삭제할 세션 UUID

    Returns:
        삭제 결과 메시지
    """
    if session_id in sessions:
        del sessions[session_id]
        return f"Session {session_id} cleared"
    return f"Session {session_id} not found"


# ── MCP Resources ─────────────────────────────────────────────

@mcp.resource("agentic://status")  # type: ignore[misc]
async def resource_status() -> str:
    """서버 상태 리소스."""
    import json

    status: dict[str, Any] = {
        "server": "AgenticFlow-M4",
        "active_sessions": len(sessions),
        "engine_loaded": engine.is_loaded if engine else False,
        "backend": engine.backend.value if engine else "none",
    }
    return json.dumps(status, indent=2)


# ── Entry Point ───────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="AgenticFlow MCP Server (M4 Optimized)"
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="MCP transport (default: stdio for OpenClaw)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="SSE port (only for sse transport)",
    )
    args = parser.parse_args()

    logger.info(
        f"🏁 Starting MCP Server (transport: {args.transport})"
    )

    if args.transport == "sse":
        mcp.run(transport="sse", port=args.port)
    else:
        mcp.run(transport="stdio")
