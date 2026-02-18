"""
AgentState — Pydantic v2 기반 영속적 상태 객체
===============================================
에이전트 파이프라인 전체에서 공유되는 직렬화 가능한 상태를 정의합니다.

핵심 원칙:
- JSON 직렬화/역직렬화 완전 지원 (체크포인팅의 전제 조건)
- 기존 AgenticState 필드 호환 유지
- 스냅샷 메타데이터 포함 (타임스탬프, 토큰 사용량)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────────

class SessionStatus(str, Enum):
    """에이전트 세션 상태."""
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    SUSPENDED = "SUSPENDED"      # HITL 대기 상태
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class CheckpointType(str, Enum):
    """체크포인트 유형."""
    TRANSACTION = "TRANSACTION"  # 외부 도구 호출 전/후
    MILESTONE = "MILESTONE"      # 논리적 과업 단위 완료


# ── Sub-models ─────────────────────────────────────────────────

class MessageModel(BaseModel):
    """구조화된 메시지."""
    role: str                     # user | assistant | system | tool
    content: str
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class SnapshotMetadata(BaseModel):
    """체크포인트 메타데이터."""
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    elapsed_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    checkpoint_type: CheckpointType | None = None
    label: str = ""


# ── Main State ─────────────────────────────────────────────────

class AgentState(BaseModel):
    """에이전트 파이프라인 전체에서 공유되는 직렬화 가능한 상태.

    기존 AgenticState와의 호환성을 유지하면서 Pydantic v2 기반으로
    체크포인팅, HITL, 동적 페르소나 전환을 지원합니다.
    """

    # ── 세션 식별 ─────────────────────────────────────────
    session_id: str = Field(
        default_factory=lambda: str(uuid.uuid4())
    )
    step: int = 0
    status: SessionStatus = SessionStatus.RUNNING

    # ── 대화 이력 ─────────────────────────────────────────
    conversation_history: list[dict[str, Any]] = Field(default_factory=list)
    history: list[MessageModel] = Field(default_factory=list)

    # ── 작업 메모리 ───────────────────────────────────────
    internal_summary: str = ""
    entities: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, Any] = Field(default_factory=dict)

    # ── 라우팅 ────────────────────────────────────────────
    current_agent: str | None = None
    next_step: str = ""
    retry_count: int = 0
    turn_number: int = 0

    # ── 페르소나 ──────────────────────────────────────────
    active_persona: str = "worker"

    # ── 실행 포인터 ───────────────────────────────────────
    execution_pointer: str = ""

    # ── 스냅샷 메타데이터 ─────────────────────────────────
    metadata: SnapshotMetadata = Field(default_factory=SnapshotMetadata)

    # ── HITL 컨텍스트 ─────────────────────────────────────
    hitl_context: dict[str, Any] = Field(default_factory=dict)

    # ── Convenience Methods (기존 AgenticState 호환) ──────

    def set_entity(self, key: str, value: Any) -> None:
        """엔티티 값을 설정합니다."""
        self.entities[key] = value

    def get_entity(self, key: str, default: Any = None) -> Any:
        """엔티티 값을 조회합니다."""
        return self.entities.get(key, default)

    def update_summary(self, summary: str) -> None:
        """핸드오프용 내부 요약을 업데이트합니다."""
        self.internal_summary = summary

    def reset_routing(self) -> None:
        """Sticky Routing 상태를 초기화합니다."""
        self.current_agent = None

    def increment_turn(self) -> None:
        """턴 번호를 증가시킵니다."""
        self.turn_number += 1
        self.retry_count = 0

    def increment_step(self) -> None:
        """실행 단계를 증가시킵니다."""
        self.step += 1

    def to_handoff_context(self) -> dict[str, Any]:
        """에이전트 간 핸드오프 시 전달할 최소 컨텍스트."""
        return {
            "summary": self.internal_summary,
            "entities": dict(self.entities),
            "turn_number": self.turn_number,
            "active_persona": self.active_persona,
            "recent_messages": self.conversation_history[-3:]
            if self.conversation_history
            else [],
        }

    def suspend(self, reason: str, context: dict[str, Any] | None = None) -> None:
        """HITL 대기 상태로 전환합니다."""
        self.status = SessionStatus.SUSPENDED
        self.hitl_context = {
            "reason": reason,
            "suspended_at": datetime.now(timezone.utc).isoformat(),
            **(context or {}),
        }

    def resume(self, modified_data: dict[str, Any] | None = None) -> None:
        """HITL 대기 상태에서 복귀합니다."""
        self.status = SessionStatus.RUNNING
        if modified_data:
            # 수정된 데이터로 아티팩트/엔티티 패치
            for key, value in modified_data.items():
                if key == "entities":
                    self.entities.update(value)
                elif key == "artifacts":
                    self.artifacts.update(value)
                else:
                    self.artifacts[key] = value
        self.hitl_context = {}
