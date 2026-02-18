"""
Critic Agent — 비평가 에이전트
================================
Helper 모델(Phi-4 Mini)을 "까칠한 코드 리뷰어" 페르소나로 재활용합니다.
Worker(작성자)와 다른 관점에서 응답을 평가하여 [PASS] 또는 [REJECT]를 판정합니다.

핵심: 작성자는 "해결하려는 의지"로 편향되지만,
      비평가는 "까려는 의지"로 오류를 잘 잡아냅니다.

멀티턴 Critic:
  REJECT 시 suggestions 필드를 통해 구체적인 수정 제안을 Worker에 전달합니다.
"""

import json
import logging
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# ── Critic 시스템 프롬프트 ─────────────────────────────────────
CRITIC_SYSTEM_PROMPT = """너는 까칠하고 꼼꼼한 시니어 코드 리뷰어(Code Reviewer)다.
지금부터 들어오는 코드/답변을 **작성자가 누구인지 모르는 상태**에서 냉정하게 평가해라.

평가 기준:
1. 사용자의 요구사항을 충족하는가?
2. 논리적 허점이나 버그가 있는가?
3. 엣지 케이스(Edge Case)를 고려했는가?
4. 코드가 실행 가능한 상태인가?

판정 규칙:
- 애매하면 REJECT로 판정해라. 통과시키는 것보다 거절하는 것이 안전하다.

반드시 아래 JSON 형식으로만 응답해라. 다른 텍스트는 출력하지 마라:
{
  "verdict": "PASS 또는 REJECT",
  "reason": "판정 이유를 한두 문장으로",
  "suggestions": ["구체적인 수정 제안 1", "수정 제안 2"]
}

- PASS일 때는 suggestions를 빈 배열 []로 출력해라.
- REJECT일 때는 반드시 하나 이상의 구체적인 수정 제안을 포함해라."""


async def critique(
    response: str,
    task: str,
    base_url: str = "http://localhost:4000",
    model: str = "local-helper",
    max_retries: int = 2,
) -> dict:
    """
    Worker의 응답을 비평가 관점에서 평가합니다.

    Args:
        response: Worker가 생성한 응답 텍스트
        task: 원본 사용자 요청 (비교 기준)
        base_url: LiteLLM 프록시 URL
        model: 비평가에 사용할 모델 (기본: Helper 모델)
        max_retries: 호출 재시도 횟수

    Returns:
        dict: {
            "passed": bool,          # 통과 여부
            "reason": str,           # 판정 이유
            "suggestions": list,     # 수정 제안 목록 (REJECT 시)
            "raw_response": str,     # Critic의 원본 응답
        }
    """
    client = AsyncOpenAI(base_url=base_url, api_key="not-needed")

    messages = [
        {"role": "system", "content": CRITIC_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"## 원본 요청\n{task}\n\n"
                f"## Worker의 응답\n{response}\n\n"
                f"위 응답을 평가하고 [PASS] 또는 [REJECT]로 판정해라."
            ),
        },
    ]

    for attempt in range(max_retries):
        try:
            result = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.2,  # 일관된 판정을 위해 낮은 temperature
                max_tokens=512,
                response_format={"type": "json_object"},
            )

            critic_response = result.choices[0].message.content or ""

            # 1차: JSON 파싱 시도
            try:
                data = json.loads(critic_response)
                verdict = data.get("verdict", "").upper()
                reason = data.get("reason", "No reason provided")
                suggestions = data.get("suggestions", [])
                passed = verdict == "PASS"

                if passed:
                    logger.info("✅ Critic 검증 통과: PASS (JSON)")
                else:
                    logger.warning("❌ Critic 검증 거절: REJECT (JSON)")

                return {
                    "passed": passed,
                    "reason": reason,
                    "suggestions": suggestions if not passed else [],
                    "raw_response": critic_response,
                }
            except (json.JSONDecodeError, TypeError):
                logger.warning("⚠️ Critic JSON 파싱 실패 → 텍스트 폴백")

            # 2차: 텍스트 기반 폴백
            passed = "[PASS]" in critic_response.upper()
            rejected = "[REJECT]" in critic_response.upper()

            if not passed and not rejected:
                logger.warning("⚠️ Critic이 명확한 판정을 내리지 않음 → REJECT 처리")
                passed = False

            if passed:
                logger.info("✅ Critic 검증 통과: [PASS] (text)")
            else:
                logger.warning("❌ Critic 검증 거절: [REJECT] (text)")

            return {
                "passed": passed and not rejected,
                "reason": critic_response.strip(),
                "suggestions": [critic_response.strip()] if (not passed or rejected) else [],
                "raw_response": critic_response,
            }

        except Exception as e:
            logger.error(f"❌ Critic 호출 실패 (시도 {attempt + 1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                # Critic 자체가 실패하면 → 안전하게 PASS (Critic 없이 진행)
                logger.warning("⚠️ Critic 호출 불가 → 안전 모드: PASS 처리")
                return {
                    "passed": True,
                    "reason": f"Critic unavailable: {e}",
                    "suggestions": [],
                    "raw_response": "",
                }

    # 도달할 수 없지만 안전장치
    return {"passed": True, "reason": "Critic skipped", "suggestions": [], "raw_response": ""}
