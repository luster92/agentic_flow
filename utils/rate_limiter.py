"""
Rate Limiter — Retry Storm 방어
================================
글로벌 LLM 호출 빈도를 제한하여 로컬 GPU 독점 문제를 방지합니다.
시간 윈도우 내 최대 호출 횟수를 초과하면 호출을 거부합니다.

Async-safe: asyncio.Lock으로 동시 접근을 보호합니다.
"""

import asyncio
import logging
from collections import deque
from time import time

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    시간 기반 Sliding Window Rate Limiter (async-safe).

    Args:
        max_calls: 윈도우 시간 내 최대 허용 호출 수
        window_sec: 시간 윈도우 (초)
    """

    def __init__(self, max_calls: int = 15, window_sec: int = 60):
        self.max_calls = max_calls
        self.window = window_sec
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def allow(self) -> bool:
        """호출 허용 여부를 판단합니다. 허용 시 호출 기록. (async-safe)"""
        async with self._lock:
            now = time()

            # 윈도우 밖의 오래된 기록 제거
            while self._calls and self._calls[0] < now - self.window:
                self._calls.popleft()

            if len(self._calls) >= self.max_calls:
                logger.warning(
                    f"⛔ Rate Limit 초과: {len(self._calls)}/{self.max_calls} "
                    f"(window={self.window}s)"
                )
                return False

            self._calls.append(now)
            return True

    async def remaining(self) -> int:
        """남은 허용 호출 수. (async-safe)"""
        async with self._lock:
            now = time()
            while self._calls and self._calls[0] < now - self.window:
                self._calls.popleft()
            return max(0, self.max_calls - len(self._calls))

    def allow_sync(self) -> bool:
        """동기 호환 래퍼 — 이벤트 루프 밖에서 사용."""
        now = time()
        while self._calls and self._calls[0] < now - self.window:
            self._calls.popleft()
        if len(self._calls) >= self.max_calls:
            return False
        self._calls.append(now)
        return True

    def remaining_sync(self) -> int:
        """동기 호환 래퍼 — 이벤트 루프 밖에서 사용."""
        now = time()
        while self._calls and self._calls[0] < now - self.window:
            self._calls.popleft()
        return max(0, self.max_calls - len(self._calls))

    def reset(self) -> None:
        """호출 기록 초기화."""
        self._calls.clear()


# 글로벌 인스턴스 (프로젝트 전체에서 공유)
global_limiter = RateLimiter(max_calls=15, window_sec=60)
