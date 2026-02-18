"""
HITL Manager — Human-in-the-loop 인터럽트 시스템
================================================
에이전트의 실행을 인터럽트하고, 인간이 상태를 검사/수정한 후
재개할 수 있는 비동기적 제어 메커니즘을 제공합니다.

핵심 기능:
- WaitApproval 예외: 워크플로우 중단 신호
- @requires_human_approval 데코레이터: 민감한 작업 자동 인터럽트
- HITLManager: 상태 저장(SUSPENDED) → 재개(RESUME) 관리
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable, TypeVar

from core.state import AgentState, SessionStatus
from core.checkpoint import CheckpointManager, CheckpointType

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


# ── 예외 클래스 ────────────────────────────────────────────────

class WaitApproval(Exception):
    """워크플로우 중단 신호.

    에이전트가 민감한 작업을 수행하기 전에 발생시켜
    인간의 승인을 요청합니다.
    """

    def __init__(
        self,
        reason: str,
        context: dict[str, Any] | None = None,
        function_name: str = "",
        function_args: dict[str, Any] | None = None,
    ) -> None:
        self.reason = reason
        self.context = context or {}
        self.function_name = function_name
        self.function_args = function_args or {}
        super().__init__(
            f"Human approval required: {reason} "
            f"(function={function_name})"
        )


# ── 데코레이터 ─────────────────────────────────────────────────

def requires_human_approval(
    reason: str = "Sensitive operation requires human approval",
) -> Callable[[F], F]:
    """민감한 작업에 대한 인간 승인 요구 데코레이터.

    이 데코레이터가 붙은 함수가 호출되면 자동으로
    WaitApproval 예외를 발생시킵니다.

    Usage:
        @requires_human_approval("이메일 전송 전 승인 필요")
        async def send_email(to: str, body: str):
            ...
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            raise WaitApproval(
                reason=reason,
                function_name=func.__name__,
                function_args=kwargs,
            )
        return wrapper  # type: ignore[return-value]
    return decorator


# ── HITL Manager ───────────────────────────────────────────────

class HITLManager:
    """Human-in-the-loop 매니저.

    에이전트 상태를 SUSPENDED로 전환하고,
    인간의 개입 후 재개(Resume) 처리를 합니다.
    """

    def __init__(self, checkpoint_manager: CheckpointManager) -> None:
        self._checkpoint = checkpoint_manager
        self._pending_approvals: dict[str, dict[str, Any]] = {}

    async def suspend(
        self,
        state: AgentState,
        reason: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """에이전트를 SUSPENDED 상태로 전환합니다.

        현재 상태를 체크포인트로 저장하고,
        승인 대기 정보를 기록합니다.

        Args:
            state: 현재 에이전트 상태
            reason: 중단 사유
            context: 추가 컨텍스트 (함수명, 인자 등)
        """
        state.suspend(reason, context)

        # 체크포인트 저장
        self._checkpoint.save_checkpoint(
            state,
            checkpoint_type=CheckpointType.TRANSACTION,
            label=f"HITL: {reason}",
        )

        # 승인 대기 정보 저장
        self._pending_approvals[state.session_id] = {
            "reason": reason,
            "context": context or {},
            "step": state.step,
        }

        logger.info(
            f"⏸️ Agent suspended: session={state.session_id[:8]}... "
            f"reason='{reason}'"
        )

    async def resume(
        self,
        session_id: str,
        action: str = "approve",
        modified_data: dict[str, Any] | None = None,
    ) -> AgentState | None:
        """SUSPENDED 상태에서 에이전트를 재개합니다.

        Args:
            session_id: 세션 UUID
            action: "approve" | "reject" | "modify"
            modified_data: "modify" 시 패치할 데이터

        Returns:
            재개된 AgentState 또는 None (거절 시)
        """
        state = self._checkpoint.load_checkpoint(session_id)
        if state is None:
            logger.error(
                f"❌ Cannot resume: no checkpoint for session "
                f"{session_id[:8]}..."
            )
            return None

        if state.status != SessionStatus.SUSPENDED:
            logger.warning(
                f"⚠️ Session {session_id[:8]}... is not SUSPENDED "
                f"(status={state.status})"
            )

        if action == "reject":
            state.status = SessionStatus.FAILED
            self._checkpoint.save_checkpoint(
                state, checkpoint_type=CheckpointType.MILESTONE,
                label="HITL: Rejected by human",
            )
            logger.info(
                f"❌ Agent rejected: session={session_id[:8]}..."
            )
            # 대기 정보 정리
            self._pending_approvals.pop(session_id, None)
            return None

        if action == "modify" and modified_data:
            state.resume(modified_data)
            logger.info(
                f"✏️ Agent state modified and resumed: "
                f"session={session_id[:8]}..."
            )
        else:
            state.resume()
            logger.info(
                f"✅ Agent approved and resumed: "
                f"session={session_id[:8]}..."
            )

        # 대기 정보 정리
        self._pending_approvals.pop(session_id, None)

        return state

    def get_pending(self, session_id: str) -> dict[str, Any] | None:
        """대기 중인 승인 요청 정보를 조회합니다."""
        return self._pending_approvals.get(session_id)

    def list_pending(self) -> dict[str, dict[str, Any]]:
        """모든 대기 중인 승인 요청을 반환합니다."""
        return dict(self._pending_approvals)
