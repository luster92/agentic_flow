"""
Engine Layer
============
에이전트 실행 엔진: 동적 페르소나, 적대적 검증, HITL 인터럽트를 제공합니다.
"""

from engine.persona import PersonaManager
from engine.adversarial import DebateLoop, DebateResult
from engine.hitl import HITLManager, WaitApproval, requires_human_approval

__all__ = [
    "PersonaManager",
    "DebateLoop",
    "DebateResult",
    "HITLManager",
    "WaitApproval",
    "requires_human_approval",
]
