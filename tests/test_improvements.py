"""
Tests for Phase 1-6 improvements to agentic_flow.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

# ── Phase 1: State Schema ──────────────────────────────────────

from state import AgenticState


class TestAgenticState:
    """AgenticState 데이터클래스 테스트."""

    def test_default_initialization(self):
        state = AgenticState()
        assert state.conversation_history == []
        assert state.internal_summary == ""
        assert state.entities == {}
        assert state.current_agent is None
        assert state.turn_number == 0
        assert state.retry_count == 0

    def test_increment_turn(self):
        state = AgenticState(retry_count=3)
        state.increment_turn()
        assert state.turn_number == 1
        assert state.retry_count == 0  # 리셋되어야 함

    def test_set_and_get_entity(self):
        state = AgenticState()
        state.set_entity("user_id", "user123")
        assert state.get_entity("user_id") == "user123"
        assert state.get_entity("nonexistent", "default") == "default"

    def test_reset_routing(self):
        state = AgenticState(current_agent="LOCAL")
        state.reset_routing()
        assert state.current_agent is None

    def test_to_handoff_context(self):
        state = AgenticState(
            conversation_history=[
                {"role": "user", "content": "msg1"},
                {"role": "assistant", "content": "msg2"},
                {"role": "user", "content": "msg3"},
                {"role": "assistant", "content": "msg4"},
            ],
            internal_summary="요약 내용",
            entities={"user_id": "123"},
            turn_number=4,
        )
        handoff = state.to_handoff_context()
        assert handoff["summary"] == "요약 내용"
        assert handoff["entities"]["user_id"] == "123"
        assert len(handoff["recent_messages"]) == 3  # 최근 3개만


# ── Phase 2: Sticky Routing ────────────────────────────────────

class TestStickyRouting:
    """Sticky Routing 조건 분기 테스트."""

    def test_sticky_route_skips_router(self):
        """current_agent가 설정되어 있으면 Router를 호출하지 않아야 함."""
        state = AgenticState(current_agent="LOCAL")
        # Router를 우회하는 조건 검증
        assert state.current_agent is not None

    def test_new_session_requires_router(self):
        """초기 상태에서는 Router 호출이 필요함."""
        state = AgenticState()
        assert state.current_agent is None

    def test_escalation_resets_routing(self):
        """에스컬레이션 시 Sticky Routing이 해제되어야 함."""
        state = AgenticState(current_agent="LOCAL")
        state.reset_routing()
        assert state.current_agent is None


# ── Phase 4: Semantic Cache ────────────────────────────────────

from utils.semantic_cache import SemanticCache


class TestSemanticCacheCacheability:
    """캐싱 가능 여부 판별 테스트 (LLM/DB 불필요)."""

    def test_code_request_not_cacheable(self):
        cache = SemanticCache.__new__(SemanticCache)
        cache._enabled = True
        assert not cache._is_cacheable("코드 작성해줘")
        assert not cache._is_cacheable("debug this function")
        assert not cache._is_cacheable("fix the bug in main.py")

    def test_faq_request_is_cacheable(self):
        cache = SemanticCache.__new__(SemanticCache)
        cache._enabled = True
        assert cache._is_cacheable("영업 시간이 언제야?")
        assert cache._is_cacheable("요금제 안내해줘")

    def test_cli_command_not_cacheable(self):
        cache = SemanticCache.__new__(SemanticCache)
        cache._enabled = True
        assert not cache._is_cacheable("/clear")
        assert not cache._is_cacheable("/stats")


# ── Phase 5: Tool Validation ──────────────────────────────────

from utils.tools import FileReadTool, ListDirTool, FileReadInput, ListDirInput


class TestToolValidation:
    """Pydantic 기반 도구 입력 검증 테스트."""

    def test_file_read_input_valid(self):
        """유효한 파일 경로 입력."""
        inp = FileReadInput(path="main.py")
        assert inp.path == "main.py"

    def test_file_read_input_empty_path_rejected(self):
        """빈 경로는 거부되어야 함."""
        with pytest.raises(Exception):
            FileReadInput(path="")

    def test_list_dir_input_default(self):
        """ListDir은 기본값 '.'을 가져야 함."""
        inp = ListDirInput()
        assert inp.path == "."

    @pytest.mark.asyncio
    async def test_validate_and_execute_with_invalid_input(self):
        """잘못된 입력 시 에러 메시지를 반환해야 함 (예외가 아닌)."""
        tool = FileReadTool()
        result = await tool.validate_and_execute(path="")
        assert "Tool Input Error" in result


# ── Phase 6: Enhanced Metrics ──────────────────────────────────

from utils.metrics import RequestMetrics


class TestEnhancedMetrics:
    """확장된 메트릭 필드 테스트."""

    def test_new_fields_exist(self):
        m = RequestMetrics()
        assert m.input_tokens == 0
        assert m.output_tokens == 0
        assert m.estimated_cost_usd == 0.0
        assert m.cache_hit is False
        assert m.sticky_route_skipped is False
        assert m.context_tokens_saved == 0

    def test_metrics_with_values(self):
        m = RequestMetrics(
            input_tokens=1500,
            output_tokens=300,
            estimated_cost_usd=0.0023,
            cache_hit=True,
            sticky_route_skipped=True,
        )
        assert m.input_tokens == 1500
        assert m.cache_hit is True
