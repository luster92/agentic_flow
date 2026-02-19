"""
MemoryFileManager — MEMORY.md 읽기/쓰기 + 검색
=================================================
OpenClaw의 MEMORY.md 파일과 연동하여 에이전트의
장기 기억을 관리합니다.

MEMORY.md 형식:
```markdown
## 2026-02-19
- **project_setup**: Next.js 14 + TypeScript로 프로젝트 초기화
- **user_preference**: 사용자는 한국어 코드 주석을 선호함

## 2026-02-18
- **debug_tip**: SQLite에서 WAL 모드 사용 시 동시 읽기 성능 향상
```
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class MemoryEntry:
    """개별 메모리 항목."""

    def __init__(
        self,
        key: str,
        content: str,
        date: str = "",
    ) -> None:
        self.key = key
        self.content = content
        self.date = date or datetime.now(timezone.utc).strftime(
            "%Y-%m-%d"
        )

    def to_markdown(self) -> str:
        """마크다운 리스트 아이템으로 변환."""
        return f"- **{self.key}**: {self.content}"

    def __repr__(self) -> str:
        return f"MemoryEntry(key={self.key!r}, date={self.date})"


class MemoryFileManager:
    """MEMORY.md 읽기/쓰기 + 키워드 기반 검색.

    OpenClaw 생태계의 MEMORY.md 파일과 연동하여
    에이전트의 장기 기억을 관리합니다.
    """

    def __init__(
        self,
        memory_path: str = "~/.openclaw/MEMORY.md",
    ) -> None:
        self.memory_path = Path(os.path.expanduser(memory_path))
        self._memories: list[MemoryEntry] = []
        self._loaded: bool = False

        if self.memory_path.exists():
            self.load_memories()

    def load_memories(self) -> list[MemoryEntry]:
        """MEMORY.md 파일에서 메모리를 로드합니다.

        Returns:
            로드된 MemoryEntry 리스트
        """
        if not self.memory_path.exists():
            logger.debug(
                f"🧠 MEMORY.md not found: {self.memory_path}"
            )
            return []

        try:
            content = self.memory_path.read_text(encoding="utf-8")
            self._memories = self._parse_memories(content)
            self._loaded = True
            logger.info(
                f"🧠 MEMORY.md loaded: "
                f"{len(self._memories)} entries"
            )
            return self._memories.copy()
        except Exception as e:
            logger.error(f"❌ Failed to load MEMORY.md: {e}")
            return []

    def _parse_memories(
        self, content: str
    ) -> list[MemoryEntry]:
        """MEMORY.md를 파싱하여 MemoryEntry 리스트로 변환.

        Args:
            content: MEMORY.md 전체 내용

        Returns:
            MemoryEntry 리스트
        """
        entries: list[MemoryEntry] = []
        current_date = ""

        for line in content.split("\n"):
            # 날짜 헤더 감지
            date_match = re.match(
                r"^#{1,3}\s+(\d{4}-\d{2}-\d{2})", line.strip()
            )
            if date_match:
                current_date = date_match.group(1)
                continue

            # 메모리 항목 감지
            entry_match = re.match(
                r"^-\s+\*\*(.+?)\*\*:\s*(.+)$", line.strip()
            )
            if entry_match:
                key = entry_match.group(1).strip()
                content_text = entry_match.group(2).strip()
                entries.append(MemoryEntry(
                    key=key,
                    content=content_text,
                    date=current_date,
                ))

        return entries

    def add_memory(
        self,
        key: str,
        content: str,
    ) -> None:
        """새 메모리를 추가하고 파일에 저장합니다.

        Args:
            key: 메모리 키 (예: "user_preference")
            content: 메모리 내용
        """
        entry = MemoryEntry(key=key, content=content)
        self._memories.append(entry)

        # 파일에 추가
        self._append_to_file(entry)
        logger.info(f"🧠 Memory added: {key}")

    def _append_to_file(self, entry: MemoryEntry) -> None:
        """파일에 메모리 항목을 추가합니다."""
        try:
            # 디렉토리 생성
            self.memory_path.parent.mkdir(
                parents=True, exist_ok=True
            )

            # 기존 파일 읽기
            existing = ""
            if self.memory_path.exists():
                existing = self.memory_path.read_text(
                    encoding="utf-8"
                )

            today = entry.date
            date_header = f"\n## {today}\n"

            # 오늘 날짜 헤더가 이미 있는지 확인
            if f"## {today}" in existing:
                # 기존 날짜 섹션에 추가
                parts = existing.split(f"## {today}")
                if len(parts) >= 2:
                    # 다음 섹션 시작 전에 삽입
                    rest = parts[1]
                    next_section = rest.find("\n## ")
                    if next_section >= 0:
                        insert_point = next_section
                        new_content = (
                            parts[0]
                            + f"## {today}"
                            + rest[:insert_point]
                            + f"\n{entry.to_markdown()}"
                            + rest[insert_point:]
                        )
                    else:
                        new_content = (
                            existing.rstrip()
                            + f"\n{entry.to_markdown()}\n"
                        )
                else:
                    new_content = (
                        existing.rstrip()
                        + f"\n{entry.to_markdown()}\n"
                    )
            else:
                # 새 날짜 섹션 생성 (파일 맨 앞에)
                if existing:
                    new_content = (
                        date_header
                        + f"{entry.to_markdown()}\n\n"
                        + existing
                    )
                else:
                    new_content = (
                        f"# Agent Memory\n"
                        + date_header
                        + f"{entry.to_markdown()}\n"
                    )

            self.memory_path.write_text(
                new_content, encoding="utf-8"
            )

        except OSError as e:
            logger.error(
                f"❌ Failed to write MEMORY.md: {e}"
            )

    def search(
        self,
        query: str,
        top_k: int = 5,
    ) -> list[str]:
        """키워드 기반 메모리 검색.

        Args:
            query: 검색 쿼리
            top_k: 반환할 최대 결과 수

        Returns:
            관련 메모리 내용 리스트
        """
        if not self._memories:
            return []

        query_lower = query.lower()
        query_words = set(query_lower.split())

        # 키워드 매칭 스코어 계산
        scored: list[tuple[float, MemoryEntry]] = []
        for entry in self._memories:
            entry_text = (
                f"{entry.key} {entry.content}".lower()
            )
            entry_words = set(entry_text.split())

            # 교집합 크기 / 쿼리 단어 수 = 매칭 비율
            overlap = len(query_words & entry_words)
            if overlap > 0:
                score = overlap / max(len(query_words), 1)
                scored.append((score, entry))

        # 스코어 내림차순 정렬
        scored.sort(key=lambda x: x[0], reverse=True)

        results = [
            f"[{entry.date}] {entry.key}: {entry.content}"
            for _, entry in scored[:top_k]
        ]
        return results

    @property
    def is_loaded(self) -> bool:
        """MEMORY.md 로드 여부."""
        return self._loaded

    @property
    def entry_count(self) -> int:
        """저장된 메모리 수."""
        return len(self._memories)

    def get_summary(self) -> dict[str, Any]:
        """메모리 상태 요약."""
        dates = set(e.date for e in self._memories)
        return {
            "loaded": self._loaded,
            "path": str(self.memory_path),
            "total_entries": len(self._memories),
            "unique_dates": len(dates),
            "keys": list(set(e.key for e in self._memories)),
        }
