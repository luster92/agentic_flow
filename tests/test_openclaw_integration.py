"""
Tests for OpenClaw Integration Improvements (Phases 1-6)
==========================================================
이벤트 버스, 샌드박스, 모델 라우터, 구조화 로거,
SOUL/MEMORY 관리, 승인 채널 추상화를 테스트합니다.
"""

import asyncio
import os
import tempfile
import shutil
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# ── Phase 1: EventBus ─────────────────────────────────────────

from core.event_bus import EventBus, Event, EventType


class TestEventBus:
    """이벤트 버스 테스트."""

    def setup_method(self) -> None:
        """각 테스트 전 싱글톤 리셋."""
        EventBus.reset()

    def teardown_method(self) -> None:
        """각 테스트 후 싱글톤 리셋."""
        EventBus.reset()

    def test_singleton(self) -> None:
        """싱글톤 패턴 검증."""
        bus1 = EventBus()
        bus2 = EventBus()
        assert bus1 is bus2

    def test_event_creation(self) -> None:
        """이벤트 생성 및 직렬화."""
        event = Event(
            type=EventType.USER_MESSAGE,
            source="user",
            payload={"text": "hello"},
        )
        assert event.type == EventType.USER_MESSAGE
        assert event.source == "user"
        assert "text" in event.payload

        d = event.to_dict()
        assert d["type"] == "user_message"
        assert d["source"] == "user"

    def test_subscribe_unsubscribe(self) -> None:
        """구독 및 해제."""
        bus = EventBus()

        async def handler(event: Event) -> None:
            pass

        sub_id = bus.subscribe(EventType.USER_MESSAGE, handler)
        assert bus.subscription_count == 1

        bus.unsubscribe(sub_id)
        assert bus.subscription_count == 0

    @pytest.mark.asyncio
    async def test_publish_and_consume(self) -> None:
        """발행 → 구독자 수신 검증."""
        bus = EventBus()
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        bus.subscribe(EventType.THINKING, handler)
        await bus.start()

        await bus.publish(Event(
            type=EventType.THINKING,
            source="test",
            payload={"msg": "hello"},
        ))

        # 소비자 루프가 이벤트를 처리할 시간
        await asyncio.sleep(0.1)

        assert len(received) == 1
        assert received[0].payload["msg"] == "hello"

        await bus.stop()

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self) -> None:
        """다중 구독자 테스트."""
        bus = EventBus()
        counts = {"a": 0, "b": 0}

        async def handler_a(event: Event) -> None:
            counts["a"] += 1

        async def handler_b(event: Event) -> None:
            counts["b"] += 1

        bus.subscribe(EventType.DECISION, handler_a)
        bus.subscribe(EventType.DECISION, handler_b)
        await bus.start()

        await bus.publish(Event(
            type=EventType.DECISION,
            source="test",
            payload={},
        ))
        await asyncio.sleep(0.1)

        assert counts["a"] == 1
        assert counts["b"] == 1
        await bus.stop()

    @pytest.mark.asyncio
    async def test_type_filtering(self) -> None:
        """다른 타입의 이벤트는 수신하지 않음."""
        bus = EventBus()
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        bus.subscribe(EventType.ERROR, handler)
        await bus.start()

        # THINKING 이벤트 발행 (ERROR 구독자는 무시해야 함)
        await bus.publish(Event(
            type=EventType.THINKING,
            source="test",
            payload={},
        ))
        await asyncio.sleep(0.1)

        assert len(received) == 0
        await bus.stop()

    def test_event_log(self) -> None:
        """이벤트 로그 조회."""
        bus = EventBus()
        assert len(bus.get_event_log()) == 0

    def test_event_types_completeness(self) -> None:
        """모든 필수 이벤트 타입이 정의되어 있는지."""
        required = {
            "user_message", "agent_response", "thinking",
            "decision", "tool_call", "tool_result",
            "approval_request", "approval_response",
        }
        actual = {e.value for e in EventType}
        assert required.issubset(actual)


# ── Phase 2: Sandbox ──────────────────────────────────────────

from core.sandbox import SandboxManager, SandboxPolicy


