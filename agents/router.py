"""
Router Agent - DeepSeek-R1-Distill-Llama-8B
============================================
작업 분석 및 경로 배정 역할:
- <think> 태그를 활용한 논리적 라우팅 수행
- 작업 복잡도에 따라 LOCAL 또는 CLOUD 경로 결정

라우팅 기준:
- LOCAL: 코드 구현, 디버깅, 리팩토링, 단순 질문 등
- CLOUD: 고난도 기획, 아키텍처 설계, 복잡한 추론 등
"""

import re
import json
import logging
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# ── Router 시스템 프롬프트 ────────────────────────────────────
ROUTER_SYSTEM_PROMPT = """You are a task router for a hybrid AI system.
Your job is to analyze user requests and decide the best execution path.

You MUST respond with a valid JSON object in this EXACT format:
{
  "thinking": "[Your reasoning about task complexity here]",
  "route": "LOCAL or CLOUD",
  "reason": "[One-line reason for the routing decision]"
}

Routing criteria:
- LOCAL: Code implementation, debugging, refactoring, simple Q&A, formatting, documentation, translation, standard programming tasks.
- CLOUD: High-level architecture design, complex multi-step reasoning, security audits, mathematical proofs, novel algorithm design, strategic planning that requires deep domain expertise.

When in doubt, prefer LOCAL to minimize cloud costs.
You MUST respond ONLY with the JSON object. No markdown, no extra text."""

# ── Rule-based Pre-filter (#5 동적 라우팅) ──────────────────────
FAST_LOCAL_PATTERNS = [
    r"^(hi|hello|안녕|감사|thanks|thank you)",
    r"^/",                            # CLI 명령어
    r"^\d+\s*[\+\-\*\/]",            # 단순 계산
    r"(주석|포맷팅|format|번역|translate|docstring|lint|type hint)",
    r"(디버깅|debug|fix|bug|오류|수정)",
    r"(코드|code|함수|function|class|모듈|module)",
]

FAST_CLOUD_PATTERNS = [
    r"(아키텍처|architecture).*(설계|design)",
    r"(설계|design).*(아키텍처|architecture)",
    r"(시스템|system).*(설계|design|아키텍처|architecture)",
    r"(전체|overall).*(설계|design|아키텍처|architecture)",
    r"(보안|security).*(감사|audit)",
    r"(수학적 증명|mathematical proof)",
]


class Router:
    """
    DeepSeek-R1 기반 작업 라우터.
    사용자 요청을 분석하여 LOCAL(Worker) 또는 CLOUD(Cloud PM) 경로를 결정합니다.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:4000",
        model: str = "local-router",
    ):
        self.client = AsyncOpenAI(base_url=base_url, api_key="not-needed")
        self.model = model

    async def route(self, user_message: str) -> dict:
        """
        사용자 요청을 분석하여 라우팅 결정을 반환합니다.
        규칙 기반 빠른 라우팅을 먼저 시도하고, 애매한 경우만 LLM Router를 호출합니다.

        Args:
            user_message: 사용자 요청 메시지

        Returns:
            dict: {
                "destination": "LOCAL" | "CLOUD",
                "reason": str,
                "thinking": str
            }
        """
        # ── 1차: Rule-based Pre-filter (빠른 라우팅) ─────────
        fast = self._fast_route(user_message)
        if fast is not None:
            return fast

        # ── 2차: LLM Router (판단이 애매한 경우) ───────────
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.3,
                max_tokens=512,
                response_format={"type": "json_object"},
            )

            raw_response = response.choices[0].message.content or ""
            return self._parse_routing_response(raw_response)

        except Exception as e:
            logger.error(f"❌ Router 호출 실패: {e}")
            # Router 실패 시 안전하게 LOCAL로 폴백 (비용 절감)
            return {
                "destination": "LOCAL",
                "reason": f"Router fallback due to error: {e}",
                "thinking": "",
            }

    def _parse_routing_response(self, raw_response: str) -> dict:
        """
        Router의 JSON 응답을 파싱합니다. JSON 실패 시 정규식 폴백.

        Args:
            raw_response: Router의 원시 응답 문자열

        Returns:
            파싱된 라우팅 결정 dict
        """
        # 1차: JSON 파싱 시도
        try:
            data = json.loads(raw_response)
            destination = data.get("route", "LOCAL").upper()
            if destination not in ("LOCAL", "CLOUD"):
                destination = "LOCAL"
            reason = data.get("reason", "No reason provided")
            thinking = data.get("thinking", "")

            logger.info(f"🧭 Route Decision (JSON): {destination} | Reason: {reason}")
            return {
                "destination": destination,
                "reason": reason,
                "thinking": thinking,
            }
        except (json.JSONDecodeError, TypeError):
            logger.warning("⚠️ Router JSON 파싱 실패 → 정규식 폴백")

        # 2차: 정규식 폴백 (하위 호환)
        think_match = re.search(
            r"<think>(.*?)</think>", raw_response, re.DOTALL
        )
        thinking = think_match.group(1).strip() if think_match else ""

        route_match = re.search(
            r"ROUTE:\s*(LOCAL|CLOUD)", raw_response, re.IGNORECASE
        )
        destination = route_match.group(1).upper() if route_match else "LOCAL"

        reason_match = re.search(
            r"REASON:\s*(.+?)(?:\n|$)", raw_response
        )
        reason = reason_match.group(1).strip() if reason_match else "No reason provided"

        logger.info(f"🧭 Route Decision (regex): {destination} | Reason: {reason}")

        return {
            "destination": destination,
            "reason": reason,
            "thinking": thinking,
        }

    def _fast_route(self, user_message: str) -> dict | None:
        """
        규칙 기반 빠른 라우팅. LLM 호출 없이 즉시 판단.
        None이면 LLM Router로 위임.
        """
        for pattern in FAST_LOCAL_PATTERNS:
            if re.search(pattern, user_message, re.IGNORECASE):
                logger.info("🧭 Fast Route: LOCAL (rule match)")
                return {
                    "destination": "LOCAL",
                    "reason": "Rule-based fast routing (simple task)",
                    "thinking": "",
                }
        for pattern in FAST_CLOUD_PATTERNS:
            if re.search(pattern, user_message, re.IGNORECASE):
                logger.info("🧭 Fast Route: CLOUD (rule match)")
                return {
                    "destination": "CLOUD",
                    "reason": "Rule-based fast routing (complex task)",
                    "thinking": "",
                }
        return None
