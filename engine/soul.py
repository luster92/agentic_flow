"""
SoulManager — SOUL.md 파서 & 시스템 프롬프트 주입
===================================================
OpenClaw의 SOUL.md 파일에서 에이전트의 성격, 말투, 원칙을
파싱하여 시스템 프롬프트에 주입합니다.

SOUL.md 형식:
```markdown
# Personality
친절하고 전문적인 시니어 엔지니어

# Tone
- 존댓말 사용
- 기술 용어는 한국어 우선

# Principles
1. 정확성이 최우선
2. 보안을 항상 고려
```
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SoulManager:
    """SOUL.md 파서 → 시스템 프롬프트 주입.

    OpenClaw 생태계에서 에이전트의 '영혼'을 정의하는
    SOUL.md 파일을 파싱하여 시스템 프롬프트에 반영합니다.
    """

    # SOUL.md에서 추출할 섹션 이름
    SECTIONS = ["personality", "tone", "principles", "constraints", "style"]

    def __init__(
        self,
        soul_path: str = "~/.openclaw/SOUL.md",
    ) -> None:
        self.soul_path = Path(os.path.expanduser(soul_path))
        self._sections: dict[str, str] = {}
        self._loaded: bool = False

        if self.soul_path.exists():
            self.load()

    def load(self) -> dict[str, str]:
        """SOUL.md 파일을 파싱합니다.

        Returns:
            섹션별 내용 딕셔너리
        """
        if not self.soul_path.exists():
            logger.debug(f"📜 SOUL.md not found: {self.soul_path}")
            return {}

        try:
            content = self.soul_path.read_text(encoding="utf-8")
            self._sections = self._parse_sections(content)
            self._loaded = True
            logger.info(
                f"📜 SOUL.md loaded: {len(self._sections)} sections "
                f"({', '.join(self._sections.keys())})"
            )
            return self._sections.copy()
        except Exception as e:
            logger.error(f"❌ Failed to load SOUL.md: {e}")
            return {}

    def _parse_sections(self, content: str) -> dict[str, str]:
        """마크다운 헤더 기반 섹션 파싱.

        Args:
            content: SOUL.md 전체 내용

        Returns:
            {section_name: section_content} 딕셔너리
        """
        sections: dict[str, str] = {}
        current_section: str | None = None
        current_lines: list[str] = []

        for line in content.split("\n"):
            # 헤더 감지 (# 또는 ##)
            header_match = re.match(r"^#{1,2}\s+(.+)$", line.strip())
            if header_match:
                # 이전 섹션 저장
                if current_section:
                    sections[current_section] = "\n".join(
                        current_lines
                    ).strip()

                section_name = header_match.group(1).strip().lower()
                # 알려진 섹션만 추출
                if section_name in self.SECTIONS:
                    current_section = section_name
                    current_lines = []
                else:
                    current_section = section_name
                    current_lines = []
            elif current_section is not None:
                current_lines.append(line)

        # 마지막 섹션 저장
        if current_section:
            sections[current_section] = "\n".join(
                current_lines
            ).strip()

        return sections

    def inject_into_prompt(self, base_prompt: str) -> str:
        """기존 시스템 프롬프트에 SOUL 정보를 주입합니다.

        Args:
            base_prompt: 원본 시스템 프롬프트

        Returns:
            SOUL 정보가 추가된 시스템 프롬프트
        """
        if not self._sections:
            return base_prompt

        soul_block_parts: list[str] = [
            "\n\n--- SOUL (Agent Identity) ---"
        ]

        for section, content in self._sections.items():
            if content:
                soul_block_parts.append(
                    f"\n[{section.upper()}]\n{content}"
                )

        soul_block_parts.append("\n--- END SOUL ---\n")

        return base_prompt + "".join(soul_block_parts)

    @property
    def personality(self) -> str:
        """성격 섹션."""
        return self._sections.get("personality", "")

    @property
    def tone(self) -> str:
        """말투 섹션."""
        return self._sections.get("tone", "")

    @property
    def principles(self) -> str:
        """원칙 섹션."""
        return self._sections.get("principles", "")

    @property
    def is_loaded(self) -> bool:
        """SOUL.md 로드 여부."""
        return self._loaded

    def get_summary(self) -> dict[str, Any]:
        """SOUL 상태 요약."""
        return {
            "loaded": self._loaded,
            "path": str(self.soul_path),
            "sections": list(self._sections.keys()),
            "total_chars": sum(
                len(v) for v in self._sections.values()
            ),
        }
