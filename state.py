"""
AgenticState — 하위 호환 Alias
===============================
기존 import 경로 유지를 위한 리다이렉트 모듈.
신규 코드는 core.state.AgentState를 직접 import하세요.

Usage (기존 호환):
    from state import AgenticState
    state = AgenticState()

Usage (신규):
    from core.state import AgentState
    state = AgentState()
"""

from core.state import AgentState

# 하위 호환: 기존 코드에서 AgenticState로 사용
AgenticState = AgentState

__all__ = ["AgenticState", "AgentState"]
