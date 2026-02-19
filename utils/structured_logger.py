"""
StructuredLogger — 구조화된 관측 이벤트 시스템
================================================
에이전트의 '생각', 도구 호출, 결정, 오류, 메트릭을
OpenClaw UI가 소비할 수 있는 구조화된 JSON 이벤트로 출력합니다.

이벤트 타입:
- thought: 에이전트의 사고 과정
- tool_call: 도구 호출 기록
- decision: 라우팅/에스컬레이션 결정
- error: 오류 발생
- metric: 성능/비용 지표
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class StructuredEvent(BaseModel):
    """OpenClaw UI가 소비할 수 있는 구조화된 이벤트."""

    event_id: str = Field(
        default_factory=lambda: str(uuid.uuid4())
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    event_type: str  # "thought" | "tool_call" | "decision" | "error" | "metric"
    source: str      # "router" | "worker" | "critic" | "debate" | "hitl"
    content: str     # 표시할 내용
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_jsonl(self) -> str:
        """JSON-line 형태 직렬화."""
        return self.model_dump_json()


class StructuredLogger:
    """구조화된 이벤트를 파일 + EventBus로 동시 출력.

    기존 logging.Logger를 보완하여, 에이전트의 내부 상태를
    외부 UI에서 시각화할 수 있는 형태로 기록합니다.
    """

    def __init__(
        self,
        log_dir: str = "logs/events",
        session_id: str = "",
        event_bus: Any = None,  # EventBus 순환 임포트 방지
    ) -> None:
        self.log_dir = Path(log_dir)
        self.session_id = session_id or str(uuid.uuid4())[:8]
        self.event_bus = event_bus
        self._events: list[StructuredEvent] = []

        # 로그 디렉토리 생성
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._log_file = self.log_dir / f"session_{self.session_id}.jsonl"

        logger.info(
            f"📊 StructuredLogger initialized → {self._log_file}"
        )

    def _emit(self, event: StructuredEvent) -> None:
        """이벤트를 로그 파일 + 메모리에 기록합니다."""
        self._events.append(event)

        # JSONL 파일에 추가
        try:
            with open(self._log_file, "a", encoding="utf-8") as f:
                f.write(event.to_jsonl() + "\n")
        except OSError as e:
            logger.error(f"❌ Failed to write event log: {e}")

        # EventBus 연동 (비동기)
        if self.event_bus is not None:
            try:
                from core.event_bus import Event, EventType
                bus_event = Event(
                    type=EventType.THINKING,
                    source=event.source,
                    payload={
                        "event_type": event.event_type,
                        "content": event.content,
                        "metadata": event.metadata,
                    },
                )
                self.event_bus.publish_sync(bus_event)
            except Exception:
                pass  # EventBus 없으면 무시

    # ── 이벤트 발행 메서드 ────────────────────────────────────

    def thought(
        self,
        source: str,
        content: str,
        **metadata: Any,
    ) -> None:
        """에이전트 사고 과정을 기록합니다."""
        self._emit(StructuredEvent(
            event_type="thought",
            source=source,
            content=content,
            metadata=metadata,
        ))

    def tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: str = "",
        **metadata: Any,
    ) -> None:
        """도구 호출을 기록합니다."""
        self._emit(StructuredEvent(
            event_type="tool_call",
            source="worker",
            content=f"Tool: {tool_name}",
            metadata={
                "tool_name": tool_name,
                "args": args,
                "result": result[:200] if result else "",
                **metadata,
            },
        ))

    def decision(
        self,
        source: str,
        decision: str,
        reason: str,
        **metadata: Any,
    ) -> None:
        """라우팅/에스컬레이션 결정을 기록합니다."""
        self._emit(StructuredEvent(
            event_type="decision",
            source=source,
            content=f"{decision}: {reason}",
            metadata={
                "decision": decision,
                "reason": reason,
                **metadata,
            },
        ))

    def error(
        self,
        source: str,
        error: str,
        **metadata: Any,
    ) -> None:
        """오류를 기록합니다."""
        self._emit(StructuredEvent(
            event_type="error",
            source=source,
            content=error,
            metadata=metadata,
        ))

    def metric(
        self,
        key: str,
        value: float,
        unit: str = "",
        **metadata: Any,
    ) -> None:
        """성능/비용 지표를 기록합니다."""
        self._emit(StructuredEvent(
            event_type="metric",
            source="system",
            content=f"{key}={value}{unit}",
            metadata={
                "key": key,
                "value": value,
                "unit": unit,
                **metadata,
            },
        ))

    # ── 조회 ──────────────────────────────────────────────────

    def get_trace(
        self,
        event_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """이벤트 트레이스를 반환합니다.

        Args:
            event_type: 필터링할 이벤트 타입
            limit: 최대 반환 개수

        Returns:
            이벤트 딕셔너리 리스트
        """
        events = self._events
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return [e.model_dump() for e in events[-limit:]]

    @property
    def event_count(self) -> int:
        """기록된 이벤트 수."""
        return len(self._events)
