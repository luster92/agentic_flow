"""
Tests for Enterprise Edition improvements.
Covers: AgentState (Pydantic), CheckpointManager, ConfigLoader,
        PersonaManager, DebateLoop, HITLManager.
"""

import json
import os
import tempfile
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

# ── Phase 1: Pydantic AgentState ──────────────────────────────

from core.state import AgentState, SessionStatus, MessageModel, SnapshotMetadata


class TestAgentStatePydantic:
    """Pydantic v2 기반 AgentState 테스트."""

    def test_default_initialization(self):
        state = AgentState()
        assert state.status == SessionStatus.RUNNING
        assert state.step == 0
        assert state.turn_number == 0
        assert state.active_persona == "worker"
        assert state.session_id  # UUID가 생성되어야 함

    def test_serialization_roundtrip(self):
        """JSON 직렬화/역직렬화 왕복 테스트."""
        state = AgentState(
            step=5,
            status=SessionStatus.PAUSED,
            internal_summary="테스트 요약",
            entities={"user_id": "u123", "intent": "code"},
            active_persona="devil",
            conversation_history=[
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
            ],
        )
        json_str = state.model_dump_json()
        restored = AgentState.model_validate_json(json_str)

        assert restored.step == 5
        assert restored.status == SessionStatus.PAUSED
        assert restored.internal_summary == "테스트 요약"
        assert restored.entities["user_id"] == "u123"
        assert restored.active_persona == "devil"
        assert len(restored.conversation_history) == 2

    def test_backward_compat_methods(self):
        """기존 AgenticState 메서드 호환성."""
        state = AgentState()
        state.set_entity("key", "value")
        assert state.get_entity("key") == "value"
        assert state.get_entity("missing", "default") == "default"

        state.increment_turn()
        assert state.turn_number == 1
        assert state.retry_count == 0

        state.update_summary("요약")
        assert state.internal_summary == "요약"

        state.current_agent = "LOCAL"
        state.reset_routing()
        assert state.current_agent is None

    def test_handoff_context(self):
        state = AgentState(
            conversation_history=[
                {"role": "user", "content": f"msg{i}"}
                for i in range(5)
            ],
            internal_summary="summary",
            entities={"k": "v"},
            turn_number=3,
            active_persona="coder",
        )
        ctx = state.to_handoff_context()
        assert ctx["summary"] == "summary"
        assert ctx["active_persona"] == "coder"
        assert len(ctx["recent_messages"]) == 3

    def test_suspend_and_resume(self):
        state = AgentState()
        state.suspend("승인 필요", {"func": "send_email"})
        assert state.status == SessionStatus.SUSPENDED
        assert "reason" in state.hitl_context

        state.resume({"entities": {"approved": True}})
        assert state.status == SessionStatus.RUNNING
        assert state.entities["approved"] is True
        assert state.hitl_context == {}


# ── Phase 2: CheckpointManager ────────────────────────────────

from core.checkpoint import CheckpointManager
from core.state import CheckpointType