class TestSandbox:
    """샌드박스 보안 검증 테스트."""

    def test_default_policy(self) -> None:
        """기본 정책 생성."""
        policy = SandboxPolicy()
        assert policy.enabled is True
        assert policy.max_execution_time == 30
        assert len(policy.blocked_commands) > 0

    def test_path_validation_allowed(self) -> None:
        """작업 디렉토리 내 경로 허용."""
        sandbox = SandboxManager()
        cwd = os.getcwd()
        result = sandbox.validate_path(
            os.path.join(cwd, "test.py"), mode="read"
        )
        assert result.allowed is True

    def test_path_validation_blocked(self) -> None:
        """작업 디렉토리 외부 경로 차단."""
        sandbox = SandboxManager()
        result = sandbox.validate_path(
            "/etc/passwd", mode="read"
        )
        assert result.allowed is False

    def test_command_validation_allowed(self) -> None:
        """안전한 명령어 허용."""
        sandbox = SandboxManager()
        result = sandbox.validate_command("ls -la")
        assert result.allowed is True

    def test_command_validation_blocked(self) -> None:
        """위험 명령어 차단."""
        sandbox = SandboxManager()
        result = sandbox.validate_command("rm -rf /")
        assert not result.allowed

    def test_disabled_sandbox(self) -> None:
        """샌드박스 비활성화 시 모든 것 허용."""
        policy = SandboxPolicy(enabled=False)
        sandbox = SandboxManager(policy=policy)
        result = sandbox.validate_path(
            "/etc/passwd", mode="read"
        )
        assert result.allowed is True

    def test_from_config(self) -> None:
        """설정 딕셔너리에서 생성."""
        config = {
            "sandbox_enabled": True,
            "allowed_read_paths": ["."],
            "blocked_commands": ["rm -rf"],
            "max_execution_time": 60,
        }
        sandbox = SandboxManager.from_config(config)
        assert sandbox.policy.max_execution_time == 60

    def test_policy_summary(self) -> None:
        """정책 요약 출력."""
        sandbox = SandboxManager()
        summary = sandbox.get_policy_summary()
        assert "enabled" in summary
        assert "read_paths" in summary
        assert "blocked_commands" in summary


# ── Phase 3: ModelRouter ──────────────────────────────────────

from core.model_router import (
    ModelRouter, TaskTier, CostTracker, CostRecord,
)


class TestModelRouter:
    """모델 라우터 테스트."""

    def test_classify_simple(self) -> None:
        """SIMPLE 작업 분류."""
        router = ModelRouter()
        tier = router.classify_tier("이 코드를 요약해줘")
        assert tier == TaskTier.SIMPLE

    def test_classify_standard(self) -> None:
        """STANDARD 작업 분류."""
        router = ModelRouter()
        tier = router.classify_tier(
            "인증 모듈에 JWT 로직을 구현해줘"
        )
        assert tier == TaskTier.STANDARD

    def test_classify_complex(self) -> None:
        """COMPLEX 작업 분류."""
        router = ModelRouter()
        tier = router.classify_tier(
            "전체 시스템 아키텍처를 재설계해줘"
        )
        assert tier == TaskTier.COMPLEX

    def test_cloud_route_minimum_standard(self) -> None:
        """CLOUD 라우팅 시 최소 STANDARD."""
        router = ModelRouter()
        tier = router.classify_tier("hello", route="CLOUD")
        assert tier in (TaskTier.STANDARD, TaskTier.COMPLEX)

    def test_get_model_for_tier(self) -> None:
        """티어별 모델 반환."""
        router = ModelRouter()
        assert "helper" in router.get_model_for_tier(
            TaskTier.SIMPLE
        )
        assert "worker" in router.get_model_for_tier(
            TaskTier.STANDARD
        )

    def test_cost_estimation(self) -> None:
        """비용 추정."""
        router = ModelRouter()
        cost = router.estimate_cost(
            "cloud-pm-gemini",
            input_tokens=1000,
            output_tokens=500,
        )
        assert cost > 0

    def test_cost_tracking(self) -> None:
        """누적 비용 추적."""
        router = ModelRouter()
        record = router.track_usage(
            model="cloud-pm-gemini",
            tier=TaskTier.COMPLEX,
            input_tokens=1000,
            output_tokens=500,
        )
        assert record.estimated_cost_usd > 0
        assert router.cost_tracker.total_calls == 1

    def test_cost_tracker_summary(self) -> None:
        """비용 요약."""
        tracker = CostTracker(alert_threshold_usd=0.01)
        tracker.add_record(CostRecord(
            model="test",
            tier=TaskTier.SIMPLE,
            input_tokens=100,
            output_tokens=50,
            estimated_cost_usd=0.005,
        ))
        summary = tracker.get_summary()
        assert summary["total_calls"] == 1
        assert summary["total_cost_usd"] == 0.005

    def test_disabled_router(self) -> None:
        """비활성화 시 항상 STANDARD."""
        router = ModelRouter(config={"enabled": False})
        tier = router.classify_tier("아키텍처 설계")
        assert tier == TaskTier.STANDARD


