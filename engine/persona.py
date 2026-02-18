"""
PersonaManager — 동적 페르소나 토글 시스템
==========================================
페르소나 레지스트리를 관리하고, 에이전트의 시스템 프롬프트를
실행 컨텍스트에 따라 실시간으로 교체(핫스왑)합니다.

핵심 기능:
- YAML 기반 페르소나 레지스트리 로드 및 캐싱
- 핫스왑: 시스템 프롬프트 실시간 교체
- 전환 메타 메시지: 역할 변화 인지 메시지 생성
- 이벤트 로깅: 모든 페르소나 전환 기록
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from core.config_loader import ConfigLoader, PersonaConfig

logger = logging.getLogger(__name__)


class PersonaTransition:
    """페르소나 전환 이벤트 기록."""

    def __init__(
        self,
        old_persona: str,
        new_persona: str,
        reason: str = "",
    ) -> None:
        self.old_persona = old_persona
        self.new_persona = new_persona
        self.reason = reason
        self.timestamp = datetime.now(timezone.utc).isoformat()


class PersonaManager:
    """동적 페르소나 관리자.

    ConfigLoader를 통해 YAML 페르소나를 로드하고,
    핫스왑을 통해 에이전트의 시스템 프롬프트를 교체합니다.
    """

    def __init__(self, config_loader: ConfigLoader | None = None) -> None:
        self._config = config_loader or ConfigLoader()
        self._current_id: str = self._config.get(
            "system.default_persona", "worker"
        )
        self._current: PersonaConfig | None = None
        self._transition_log: list[PersonaTransition] = []

        # 초기 페르소나 로드
        try:
            self._current = self._config.load_persona(self._current_id)
        except FileNotFoundError:
            logger.warning(
                f"⚠️ Default persona '{self._current_id}' not found, "
                "using fallback"
            )

    @property
    def current_id(self) -> str:
        """현재 활성 페르소나 ID."""
        return self._current_id

    @property
    def current(self) -> PersonaConfig | None:
        """현재 활성 페르소나 설정."""
        return self._current

    @property
    def transitions(self) -> list[PersonaTransition]:
        """페르소나 전환 이력."""
        return list(self._transition_log)

    def switch_persona(
        self,
        persona_id: str,
        reason: str = "",
    ) -> PersonaConfig:
        """페르소나를 전환합니다.

        시스템 프롬프트를 교체하고 이벤트를 기록합니다.

        Args:
            persona_id: 전환할 페르소나 ID
            reason: 전환 사유

        Returns:
            새 페르소나 설정

        Raises:
            FileNotFoundError: 페르소나 YAML 파일이 없을 때
        """
        old_id = self._current_id
        new_persona = self._config.load_persona(persona_id)

        # 이벤트 기록
        transition = PersonaTransition(
            old_persona=old_id,
            new_persona=persona_id,
            reason=reason,
        )
        self._transition_log.append(transition)

        self._current_id = persona_id
        self._current = new_persona

        logger.info(
            f"🎭 Persona switch: {old_id} → {persona_id} "
            f"({new_persona.display_name}) | reason: {reason}"
        )

        return new_persona

    def get_system_prompt(
        self,
        context: dict[str, Any] | None = None,
    ) -> str:
        """현재 페르소나의 시스템 프롬프트를 반환합니다.

        Jinja2를 통해 런타임 변수가 주입됩니다.

        Args:
            context: 템플릿 변수 (사용자 이름, 날짜 등)

        Returns:
            렌더링된 시스템 프롬프트
        """
        if self._current is None:
            return "You are a helpful AI assistant."

        if context:
            return self._config.render_prompt(
                self._current.system_prompt, context
            )
        return self._current.system_prompt

    def get_transition_message(
        self,
        old_id: str | None = None,
        new_id: str | None = None,
    ) -> str:
        """페르소나 전환 시 LLM에 주입할 메타 메시지를 생성합니다.

        모델의 주의(Attention) 메커니즘을 새로운 역할에 집중시킵니다.

        Args:
            old_id: 이전 페르소나 ID (None이면 최근 전환에서 추출)
            new_id: 새 페르소나 ID (None이면 현재 페르소나)

        Returns:
            역할 전환 인지 메시지
        """
        if old_id is None and self._transition_log:
            old_id = self._transition_log[-1].old_persona
        if new_id is None:
            new_id = self._current_id

        old_name = old_id or "Unknown"
        try:
            new_persona = self._config.load_persona(new_id or self._current_id)
            new_name = new_persona.display_name
        except FileNotFoundError:
            new_name = new_id or "Unknown"

        return (
            f"[시스템 알림] 당신의 역할이 '{old_name}'에서 "
            f"'{new_name}'(으)로 변경되었습니다. "
            f"새로운 관점으로 이전 대화를 분석하십시오. "
            f"이전의 판단이나 결론에 구애받지 말고, "
            f"현재 역할의 전문성과 기준으로 독립적으로 평가하십시오."
        )

    def get_temperature(self) -> float:
        """현재 페르소나의 temperature 값."""
        if self._current is None:
            return 0.7
        return self._current.temperature

    def get_allowed_tools(self) -> list[str]:
        """현재 페르소나의 허용 도구 목록."""
        if self._current is None:
            return []
        return self._current.allowed_tools

    def available_personas(self) -> list[str]:
        """사용 가능한 페르소나 목록."""
        return self._config.list_personas()
