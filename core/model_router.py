"""
ModelRouter — 작업 난이도 기반 모델 동적 선택
=============================================
작업의 복잡도를 분류하고, 최적의 모델을 자동 선택합니다.
단순 작업에 고가 모델을 사용하는 비용 낭비를 방지합니다.

티어 구조:
- SIMPLE: 요약, 분류, 번역 → Helper(Phi-4)
- STANDARD: 코딩, 디버깅 → Worker(Qwen 32B)
- COMPLEX: 아키텍처, 전략 → Cloud PM(Gemini/Claude/GPT)
"""

from __future__ import annotations

import logging
import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── 모델 별 가격 ($/1K tokens) ─────────────────────────────────
# 로컬 모델은 전력 비용만 존재하므로 근사치 사용
MODEL_COSTS: dict[str, dict[str, float]] = {
    # 로컬 모델 (전력 비용 근사치)
    "local-helper": {"input": 0.0001, "output": 0.0002},
    "local-worker": {"input": 0.0005, "output": 0.001},
    "local-router": {"input": 0.0003, "output": 0.0006},
    # 클라우드 모델
    "cloud-pm-gemini": {"input": 0.00125, "output": 0.005},
    "cloud-pm-claude": {"input": 0.003, "output": 0.015},
    "cloud-pm-gpt4": {"input": 0.005, "output": 0.015},
}


# ── 작업 티어 ──────────────────────────────────────────────────

class TaskTier(str, Enum):
    """작업 복잡도 티어."""
    SIMPLE = "simple"       # 요약, 분류, 번역, 포맷팅
    STANDARD = "standard"   # 코딩, 디버깅, 리팩토링, 분석
    COMPLEX = "complex"     # 아키텍처, 전략, 복잡 추론, 멀티-스텝


# ── 규칙 기반 분류 패턴 ────────────────────────────────────────

# SIMPLE 작업 키워드 (한/영)
# Note: \b는 한국어에서 작동하지 않으므로, 한국어 키워드는 단순 포함 검사
SIMPLE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(요약|summarize|summary)", re.IGNORECASE),
    re.compile(r"(번역|translate|translation)", re.IGNORECASE),
    re.compile(r"(분류|classify|categorize)", re.IGNORECASE),
    re.compile(r"(포맷|format|pretty.?print)", re.IGNORECASE),
    re.compile(r"(주석|comment|docstring)", re.IGNORECASE),
    re.compile(r"(정리|clean.?up|tidy)", re.IGNORECASE),
]

# COMPLEX 작업 키워드 (한/영)
COMPLEX_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(아키텍처|architecture|system.?design)", re.IGNORECASE),
    re.compile(r"(전략|strategy|roadmap)", re.IGNORECASE),
    re.compile(r"(마이그레이션|migrat|refactor.*전체)", re.IGNORECASE),
    re.compile(r"(보안.*감사|security.*audit|penetration)", re.IGNORECASE),
    re.compile(r"(설계|design.*pattern|trade.?off)", re.IGNORECASE),
    re.compile(r"(비교.*분석|comparative.*analysis)", re.IGNORECASE),
    re.compile(r"(최적화.*전략|optimization.*strategy)", re.IGNORECASE),
    re.compile(r"(멀티.?스텝|multi.?step|복잡)", re.IGNORECASE),
    re.compile(r"(재설계|redesign|overhaul)", re.IGNORECASE),
]


# ── 비용 추적 ──────────────────────────────────────────────────

class CostRecord(BaseModel):
    """개별 호출 비용 기록."""
    model: str
    tier: TaskTier
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0


class CostTracker(BaseModel):
    """세션 누적 비용 추적."""
    records: list[CostRecord] = Field(default_factory=list)
    alert_threshold_usd: float = 1.0

    @property
    def total_cost_usd(self) -> float:
        """누적 비용 합계."""
        return sum(r.estimated_cost_usd for r in self.records)

    @property
    def total_calls(self) -> int:
        """총 호출 횟수."""
        return len(self.records)

    def add_record(self, record: CostRecord) -> bool:
        """비용 기록을 추가합니다.

        Returns:
            True if alert threshold exceeded
        """
        self.records.append(record)
        exceeded = self.total_cost_usd > self.alert_threshold_usd
        if exceeded:
            logger.warning(
                f"💰 Cost alert: ${self.total_cost_usd:.4f} "
                f"exceeds threshold ${self.alert_threshold_usd:.2f}"
            )
        return exceeded

    def get_summary(self) -> dict[str, Any]:
        """비용 요약을 반환합니다."""
        by_model: dict[str, dict[str, Any]] = {}
        for r in self.records:
            if r.model not in by_model:
                by_model[r.model] = {
                    "calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost_usd": 0.0,
                }
            by_model[r.model]["calls"] += 1
            by_model[r.model]["input_tokens"] += r.input_tokens
            by_model[r.model]["output_tokens"] += r.output_tokens
            by_model[r.model]["cost_usd"] += r.estimated_cost_usd

        return {
            "total_calls": self.total_calls,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "by_model": by_model,
            "alert_threshold_usd": self.alert_threshold_usd,
            "threshold_exceeded": self.total_cost_usd > self.alert_threshold_usd,
        }


