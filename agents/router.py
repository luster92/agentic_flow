"""Structured hybrid task router.

The router classifies task attributes. It does not select concrete providers;
`core.model_policy.ModelPolicy` maps the decision to stable LiteLLM aliases.
"""

from __future__ import annotations

import json
import logging
import re

from openai import AsyncOpenAI
from pydantic import ValidationError

from core.routing_schema import ExecutionTier, RiskLevel, RoutingDecision, TaskType

logger = logging.getLogger(__name__)

ROUTER_SYSTEM_PROMPT = """You classify requests for a hybrid AI runtime.
Return one valid JSON object matching this schema exactly:
{
  "task_type": "general|coding|reasoning|long_context|vision|extraction",
  "execution_tier": "local_fast|local_quality|cloud_general|cloud_specialist|deep_local",
  "risk_level": "low|medium|high",
  "requires_tools": true,
  "requires_vision": false,
  "requires_human_approval": false,
  "local_only": false,
  "latency_tolerance_seconds": 30,
  "reason": "one concise sentence",
  "confidence": 0.0
}

Rules:
- Prefer local_fast for formatting, translation, extraction, and simple questions.
- Prefer local_quality for ordinary coding, debugging, summarization, and tool use.
- Prefer cloud_specialist for security review, architecture, proofs, or complex reasoning.
- Use deep_local only when the user explicitly requires local-only deep reasoning and accepts minute-scale latency.
- Set local_only when the request explicitly forbids external transmission or contains clearly sensitive internal data.
- High-risk destructive, financial, security-sensitive, or irreversible actions require human approval.
- Do not expose chain-of-thought. Return JSON only."""

FAST_LOCAL_PATTERNS = [
    r"^(hi|hello|안녕|감사|thanks|thank you)\b",
    r"^/",
    r"^\s*\d+\s*[+\-*/]",
    r"(주석|포맷팅|format|번역|translate|docstring|lint|type hint|추출|extract)",
]

CODING_PATTERNS = [
    r"(디버깅|debug|fix|bug|오류|리팩터링|refactor)",
    r"(코드|code|함수|function|class|모듈|module|테스트|test)",
]

CLOUD_SPECIALIST_PATTERNS = [
    r"(아키텍처|architecture).*(설계|design)",
    r"(설계|design).*(아키텍처|architecture)",
    r"(보안|security).*(감사|audit|review|검토)",
    r"(수학적 증명|mathematical proof|정리.*증명)",
    r"(전략|strategy).*(복잡|전사|enterprise|장기)",
]

LOCAL_ONLY_PATTERNS = [
    r"(외부.*전송.*금지|외부망.*금지|로컬에서만|local only|폐쇄망|사내기밀|기밀정보)",
]

HIGH_RISK_PATTERNS = [
    r"(삭제|delete|drop table|rm -rf|결제|payment|송금|transfer)",
    r"(배포|deploy|production|운영반영|권한변경|permission)",
]

VISION_PATTERNS = [r"(이미지|image|사진|screenshot|스크린샷|vision)"]
LONG_CONTEXT_PATTERNS = [r"(전체 문서|긴 문서|long context|책 전체|repository 전체|레포 전체)"]
DEEP_LOCAL_PATTERNS = [r"(glm.?5\.2|colibri|deep local|느려도.*로컬|로컬.*심층)"]


