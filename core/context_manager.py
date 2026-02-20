import logging
from typing import Optional
from core.state import AgentState
from core.handoff import HandoffManager, HandoffData
from utils.history_manager import HistoryManager

logger = logging.getLogger("context_monitor")

class ContextMonitor:
    """메시지 턴 수 또는 토큰 수를 기반으로 컨텍스트 수명주기를 관리합니다."""
    
    def __init__(self, max_turns: int = 20):
        self.max_turns = max_turns

    def should_spawn_new_session(self, state: AgentState) -> bool:
        """컨텍스트가 임계치를 초과했는지 확인합니다."""
        # TODO: 실제 토큰 수 기반으로 고도화 (현재는 turn_number 기반)
        if state.turn_number >= self.max_turns:
            return True
        return False

    async def execute_handoff(
        self, 
        state: AgentState, 
        history: HistoryManager,
        project_dir: str
    ) -> AgentState:
        """세션을 종료하고 HANDOFF를 생성한 뒤 새 세션을 스폰합니다."""
        logger.info("🔄 Context degradation detected. Executing Hand-off protocol...")
        
        mgr = HandoffManager(project_dir)
        
        # 여기서 LLM을 호출하여 요약(HANDOFF 데이터)을 생성하게 할 수도 있습니다.
        # 심플리티를 위해 현재의 internal_summary와 큐 상태를 기반으로 작성합니다.
        
        next_steps = []
        if state.task_queue:
            next_steps = [f"Complete sub-task: {t['desc']}" for t in state.task_queue]
            
        data = HandoffData(
            current_goal=state.internal_summary or "Continue previous conversation objectives.",
            progress=[f"Completed {state.step} steps in previous session."],
            failed_attempts=[],
            next_steps=next_steps
        )
        
        mgr.generate_handoff(data)
        
        # 새 세션 스폰
        logger.info("✨ Spawning new AgentState iteration")
        history.clear() 
        new_state = AgentState(
            session_id=state.session_id, # 같은 세션 ID 유지 혹은 새로 발급 가능
            internal_summary=state.internal_summary,
            task_queue=state.task_queue
        )
        new_state.turn_number = 0
        
        return new_state