# ── 모델 라우터 ────────────────────────────────────────────────

class ModelRouter:
    """작업 난이도 기반 모델 동적 선택.

    Router의 라우팅 결정(LOCAL/CLOUD)과 독립적으로,
    작업 텍스트를 분석하여 최적 모델 티어를 결정합니다.
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
    ) -> None:
        cfg = config or {}
        self.enabled: bool = cfg.get("enabled", True)

        # 티어별 모델 목록
        tiers_cfg = cfg.get("tiers", {})
        self._tier_models: dict[TaskTier, list[str]] = {
            TaskTier.SIMPLE: tiers_cfg.get(
                "simple", {}
            ).get("models", ["local-helper"]),
            TaskTier.STANDARD: tiers_cfg.get(
                "standard", {}
            ).get("models", ["local-worker"]),
            TaskTier.COMPLEX: tiers_cfg.get(
                "complex", {}
            ).get("models", ["cloud-pm-gemini"]),
        }

        # 비용 추적
        cost_cfg = cfg.get("cost_tracking", {})
        self.cost_tracker = CostTracker(
            alert_threshold_usd=cost_cfg.get(
                "alert_threshold_usd", 1.0
            ),
        )

        logger.info(
            f"📊 ModelRouter initialized "
            f"(enabled={self.enabled})"
        )

    def classify_tier(
        self,
        task: str,
        route: str = "LOCAL",
    ) -> TaskTier:
        """작업의 난이도 티어를 분류합니다.

        Args:
            task: 사용자 입력 텍스트
            route: Router 결정 ("LOCAL" | "CLOUD")

        Returns:
            TaskTier: 분류된 티어
        """
        if not self.enabled:
            return TaskTier.STANDARD

        # CLOUD 라우팅이면 최소 STANDARD
        if route == "CLOUD":
            # COMPLEX 패턴 매칭 시 COMPLEX
            for pattern in COMPLEX_PATTERNS:
                if pattern.search(task):
                    return TaskTier.COMPLEX
            return TaskTier.STANDARD

        # LOCAL 라우팅에서 SIMPLE 패턴 매칭
        for pattern in SIMPLE_PATTERNS:
            if pattern.search(task):
                return TaskTier.SIMPLE

        # COMPLEX 패턴 매칭
        for pattern in COMPLEX_PATTERNS:
            if pattern.search(task):
                return TaskTier.COMPLEX

        # 기본값
        return TaskTier.STANDARD

    def get_model_for_tier(self, tier: TaskTier) -> str:
        """티어에 맞는 모델을 반환합니다.

        Args:
            tier: 작업 티어

        Returns:
            모델 이름
        """
        models = self._tier_models.get(tier, ["local-worker"])
        return models[0] if models else "local-worker"

    def estimate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """토큰 사용량 기반 비용을 추정합니다.

        Args:
            model: 모델 이름
            input_tokens: 입력 토큰 수
            output_tokens: 출력 토큰 수

        Returns:
            추정 비용 (USD)
        """
        costs = MODEL_COSTS.get(model, {"input": 0.001, "output": 0.002})
        cost = (
            (input_tokens / 1000) * costs["input"]
            + (output_tokens / 1000) * costs["output"]
        )
        return round(cost, 6)

    def track_usage(
        self,
        model: str,
        tier: TaskTier,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> CostRecord:
        """모델 사용을 추적합니다.

        Args:
            model: 사용한 모델
            tier: 작업 티어
            input_tokens: 입력 토큰
            output_tokens: 출력 토큰

        Returns:
            CostRecord: 생성된 비용 기록
        """
        estimated = self.estimate_cost(model, input_tokens, output_tokens)
        record = CostRecord(
            model=model,
            tier=tier,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=estimated,
        )
        self.cost_tracker.add_record(record)

        logger.debug(
            f"📊 Usage tracked: {model} "
            f"(in={input_tokens}, out={output_tokens}, "
            f"cost=${estimated:.6f})"
        )
        return record