class TestCheckpointManager:
    """SQLite 체크포인트 관리자 테스트."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.mgr = CheckpointManager(db_dir=self.tmpdir)

    def test_save_and_load(self):
        state = AgentState(step=3, internal_summary="step 3 done")
        self.mgr.save_checkpoint(state, CheckpointType.MILESTONE, label="test")

        loaded = self.mgr.load_checkpoint(state.session_id, step=3)
        assert loaded is not None
        assert loaded.step == 3
        assert loaded.internal_summary == "step 3 done"

    def test_load_latest(self):
        state = AgentState()
        state.step = 1
        self.mgr.save_checkpoint(state, CheckpointType.TRANSACTION)
        state.step = 2
        self.mgr.save_checkpoint(state, CheckpointType.TRANSACTION)

        loaded = self.mgr.load_checkpoint(state.session_id)
        assert loaded is not None
        assert loaded.step == 2

    def test_rollback(self):
        state = AgentState()
        for i in range(1, 6):
            state.step = i
            self.mgr.save_checkpoint(state, CheckpointType.MILESTONE)

        rolled = self.mgr.rollback(state.session_id, step=3)
        assert rolled is not None
        assert rolled.step == 3

        # step 3 이후 체크포인트는 삭제됨
        cps = self.mgr.list_checkpoints(state.session_id)
        assert all(cp["step"] <= 3 for cp in cps)

    def test_list_checkpoints(self):
        state = AgentState()
        self.mgr.save_checkpoint(state, CheckpointType.TRANSACTION, label="a")
        state.step = 1
        self.mgr.save_checkpoint(state, CheckpointType.MILESTONE, label="b")

        cps = self.mgr.list_checkpoints(state.session_id)
        assert len(cps) == 2
        assert cps[0]["label"] == "a"
        assert cps[1]["label"] == "b"

    def test_load_nonexistent(self):
        loaded = self.mgr.load_checkpoint("nonexistent-id")
        assert loaded is None


# ── Phase 3: ConfigLoader ─────────────────────────────────────

from core.config_loader import ConfigLoader, PersonaConfig


class TestConfigLoader:
    """계층적 설정 로더 테스트."""

    def setup_method(self):
        ConfigLoader.reset()
        self.tmpdir = tempfile.mkdtemp()
        self.personas_dir = os.path.join(self.tmpdir, "personas")
        os.makedirs(self.personas_dir)

        # base.yaml 생성
        with open(os.path.join(self.tmpdir, "base.yaml"), "w") as f:
            f.write(
                "system:\n"
                "  default_persona: worker\n"
                "  debate_max_rounds: 3\n"
            )

        # 테스트 페르소나 생성
        with open(os.path.join(self.personas_dir, "test_persona.yaml"), "w") as f:
            f.write(
                'persona_id: "test_v1"\n'
                'display_name: "Test Persona"\n'
                'system_prompt: "Hello {{ user_name }}"\n'
                "parameters:\n"
                "  temperature: 0.5\n"
                "  top_p: 0.8\n"
                "allowed_tools:\n"
                '  - "file_read"\n'
                'voice_tone: "neutral"\n'
            )

        self.loader = ConfigLoader(configs_dir=self.tmpdir)

    def teardown_method(self):
        ConfigLoader.reset()

    def test_base_config_loaded(self):
        assert self.loader.get("system.default_persona") == "worker"
        assert self.loader.get("system.debate_max_rounds") == 3

    def test_dot_notation_default(self):
        assert self.loader.get("nonexistent.key", "fallback") == "fallback"

    def test_persona_load(self):
        persona = self.loader.load_persona("test_persona")
        assert persona.persona_id == "test_v1"
        assert persona.display_name == "Test Persona"
        assert persona.temperature == 0.5
        assert "file_read" in persona.allowed_tools

    def test_persona_caching(self):
        p1 = self.loader.load_persona("test_persona")
        p2 = self.loader.load_persona("test_persona")
        assert p1 is p2  # 동일 객체 (캐싱됨)

    def test_persona_not_found(self):
        with pytest.raises(FileNotFoundError):
            self.loader.load_persona("nonexistent")

    def test_jinja2_rendering(self):
        rendered = self.loader.render_prompt(
            "Hello {{ user_name }}!", {"user_name": "World"}
        )
        assert rendered == "Hello World!"

    def test_list_personas(self):
        personas = self.loader.list_personas()
        assert "test_persona" in personas


# ── Phase 4: PersonaManager ───────────────────────────────────

from engine.persona import PersonaManager


class TestPersonaManager:
    """동적 페르소나 관리자 테스트."""

    def setup_method(self):
        ConfigLoader.reset()
        # 실제 configs 디렉토리 사용
        configs_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "configs",
        )
        self.loader = ConfigLoader(configs_dir=configs_dir)
        self.mgr = PersonaManager(config_loader=self.loader)

    def teardown_method(self):
        ConfigLoader.reset()

    def test_default_persona(self):
        assert self.mgr.current_id == "worker"

    def test_switch_persona(self):
        new_persona = self.mgr.switch_persona("devil", reason="test")
        assert self.mgr.current_id == "devil"
        assert new_persona.persona_id == "devil_advocate_v1"

    def test_transition_log(self):
        self.mgr.switch_persona("devil")
        self.mgr.switch_persona("moderator")
        assert len(self.mgr.transitions) == 2
        assert self.mgr.transitions[0].old_persona == "worker"
        assert self.mgr.transitions[0].new_persona == "devil"

    def test_transition_message(self):
        self.mgr.switch_persona("devil")
        msg = self.mgr.get_transition_message()
        assert "worker" in msg
        assert "Devil's Advocate" in msg
        assert "변경되었습니다" in msg

    def test_system_prompt_with_context(self):
        prompt = self.mgr.get_system_prompt()
        assert len(prompt) > 0  # 비어있지 않아야 함

    def test_available_personas(self):
        available = self.mgr.available_personas()
        assert "worker" in available
        assert "devil" in available
        assert "moderator" in available


# ── Phase 5: DebateLoop ───────────────────────────────────────

from engine.adversarial import DebateLoop, DebateResult


class TestDebateLoop:
    """적대적 검증 루프 테스트 (Mock 기반)."""

    def setup_method(self):
        ConfigLoader.reset()
        configs_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "configs",
        )
        self.loader = ConfigLoader(configs_dir=configs_dir)

    def teardown_method(self):
        ConfigLoader.reset()

    @pytest.mark.asyncio
    async def test_debate_early_approval(self):
        """Moderator가 낮은 점수 → 조기 승인."""
        persona_mgr = PersonaManager(config_loader=self.loader)
        debate = DebateLoop(persona_manager=persona_mgr)

        # Mock LLM calls — must be coroutine-compatible
        mock_response_attack = MagicMock()
        mock_response_attack.choices = [
            MagicMock(message=MagicMock(content=json.dumps({
                "attack_vectors": [],
                "overall_assessment": "Minor issues only",
                "recommendation": "CONDITIONAL_PASS",
            })))
        ]

        mock_response_judge = MagicMock()
        mock_response_judge.choices = [
            MagicMock(message=MagicMock(content=json.dumps({
                "validity_score": 3,
                "verdict": "APPROVE",
                "reasoning": "Attacks are trivial",
            })))
        ]

        with patch.object(debate._client.chat.completions, "create", new_callable=AsyncMock) as mock_create:
            mock_create.side_effect = [
                mock_response_attack,  # Attack
                mock_response_judge,   # Judge
            ]
            result = await debate.run(
                "test proposal", "test task",
                max_rounds=3, approval_threshold=7.0,
            )

        assert result.approved is True
        assert result.total_rounds == 1

    @pytest.mark.asyncio
    async def test_debate_max_rounds(self):
        """max_rounds 도달 시 강제 승인."""
        persona_mgr = PersonaManager(config_loader=self.loader)
        debate = DebateLoop(persona_manager=persona_mgr)

        mock_attack = MagicMock()
        mock_attack.choices = [MagicMock(message=MagicMock(content="{}"))]
        mock_judge = MagicMock()
        mock_judge.choices = [
            MagicMock(message=MagicMock(content=json.dumps({
                "validity_score": 9, "verdict": "REVISE",
            })))
        ]
        mock_revise = MagicMock()
        mock_revise.choices = [
            MagicMock(message=MagicMock(content="revised proposal"))
        ]

        with patch.object(debate._client.chat.completions, "create", new_callable=AsyncMock) as mock_create:
            # 2 rounds: each needs attack + judge + revise (except last round no revise)
            mock_create.side_effect = [
                mock_attack, mock_judge, mock_revise,  # Round 1
                mock_attack, mock_judge,                # Round 2 (last, no revise)
            ]
            result = await debate.run(
                "test", "task", max_rounds=2, approval_threshold=7.0,
            )

        assert result.approved is True
        assert result.total_rounds == 2


# ── Phase 6: HITLManager ─────────────────────────────────────

from engine.hitl import HITLManager, WaitApproval, requires_human_approval


class TestHITL:
    """HITL 인터럽트/재개 테스트."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cp_mgr = CheckpointManager(db_dir=self.tmpdir)
        self.hitl = HITLManager(checkpoint_manager=self.cp_mgr)

    @pytest.mark.asyncio
    async def test_suspend_and_resume(self):
        state = AgentState()
        await self.hitl.suspend(state, "Test approval needed")

        assert state.status == SessionStatus.SUSPENDED
        pending = self.hitl.get_pending(state.session_id)
        assert pending is not None
        assert pending["reason"] == "Test approval needed"

        restored = await self.hitl.resume(state.session_id, action="approve")
        assert restored is not None
        assert restored.status == SessionStatus.RUNNING

    @pytest.mark.asyncio
    async def test_resume_with_modify(self):
        state = AgentState()
        state.set_entity("original", "value")
        await self.hitl.suspend(state, "Modify needed")

        restored = await self.hitl.resume(
            state.session_id, action="modify",
            modified_data={"entities": {"modified": True}},
        )
        assert restored is not None
        assert restored.entities["modified"] is True

    @pytest.mark.asyncio
    async def test_resume_reject(self):
        state = AgentState()
        await self.hitl.suspend(state, "Reject test")

        result = await self.hitl.resume(state.session_id, action="reject")
        assert result is None  # reject → None

    def test_wait_approval_exception(self):
        with pytest.raises(WaitApproval) as exc_info:
            raise WaitApproval(
                reason="Test", function_name="send_email",
                function_args={"to": "a@b.com"},
            )
        assert "send_email" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_requires_human_approval_decorator(self):
        @requires_human_approval("Email approval")
        async def send_email(to: str, body: str) -> str:
            return "sent"

        with pytest.raises(WaitApproval) as exc_info:
            await send_email(to="a@b.com", body="hello")
        assert exc_info.value.function_name == "send_email"


# ── Backward Compatibility ────────────────────────────────────

class TestBackwardCompatibility:
    """기존 state.py import 호환성 테스트."""

    def test_old_import_works(self):
        from state import AgenticState
        state = AgenticState()
        assert state.turn_number == 0
        state.increment_turn()
        assert state.turn_number == 1

    def test_agenticstate_is_agentstate(self):
        from state import AgenticState, AgentState
        assert AgenticState is AgentState
