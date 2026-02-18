"""
AgenticState — 구조화된 상태 객체
==================================
에이전트 파이프라인 전체에서 공유되는 상태를 정의합니다.

핵심 원칙:
- Raw 대화 로그 대신 구조화된 데이터로 에이전트 간 통신
- 컨텍스트 오염(Context Pollution) 방지
- Sticky Routing, Semantic Filtering 등 후속 최적화의 기반
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgenticState:
    """에이전트 파이프라인 전체에서 공유되는 구조화된 상태.

    Fields:
        conversation_history: 사용자에게 보여지는 최근 대화 (컨텍스트 윈도우)
        internal_summary: 에이전트 간 핸드오프 시 전달할 핵심 요약
        entities: 대화에서 추출된 구조화 데이터 (user_id, intent 등)
        current_agent: Sticky Routing — 현재 할당된 에이전트 경로
        next_step: 오케스트레이터가 다음에 실행할 단계
        retry_count: 현재 턴의 재시도 횟수
        turn_number: 현재 세션의 턴 번호
    """

    conversation_history: list[dict[str, str]] = field(default_factory=list)
    internal_summary: str = ""
    entities: dict[str, Any] = field(default_factory=dict)
    current_agent: str | None = None
    next_step: str = ""
    retry_count: int = 0
    turn_number: int = 0

    # ── Convenience Methods ──────────────────────────────────

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
        """Sticky Routing 상태를 초기화합니다 (에이전트 전환 시)."""
        self.current_agent = None

    def increment_turn(self) -> None:
        """턴 번호를 증가시킵니다."""
        self.turn_number += 1
        self.retry_count = 0

    def to_handoff_context(self) -> dict[str, Any]:
        """에이전트 간 핸드오프 시 전달할 최소 컨텍스트를 반환합니다.

        Raw 대화 로그 대신 요약 + 엔티티만 전달하여 토큰을 절약합니다.
        """
        return {
            "summary": self.internal_summary,
            "entities": dict(self.entities),
            "turn_number": self.turn_number,
            "recent_messages": self.conversation_history[-3:]
            if self.conversation_history
            else [],
        }
