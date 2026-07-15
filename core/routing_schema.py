"""Structured routing contract shared by routers, policy, and runtime."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class TaskType(str, Enum):
    GENERAL = "general"
    CODING = "coding"
    REASONING = "reasoning"
    LONG_CONTEXT = "long_context"
    VISION = "vision"
    EXTRACTION = "extraction"


class ExecutionTier(str, Enum):
    LOCAL_FAST = "local_fast"
    LOCAL_QUALITY = "local_quality"
    CLOUD_GENERAL = "cloud_general"
    CLOUD_SPECIALIST = "cloud_specialist"
    DEEP_LOCAL = "deep_local"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RoutingDecision(BaseModel):
    task_type: TaskType = TaskType.GENERAL
    execution_tier: ExecutionTier = ExecutionTier.LOCAL_QUALITY
    risk_level: RiskLevel = RiskLevel.LOW
    requires_tools: bool = False
    requires_vision: bool = False
    requires_human_approval: bool = False
    local_only: bool = False
    latency_tolerance_seconds: int = Field(default=30, ge=1, le=3600)
    reason: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @property
    def destination(self) -> str:
        """Backward-compatible LOCAL/CLOUD destination."""
        if self.execution_tier in {
            ExecutionTier.CLOUD_GENERAL,
            ExecutionTier.CLOUD_SPECIALIST,
        }:
            return "CLOUD"
        return "LOCAL"