class Router:
    """Rule-first structured router with an LLM fallback."""

    def __init__(
        self,
        base_url: str = "http://localhost:4000",
        model: str = "local-router",
    ):
        self.client = AsyncOpenAI(base_url=base_url, api_key="not-needed")
        self.model = model

    async def decide(self, user_message: str) -> RoutingDecision:
        fast = self._fast_decision(user_message)
        if fast is not None:
            return fast

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0,
                max_tokens=400,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content or "{}"
            return self._parse_decision(raw)
        except Exception as exc:
            logger.exception("Router call failed; using local-quality fallback")
            return RoutingDecision(
                task_type=self._detect_task_type(user_message),
                execution_tier=ExecutionTier.LOCAL_QUALITY,
                reason=f"Router fallback: {type(exc).__name__}",
                confidence=0.2,
            )

    async def route(self, user_message: str) -> dict:
        """Backward-compatible response consumed by the current main.py."""
        decision = await self.decide(user_message)
        payload = decision.model_dump(mode="json")
        payload.update(
            {
                "destination": decision.destination,
                "thinking": "",
                "route": decision.destination,
            }
        )
        return payload

    def _parse_decision(self, raw_response: str) -> RoutingDecision:
        try:
            return RoutingDecision.model_validate(json.loads(raw_response))
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            logger.warning("Invalid structured routing response: %s", exc)
            return RoutingDecision(
                execution_tier=ExecutionTier.LOCAL_QUALITY,
                reason="Invalid router response; safe local fallback",
                confidence=0.1,
            )

    def _fast_decision(self, message: str) -> RoutingDecision | None:
        local_only = self._matches(LOCAL_ONLY_PATTERNS, message)
        high_risk = self._matches(HIGH_RISK_PATTERNS, message)
        requires_vision = self._matches(VISION_PATTERNS, message)
        task_type = self._detect_task_type(message)

        if self._matches(DEEP_LOCAL_PATTERNS, message) and local_only:
            return RoutingDecision(
                task_type=TaskType.REASONING,
                execution_tier=ExecutionTier.DEEP_LOCAL,
                local_only=True,
                latency_tolerance_seconds=1800,
                reason="Explicit local-only deep reasoning request",
                confidence=0.98,
            )

        if high_risk:
            return RoutingDecision(
                task_type=task_type,
                execution_tier=(
                    ExecutionTier.LOCAL_QUALITY if local_only else ExecutionTier.CLOUD_SPECIALIST
                ),
                risk_level=RiskLevel.HIGH,
                requires_tools=True,
                requires_human_approval=True,
                local_only=local_only,
                reason="Potentially destructive or irreversible action",
                confidence=0.95,
            )

        if requires_vision:
            return RoutingDecision(
                task_type=TaskType.VISION,
                execution_tier=(
                    ExecutionTier.LOCAL_QUALITY if local_only else ExecutionTier.CLOUD_SPECIALIST
                ),
                requires_vision=True,
                local_only=local_only,
                reason="Visual input requires a vision-capable deployment",
                confidence=0.95,
            )

        if self._matches(CLOUD_SPECIALIST_PATTERNS, message):
            return RoutingDecision(
                task_type=task_type,
                execution_tier=(
                    ExecutionTier.LOCAL_QUALITY if local_only else ExecutionTier.CLOUD_SPECIALIST
                ),
                local_only=local_only,
                reason="Specialist reasoning pattern matched",
                confidence=0.9,
            )

        if self._matches(FAST_LOCAL_PATTERNS, message):
            return RoutingDecision(
                task_type=task_type,
                execution_tier=ExecutionTier.LOCAL_FAST,
                local_only=local_only,
                reason="Low-complexity deterministic rule matched",
                confidence=0.95,
            )

        if self._matches(CODING_PATTERNS, message):
            return RoutingDecision(
                task_type=TaskType.CODING,
                execution_tier=ExecutionTier.LOCAL_QUALITY,
                requires_tools=True,
                local_only=local_only,
                reason="Standard coding task matched",
                confidence=0.85,
            )

        return None

    def _detect_task_type(self, message: str) -> TaskType:
        if self._matches(VISION_PATTERNS, message):
            return TaskType.VISION
        if self._matches(LONG_CONTEXT_PATTERNS, message):
            return TaskType.LONG_CONTEXT
        if self._matches(CODING_PATTERNS, message):
            return TaskType.CODING
        if self._matches(CLOUD_SPECIALIST_PATTERNS, message):
            return TaskType.REASONING
        if re.search(r"(추출|extract|json|표로|구조화)", message, re.IGNORECASE):
            return TaskType.EXTRACTION
        return TaskType.GENERAL

    @staticmethod
    def _matches(patterns: list[str], message: str) -> bool:
        return any(re.search(pattern, message, re.IGNORECASE) for pattern in patterns)
