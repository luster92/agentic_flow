"""
EventBus — 비동기 이벤트 기반 통신 시스템
==========================================
모든 내부 통신(사용자 메시지, 도구 호출, 승인 요청 등)이
이 이벤트 버스를 경유하여 느슨한 결합(Loose Coupling)을 달성합니다.

핵심 기능:
- asyncio.Queue 기반 pub/sub 패턴
- 타입 기반 이벤트 구독
- 다중 구독자 지원
- 백그라운드 이벤트 소비 루프
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


# ── 이벤트 타입 ────────────────────────────────────────────────

class EventType(str, Enum):
    """시스템에서 발생하는 모든 이벤트 유형."""

    # 사용자 상호작용
    USER_MESSAGE = "user_message"
    AGENT_RESPONSE = "agent_response"

    # 에이전트 내부
    THINKING = "thinking"
    DECISION = "decision"

    # 도구 실행
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"

    # HITL
    APPROVAL_REQUEST = "approval_request"
    APPROVAL_RESPONSE = "approval_response"

    # 시스템
    SYSTEM_NOTIFICATION = "system_notification"
    ERROR = "error"
    METRIC = "metric"

    # 생명주기
    SESSION_START = "session_start"
    SESSION_END = "session_end"


# ── 이벤트 데이터 ─────────────────────────────────────────────

@dataclass
class Event:
    """시스템 전체에서 교환되는 구조화된 이벤트.

    모든 내부 통신은 이 Event 객체를 통해 이루어집니다.
    OpenClaw 게이트웨이와의 통합 시에도 동일한 포맷을 사용합니다.
    """

    type: EventType
    payload: dict[str, Any]
    source: str  # "user" | "router" | "worker" | "critic" | "hitl" | "system"
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 딕셔너리 변환."""
        return {
            "event_id": self.event_id,
            "type": self.type.value,
            "source": self.source,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }


# ── 구독 정보 ──────────────────────────────────────────────────

EventHandler = Callable[[Event], Coroutine[Any, Any, None]]


@dataclass
class _Subscription:
    """내부 구독 레코드."""
    subscription_id: str
    event_type: EventType
    handler: EventHandler


# ── 이벤트 버스 ────────────────────────────────────────────────

class EventBus:
    """Singleton 비동기 이벤트 버스.

    asyncio.Queue를 사용하여 이벤트를 비동기적으로 분배합니다.
    모든 구독자의 핸들러는 비동기 함수여야 합니다.
    """

    _instance: EventBus | None = None

    def __new__(cls) -> EventBus:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized: bool = True

        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._subscriptions: dict[str, _Subscription] = {}
        self._type_index: dict[EventType, list[str]] = {}
        self._running: bool = False
        self._consumer_task: asyncio.Task[None] | None = None
        self._event_log: list[Event] = []
        self._max_log_size: int = 1000

        logger.info("📡 EventBus initialized")

    # ── 발행 ──────────────────────────────────────────────────

    async def publish(self, event: Event) -> None:
        """이벤트를 버스에 발행합니다.

        Args:
            event: 발행할 이벤트
        """
        await self._queue.put(event)
        logger.debug(
            f"📡 Event published: {event.type.value} "
            f"from {event.source}"
        )

    def publish_sync(self, event: Event) -> None:
        """동기 컨텍스트에서 이벤트를 발행합니다 (fire-and-forget).

        이벤트 루프가 실행 중이어야 합니다.
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.publish(event))
        except RuntimeError:
            logger.warning(
                "⚠️ No running event loop for sync publish, "
                "event dropped"
            )

    # ── 구독 ──────────────────────────────────────────────────

    def subscribe(
        self,
        event_type: EventType,
        handler: EventHandler,
    ) -> str:
        """특정 이벤트 타입에 핸들러를 구독합니다.

        Args:
            event_type: 구독할 이벤트 타입
            handler: 비동기 핸들러 함수

        Returns:
            구독 ID (구독 해제 시 사용)
        """
        sub_id = str(uuid.uuid4())
        subscription = _Subscription(
            subscription_id=sub_id,
            event_type=event_type,
            handler=handler,
        )
        self._subscriptions[sub_id] = subscription

        if event_type not in self._type_index:
            self._type_index[event_type] = []
        self._type_index[event_type].append(sub_id)

        logger.debug(
            f"📡 Subscribed: {event_type.value} → "
            f"{handler.__name__} (id={sub_id[:8]}...)"
        )
        return sub_id

    def unsubscribe(self, subscription_id: str) -> None:
        """구독을 해제합니다.

        Args:
            subscription_id: subscribe()에서 반환된 ID
        """
        sub = self._subscriptions.pop(subscription_id, None)
        if sub is None:
            return

        type_subs = self._type_index.get(sub.event_type, [])
        if subscription_id in type_subs:
            type_subs.remove(subscription_id)

        logger.debug(
            f"📡 Unsubscribed: {sub.event_type.value} "
            f"(id={subscription_id[:8]}...)"
        )

    # ── 소비자 루프 ───────────────────────────────────────────

    async def start(self) -> None:
        """백그라운드 이벤트 소비 루프를 시작합니다."""
        if self._running:
            logger.warning("⚠️ EventBus already running")
            return

        self._running = True
        self._consumer_task = asyncio.create_task(self._consume_loop())
        logger.info("📡 EventBus consumer loop started")

    async def stop(self) -> None:
        """이벤트 소비 루프를 중지합니다."""
        self._running = False
        if self._consumer_task is not None:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
            self._consumer_task = None
        logger.info("📡 EventBus consumer loop stopped")

    async def _consume_loop(self) -> None:
        """큐에서 이벤트를 꺼내 구독자에게 분배합니다."""
        while self._running:
            try:
                event = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            # 이벤트 로그 기록
            self._event_log.append(event)
            if len(self._event_log) > self._max_log_size:
                self._event_log = self._event_log[-self._max_log_size:]

            # 구독자에게 분배
            sub_ids = self._type_index.get(event.type, [])
            for sub_id in sub_ids:
                sub = self._subscriptions.get(sub_id)
                if sub is None:
                    continue
                try:
                    await sub.handler(event)
                except Exception as e:
                    logger.error(
                        f"❌ Event handler error: "
                        f"{sub.handler.__name__} → {e}"
                    )

    # ── 유틸리티 ──────────────────────────────────────────────

    def get_event_log(
        self,
        event_type: EventType | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """이벤트 로그를 조회합니다.

        Args:
            event_type: 필터링할 이벤트 타입 (None이면 전체)
            limit: 최대 반환 개수

        Returns:
            이벤트 딕셔너리 리스트 (최신순)
        """
        events = self._event_log
        if event_type is not None:
            events = [e for e in events if e.type == event_type]
        return [e.to_dict() for e in events[-limit:]]

    @property
    def subscription_count(self) -> int:
        """활성 구독 수."""
        return len(self._subscriptions)

    @property
    def is_running(self) -> bool:
        """소비 루프 실행 여부."""
        return self._running

    @classmethod
    def reset(cls) -> None:
        """Singleton 인스턴스를 리셋합니다 (테스트용)."""
        if cls._instance is not None:
            cls._instance._running = False
            cls._instance._subscriptions.clear()
            cls._instance._type_index.clear()
            cls._instance._event_log.clear()
        cls._instance = None