# ── Phase 4: StructuredLogger ─────────────────────────────────

from utils.structured_logger import StructuredLogger, StructuredEvent


class TestStructuredLogger:
    """구조화 로거 테스트."""

    def test_event_creation(self) -> None:
        """이벤트 생성."""
        event = StructuredEvent(
            event_type="thought",
            source="router",
            content="Analyzing task complexity",
        )
        assert event.event_type == "thought"
        jsonl = event.to_jsonl()
        assert "thought" in jsonl

    def test_logger_thought(self) -> None:
        """thought 이벤트 기록."""
        with tempfile.TemporaryDirectory() as tmpdir:
            slogger = StructuredLogger(
                log_dir=tmpdir, session_id="test"
            )
            slogger.thought("router", "Analyzing input")
            assert slogger.event_count == 1

    def test_logger_tool_call(self) -> None:
        """tool_call 이벤트 기록."""
        with tempfile.TemporaryDirectory() as tmpdir:
            slogger = StructuredLogger(
                log_dir=tmpdir, session_id="test"
            )
            slogger.tool_call(
                "read_file",
                {"path": "main.py"},
                result="file content...",
            )
            assert slogger.event_count == 1

    def test_logger_decision(self) -> None:
        """decision 이벤트 기록."""
        with tempfile.TemporaryDirectory() as tmpdir:
            slogger = StructuredLogger(
                log_dir=tmpdir, session_id="test"
            )
            slogger.decision("router", "LOCAL", "Simple task")
            assert slogger.event_count == 1

    def test_logger_jsonl_output(self) -> None:
        """JSONL 파일 출력 검증."""
        with tempfile.TemporaryDirectory() as tmpdir:
            slogger = StructuredLogger(
                log_dir=tmpdir, session_id="test"
            )
            slogger.thought("test", "msg1")
            slogger.error("test", "err1")

            log_file = Path(tmpdir) / "session_test.jsonl"
            assert log_file.exists()
            lines = log_file.read_text().strip().split("\n")
            assert len(lines) == 2

    def test_get_trace(self) -> None:
        """트레이스 조회."""
        with tempfile.TemporaryDirectory() as tmpdir:
            slogger = StructuredLogger(
                log_dir=tmpdir, session_id="test"
            )
            slogger.thought("router", "step1")
            slogger.decision("router", "LOCAL", "simple")
            slogger.metric("tokens", 150, "tok")

            trace = slogger.get_trace()
            assert len(trace) == 3

            # 필터링
            decisions = slogger.get_trace(event_type="decision")
            assert len(decisions) == 1


# ── Phase 5: SOUL/MEMORY ─────────────────────────────────────

from engine.soul import SoulManager
from engine.memory_file import MemoryFileManager, MemoryEntry


class TestSoulManager:
    """SOUL.md 관리자 테스트."""

    def test_parse_sections(self) -> None:
        """섹션 파싱."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False,
            encoding="utf-8",
        ) as f:
            f.write(
                "# Personality\n"
                "친절한 시니어 엔지니어\n\n"
                "# Tone\n"
                "- 존댓말 사용\n"
                "- 기술 용어는 한국어 우선\n\n"
                "# Principles\n"
                "1. 정확성 최우선\n"
                "2. 보안 고려\n"
            )
            f.flush()
            path = f.name

        try:
            soul = SoulManager(soul_path=path)
            assert soul.is_loaded
            assert "친절" in soul.personality
            assert "존댓말" in soul.tone
            assert "정확성" in soul.principles
        finally:
            os.unlink(path)

    def test_inject_into_prompt(self) -> None:
        """프롬프트 주입."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False,
            encoding="utf-8",
        ) as f:
            f.write("# Personality\nHelperful AI\n")
            f.flush()
            path = f.name

        try:
            soul = SoulManager(soul_path=path)
            result = soul.inject_into_prompt("You are an AI.")
            assert "You are an AI." in result
            assert "SOUL" in result
            assert "Helperful AI" in result
        finally:
            os.unlink(path)

    def test_no_soul_file(self) -> None:
        """파일 없을 때 정상 동작."""
        soul = SoulManager(soul_path="/nonexistent/SOUL.md")
        assert not soul.is_loaded
        result = soul.inject_into_prompt("base prompt")
        assert result == "base prompt"


