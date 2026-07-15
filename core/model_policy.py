"""Policy mapping from structured routing decisions to stable model aliases."""

from __future__ import annotations

from dataclasses import dataclass

from core.routing_schema import ExecutionTier, RoutingDecision, TaskType


@dataclass(frozen=True)
class ModelSelection:
    """Provider-independent execution choice returned to the runtime."""

    alias: str
    fallback_aliases: tuple[str, ...] = ()
    timeout_seconds: int = 120


class ModelPolicy:
    """Translate task attributes into provider-agnostic LiteLLM aliases."""

    DEFAULT_ALIASES = {
        ExecutionTier.LOCAL_FAST: "local-fast",
        ExecutionTier.LOCAL_QUALITY: "local-quality",
        ExecutionTier.CLOUD_GENERAL: "cloud-general",
        ExecutionTier.CLOUD_SPECIALIST: "cloud-specialist",
        ExecutionTier.DEEP_LOCAL: "deep-local",
    }
    DEFAULT_ELEVATION_ALIAS = "nvidia-glm52"

    def __init__(
        self,
        aliases: dict[ExecutionTier, str] | None = None,
        elevation_alias: str | None = None,
    ):
        self.aliases = {**self.DEFAULT_ALIASES, **(aliases or {})}
        self.elevation_alias = elevation_alias or self.DEFAULT_ELEVATION_ALIAS

    def select(self, decision: RoutingDecision) -> ModelSelection:
        if decision.local_only and decision.execution_tier in {
            ExecutionTier.CLOUD_GENERAL,
            ExecutionTier.CLOUD_SPECIALIST,
        }:
            decision = decision.model_copy(
                update={"execution_tier": ExecutionTier.LOCAL_QUALITY}
            )

        alias = self.aliases[decision.execution_tier]

        if decision.execution_tier == ExecutionTier.LOCAL_FAST:
            fallbacks = ("local-quality",)
            timeout = 45
        elif decision.execution_tier == ExecutionTier.LOCAL_QUALITY:
            fallbacks = () if decision.local_only else (self.elevation_alias, "cloud-general")
            timeout = 180
        elif decision.execution_tier == ExecutionTier.CLOUD_GENERAL:
            fallbacks = ("cloud-specialist", "local-quality")
            timeout = 180
        elif decision.execution_tier == ExecutionTier.CLOUD_SPECIALIST:
            fallbacks = ("cloud-general",)
            timeout = 300
        else:
            fallbacks = ("local-quality",)
            timeout = max(600, decision.latency_tolerance_seconds)

        if decision.task_type == TaskType.CODING and alias == "cloud-general":
            alias = "cloud-coding"
        elif decision.task_type == TaskType.REASONING and alias == "cloud-general":
            alias = "cloud-reasoning"
        elif decision.task_type == TaskType.LONG_CONTEXT and alias.startswith("cloud"):
            alias = "cloud-long-context"

        return ModelSelection(
            alias=alias,
            fallback_aliases=fallbacks,
            timeout_seconds=timeout,
        )

    def select_elevation(self, decision: RoutingDecision) -> ModelSelection:
        """Select the explicit quality-elevation target after local execution failure."""
        if decision.local_only:
            return ModelSelection(alias="local-quality", fallback_aliases=(), timeout_seconds=180)

        return ModelSelection(
            alias=self.elevation_alias,
            fallback_aliases=("cloud-specialist", "cloud-reasoning"),
            timeout_seconds=600,
        )
