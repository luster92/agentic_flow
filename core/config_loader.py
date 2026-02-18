"""
ConfigLoader — 계층적 설정 로더 + Jinja2 템플릿 렌더링
=====================================================
설정 파일을 계층적으로 로드하고, Jinja2를 통해 런타임 변수를 주입합니다.

계층 구조:
- base.yaml: 전역 기본 설정
- personas/*.yaml: 페르소나별 시스템 프롬프트 및 파라미터
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

import yaml
from jinja2 import Environment, BaseLoader

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────
DEFAULT_CONFIGS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "configs",
)


class PersonaConfig:
    """페르소나 설정 데이터."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.persona_id: str = data.get("persona_id", "unknown")
        self.display_name: str = data.get("display_name", "Unknown")
        self.system_prompt: str = data.get("system_prompt", "")
        self.parameters: dict[str, Any] = data.get("parameters", {})
        self.allowed_tools: list[str] = data.get("allowed_tools", [])
        self.voice_tone: str = data.get("voice_tone", "neutral")
        self._raw = data

    @property
    def temperature(self) -> float:
        return float(self.parameters.get("temperature", 0.7))

    @property
    def top_p(self) -> float:
        return float(self.parameters.get("top_p", 0.9))

    @property
    def max_tokens(self) -> int:
        return int(self.parameters.get("max_tokens", 4096))

    def to_dict(self) -> dict[str, Any]:
        return dict(self._raw)


class ConfigLoader:
    """계층적 설정 로더 (Singleton).

    configs/ 디렉토리의 YAML 파일을 읽고 캐싱합니다.
    Jinja2 템플릿 엔진으로 런타임 변수 주입을 지원합니다.
    """

    _instance: ConfigLoader | None = None
    _initialized: bool = False

    def __new__(cls, configs_dir: str = DEFAULT_CONFIGS_DIR) -> ConfigLoader:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, configs_dir: str = DEFAULT_CONFIGS_DIR) -> None:
        if ConfigLoader._initialized:
            return
        ConfigLoader._initialized = True

        self.configs_dir = configs_dir
        self._persona_cache: dict[str, PersonaConfig] = {}
        self._base_config: dict[str, Any] = {}
        self._jinja_env = Environment(loader=BaseLoader())

        self._load_base()
        logger.info(f"⚙️ ConfigLoader initialized (dir: {self.configs_dir})")

    def _load_base(self) -> None:
        """base.yaml 기본 설정 로드."""
        base_path = os.path.join(self.configs_dir, "base.yaml")
        if os.path.exists(base_path):
            try:
                with open(base_path, "r", encoding="utf-8") as f:
                    self._base_config = yaml.safe_load(f) or {}
                logger.info("⚙️ Base config loaded")
            except Exception as e:
                logger.error(f"❌ Failed to load base.yaml: {e}")
                self._base_config = {}
        else:
            logger.warning(f"⚠️ base.yaml not found at {base_path}")
            self._base_config = {}

    @property
    def base(self) -> dict[str, Any]:
        """전역 기본 설정."""
        return self._base_config

    def get(self, key: str, default: Any = None) -> Any:
        """점(.) 표기법으로 중첩 설정 값 조회.

        Example:
            config.get("system.debate_max_rounds", 3)
        """
        keys = key.split(".")
        value: Any = self._base_config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
            if value is None:
                return default
        return value

    def load_persona(self, persona_id: str) -> PersonaConfig:
        """페르소나 설정 로드 (캐싱).

        Args:
            persona_id: 페르소나 파일명 (확장자 없이)

        Returns:
            PersonaConfig 객체

        Raises:
            FileNotFoundError: 페르소나 YAML 파일이 없을 때
        """
        if persona_id in self._persona_cache:
            return self._persona_cache[persona_id]

        persona_path = os.path.join(
            self.configs_dir, "personas", f"{persona_id}.yaml"
        )
        if not os.path.exists(persona_path):
            raise FileNotFoundError(
                f"Persona config not found: {persona_path}"
            )

        try:
            with open(persona_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            persona = PersonaConfig(data)
            self._persona_cache[persona_id] = persona
            logger.info(
                f"⚙️ Persona loaded: {persona.display_name} "
                f"(id={persona.persona_id})"
            )
            return persona

        except Exception as e:
            logger.error(f"❌ Failed to load persona '{persona_id}': {e}")
            raise

    def list_personas(self) -> list[str]:
        """사용 가능한 페르소나 ID 목록."""
        personas_dir = os.path.join(self.configs_dir, "personas")
        if not os.path.isdir(personas_dir):
            return []
        return [
            f.replace(".yaml", "")
            for f in os.listdir(personas_dir)
            if f.endswith(".yaml")
        ]

    def render_prompt(
        self,
        template_str: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Jinja2 템플릿에 런타임 변수를 주입합니다.

        Args:
            template_str: Jinja2 템플릿 문자열
            context: 주입할 변수 딕셔너리

        Returns:
            렌더링된 문자열
        """
        try:
            template = self._jinja_env.from_string(template_str)
            return template.render(**(context or {}))
        except Exception as e:
            logger.error(f"❌ Template rendering failed: {e}")
            return template_str  # 렌더링 실패 시 원본 반환

    def reload(self) -> None:
        """설정을 다시 로드합니다 (캐시 초기화)."""
        self._persona_cache.clear()
        self._load_base()
        logger.info("🔄 Config reloaded")

    @classmethod
    def reset(cls) -> None:
        """Singleton 인스턴스를 리셋합니다 (테스트용)."""
        cls._instance = None
        cls._initialized = False