class TestMemoryFileManager:
    """MEMORY.md 관리자 테스트."""

    def test_parse_memories(self) -> None:
        """메모리 파싱."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False,
            encoding="utf-8",
        ) as f:
            f.write(
                "## 2026-02-19\n"
                "- **user_pref**: 한국어 주석 선호\n"
                "- **debug**: SQLite WAL 모드 사용\n\n"
                "## 2026-02-18\n"
                "- **setup**: Next.js 14 초기화\n"
            )
            f.flush()
            path = f.name

        try:
            mem = MemoryFileManager(memory_path=path)
            assert mem.is_loaded
            assert mem.entry_count == 3
        finally:
            os.unlink(path)

    def test_search(self) -> None:
        """키워드 검색."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False,
            encoding="utf-8",
        ) as f:
            f.write(
                "## 2026-02-19\n"
                "- **python**: Python 가상환경 설정\n"
                "- **docker**: Docker Compose 사용\n"
                "- **python_debug**: pdb 대신 breakpoint 사용\n"
            )
            f.flush()
            path = f.name

        try:
            mem = MemoryFileManager(memory_path=path)
            results = mem.search("python")
            assert len(results) >= 1
            assert any("python" in r.lower() for r in results)
        finally:
            os.unlink(path)

    def test_add_memory(self) -> None:
        """메모리 추가 및 파일 쓰기."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "MEMORY.md")
            mem = MemoryFileManager(memory_path=path)
            mem.add_memory("test_key", "test value")

            assert mem.entry_count == 1
            assert Path(path).exists()

            content = Path(path).read_text(encoding="utf-8")
            assert "test_key" in content
            assert "test value" in content

    def test_no_memory_file(self) -> None:
        """파일 없을 때 정상 동작."""
        mem = MemoryFileManager(
            memory_path="/nonexistent/MEMORY.md"
        )
        assert not mem.is_loaded
        assert mem.entry_count == 0
        assert mem.search("anything") == []

    def test_summary(self) -> None:
        """상태 요약."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "MEMORY.md")
            mem = MemoryFileManager(memory_path=path)
            mem.add_memory("k1", "v1")
            mem.add_memory("k2", "v2")

            summary = mem.get_summary()
            assert summary["total_entries"] == 2


# ── Phase 6: ApprovalChannel ─────────────────────────────────

from gateway.approval_bridge import (
    CLIApprovalChannel,
    CallbackApprovalChannel,
    ApprovalResult,
)


class TestCLIApprovalChannel:
    """CLI 승인 채널 테스트."""

    @pytest.mark.asyncio
    async def test_approve_flow(self) -> None:
        """승인 흐름."""
        channel = CLIApprovalChannel()
        await channel.request_approval(
            "Test reason", {"fn": "test"},
        )
        assert channel.has_pending

        # 비동기 승인 응답
        channel.respond("approve")

        result = await channel.wait_for_response(timeout=5)
        assert result.approved is True
        assert result.action == "approve"

    @pytest.mark.asyncio
    async def test_reject_flow(self) -> None:
        """거절 흐름."""
        channel = CLIApprovalChannel()
        await channel.request_approval("Dangerous", {})
        channel.respond("reject", reason="Too risky")

        result = await channel.wait_for_response(timeout=5)
        assert result.approved is False
        assert result.action == "reject"

    @pytest.mark.asyncio
    async def test_timeout(self) -> None:
        """타임아웃 자동 거절."""
        channel = CLIApprovalChannel()
        await channel.request_approval("Timeout test", {})

        result = await channel.wait_for_response(timeout=1)
        assert result.approved is False
        assert result.action == "timeout"


class TestCallbackApprovalChannel:
    """콜백 승인 채널 테스트."""

    @pytest.mark.asyncio
    async def test_callback_approve(self) -> None:
        """콜백 승인 흐름."""
        channel = CallbackApprovalChannel(
            auto_reject_timeout=10,
        )
        await channel.request_approval("Test", {})

        # 비동기로 응답 제출
        asyncio.get_event_loop().call_later(
            0.1,
            lambda: asyncio.create_task(
                channel.submit_response(True, "LGTM")
            ),
        )

        result = await channel.wait_for_response(timeout=5)
        assert result.approved is True

    @pytest.mark.asyncio
    async def test_callback_timeout(self) -> None:
        """콜백 타임아웃."""
        channel = CallbackApprovalChannel(
            auto_reject_timeout=1,
        )
        await channel.request_approval("Timeout", {})

        result = await channel.wait_for_response()
        assert result.approved is False
        assert result.action == "timeout"
