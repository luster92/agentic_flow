"""
ApprovalBridge — HITL 승인 채널 추상화 및 게이트웨이 연동
==========================================================
기존 CLI `/approve` `/reject` 매커니즘을 추상화하여
WebSocket, HTTP, 외부 게이트웨이로 확장 가능하게 합니다.

채널 구조:
- ApprovalChannel (ABC): 승인 채널 인터페이스
- CLIApprovalChannel: 기존 CLI 호환 채널
- CallbackApprovalChannel: 콜백 기반 비동기 채널 (외부 게이트웨이용)
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ── 승인 결과 ──────────────────────────────────────────────────

@dataclass
class ApprovalResult:
    """승인 요청 결과."""
    approved: bool
    action: str  # "approve" | "reject" | "timeout"
    reason: str = ""
    responded_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict[str, Any] = field(default_factory=dict)


# ── 승인 채널 추상화 ──────────────────────────────────────────

class ApprovalChannel(ABC):
    """승인 채널 인터페이스.

    모든 승인 채널(CLI, WebSocket, HTTP 등)은
    이 인터페이스를 구현해야 합니다.
    """

    @abstractmethod
    async def request_approval(
        self,
        reason: str,
        context: dict[str, Any],
    ) -> None:
        """승인 요청을 전송합니다.

        Args:
            reason: 승인 필요 사유
            context: 추가 컨텍스트 정보
        """
        ...

    @abstractmethod
    async def wait_for_response(
        self,
        timeout: int = 300,
    ) -> ApprovalResult:
        """승인 응답을 대기합니다.

        Args:
            timeout: 대기 시간 (초), 초과 시 자동 거절

        Returns:
            ApprovalResult
        """
        ...


# ── CLI 승인 채널 (하위 호환) ──────────────────────────────────

class CLIApprovalChannel(ApprovalChannel):
    """기존 CLI 기반 승인 채널.

    `/approve` / `/reject` 명령어로 응답을 받습니다.
    main.py의 기존 동작과 100% 호환됩니다.
    """

    def __init__(self) -> None:
        self._pending_approval: asyncio.Event = asyncio.Event()
        self._approval_result: ApprovalResult | None = None
        self._current_reason: str = ""
        self._current_context: dict[str, Any] = {}

    async def request_approval(
        self,
        reason: str,
        context: dict[str, Any],
    ) -> None:
        """CLI에 승인 요청을 표시합니다."""
        self._current_reason = reason
        self._current_context = context
        self._pending_approval.clear()
        self._approval_result = None

        logger.info(
            f"⏸️ Approval requested via CLI: {reason}"
        )

    async def wait_for_response(
        self,
        timeout: int = 300,
    ) -> ApprovalResult:
        """CLI에서 승인/거절 입력을 대기합니다."""
        try:
            await asyncio.wait_for(
                self._pending_approval.wait(),
                timeout=timeout,
            )
            if self._approval_result:
                return self._approval_result
            return ApprovalResult(
                approved=False,
                action="error",
                reason="No result received",
            )
        except asyncio.TimeoutError:
            logger.warning(
                f"⏰ Approval timed out after {timeout}s"
            )
            return ApprovalResult(
                approved=False,
                action="timeout",
                reason=f"No response within {timeout} seconds",
            )

    def respond(
        self,
        action: str,
        reason: str = "",
    ) -> None:
        """CLI에서 승인/거절 응답을 제출합니다.

        Args:
            action: "approve" | "reject"
            reason: 응답 사유
        """
        self._approval_result = ApprovalResult(
            approved=(action == "approve"),
            action=action,
            reason=reason,
        )
        self._pending_approval.set()

    @property
    def has_pending(self) -> bool:
        """보류 중인 승인 요청 존재 여부."""
        return (
            not self._pending_approval.is_set()
            and self._current_reason != ""
        )


# ── 콜백 승인 채널 (외부 게이트웨이용) ────────────────────────

class CallbackApprovalChannel(ApprovalChannel):
    """콜백 기반 비동기 승인 채널.

    외부 게이트웨이(WebSocket, HTTP 등)에서
    콜백으로 승인/거절을 트리거합니다.
    EventBus와 연동하여 이벤트 기반 승인 처리를 지원합니다.
    """

    def __init__(
        self,
        event_bus: Any = None,
        auto_reject_timeout: int = 300,
    ) -> None:
        self.event_bus = event_bus
        self.auto_reject_timeout = auto_reject_timeout
        self._response_queue: asyncio.Queue[ApprovalResult] = (
            asyncio.Queue()
        )
        self._request_id: str = ""

    async def request_approval(
        self,
        reason: str,
        context: dict[str, Any],
    ) -> None:
        """이벤트 버스를 통해 승인 요청을 발행합니다."""
        self._request_id = str(uuid.uuid4())

        if self.event_bus is not None:
            try:
                from core.event_bus import Event, EventType
                await self.event_bus.publish(Event(
                    type=EventType.APPROVAL_REQUEST,
                    source="hitl",
                    payload={
                        "request_id": self._request_id,
                        "reason": reason,
                        "context": context,
                    },
                ))
            except Exception as e:
                logger.error(
                    f"❌ Failed to publish approval request: {e}"
                )

        logger.info(
            f"⏸️ Approval requested via callback channel: "
            f"{reason} (id={self._request_id[:8]}...)"
        )

    async def wait_for_response(
        self,
        timeout: int = 0,
    ) -> ApprovalResult:
        """콜백 응답을 대기합니다."""
        effective_timeout = (
            timeout if timeout > 0
            else self.auto_reject_timeout
        )

        try:
            result = await asyncio.wait_for(
                self._response_queue.get(),
                timeout=effective_timeout,
            )
            return result
        except asyncio.TimeoutError:
            logger.warning(
                f"⏰ Callback approval timed out "
                f"after {effective_timeout}s → auto-reject"
            )
            return ApprovalResult(
                approved=False,
                action="timeout",
                reason=(
                    f"Auto-rejected: no response within "
                    f"{effective_timeout} seconds"
                ),
            )

    async def submit_response(
        self,
        approved: bool,
        reason: str = "",
    ) -> None:
        """외부 시스템에서 승인 응답을 제출합니다.

        WebSocket 핸들러 등에서 호출합니다.
        """
        result = ApprovalResult(
            approved=approved,
            action="approve" if approved else "reject",
            reason=reason,
        )
        await self._response_queue.put(result)

        # 응답 이벤트 발행
        if self.event_bus is not None:
            try:
                from core.event_bus import Event, EventType
                await self.event_bus.publish(Event(
                    type=EventType.APPROVAL_RESPONSE,
                    source="gateway",
                    payload={
                        "request_id": self._request_id,
                        "approved": approved,
                        "reason": reason,
                    },
                ))
            except Exception:
                pass

    @property
    def request_id(self) -> str:
        """현재 승인 요청 ID."""
        return self._request_id
