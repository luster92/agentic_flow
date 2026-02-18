"""
Helper Agent - Phi-4 Mini (3.8B)
================================
[Strict Subordinate] 역할:
- 단순 포맷팅, 주석 추가, 번역 등 반복 작업만 수행
- 독자적 사고 금지, 에스컬레이션 불가
- Input → Transformation → Output만 수행

Circuit Breaker 패턴:
- 최대 3회 재시도
- 결과값 검증 (빈 문자열, JSON 파싱 등)
- 실패 시 None 반환 → Worker가 직접 처리
"""

import logging
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# ── Helper 시스템 프롬프트 ────────────────────────────────────
HELPER_SYSTEM_PROMPT = """You are a strict subordinate assistant.

RULES:
1. You ONLY perform the exact transformation requested.
2. You do NOT think independently or add your own ideas.
3. You do NOT escalate or request help from other models.
4. You MUST return ONLY the transformed result, nothing else.
5. You do NOT explain your reasoning or add commentary.

Your job: Input → Transformation → Output. Nothing more."""


async def _call_phi4_mini(
    task: str,
    base_url: str = "http://localhost:4000",
    model: str = "local-helper",
) -> str:
    """
    Phi-4 Mini를 호출하여 단순 변환 작업을 수행합니다.

    Args:
        task: 수행할 변환 작업 지시 (예: "다음 코드에 한국어 주석을 추가해줘: ...")
        base_url: LiteLLM Proxy URL
        model: 호출할 모델명

    Returns:
        변환된 결과 문자열

    Raises:
        Exception: API 호출 실패 또는 빈 응답 시
    """
    client = AsyncOpenAI(base_url=base_url, api_key="not-needed")

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": HELPER_SYSTEM_PROMPT},
            {"role": "user", "content": task},
        ],
        temperature=0.1,   # 창의성 최소화, 정확한 변환에 집중
        max_tokens=2048,
    )

    result = response.choices[0].message.content
    if not result or not result.strip():
        raise ValueError("Helper returned empty response")

    return result.strip()


def validate(result: str) -> bool:
    """
    Helper의 출력 결과를 검증합니다.

    검증 기준:
    - 빈 문자열이 아닐 것
    - 에스컬레이션 키워드가 포함되지 않을 것
    - 최소 길이(5자) 이상일 것

    Args:
        result: 검증할 결과 문자열

    Returns:
        검증 통과 여부
    """
    if not result or not result.strip():
        return False

    # Helper가 에스컬레이션을 시도하면 거부
    forbidden_keywords = ["[ESCALATE]", "I cannot", "I need help", "beyond my capability"]
    for keyword in forbidden_keywords:
        if keyword.lower() in result.lower():
            logger.warning(f"Helper attempted forbidden action: contains '{keyword}'")
            return False

    # 너무 짧은 응답은 유효하지 않음
    if len(result.strip()) < 5:
        return False

    return True


async def ask_helper_safe(
    task: str,
    max_retries: int = 3,
    base_url: str = "http://localhost:4000",
) -> str | None:
    """
    Circuit Breaker가 적용된 안전한 Helper 호출 함수.

    최대 max_retries 횟수만큼 재시도하며, 모든 시도가 실패하면
    None을 반환하여 Worker가 직접 처리하도록 합니다.

    ⚠️ Helper 실패로 인한 상위(Cloud) 에스컬레이션은 절대 발생하지 않습니다.

    Args:
        task: Helper에게 위임할 작업 설명
        max_retries: 최대 재시도 횟수 (기본값: 3)
        base_url: LiteLLM Proxy URL

    Returns:
        성공 시: 변환된 결과 문자열
        실패 시: None (→ Worker가 직접 처리)
    """
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"🔧 Helper 호출 시도 {attempt}/{max_retries}: {task[:80]}...")
            result = await _call_phi4_mini(task, base_url=base_url)

            if validate(result):
                logger.info(f"✅ Helper 성공 (시도 {attempt}/{max_retries})")
                return result
            else:
                logger.warning(
                    f"⚠️ Helper 검증 실패 (시도 {attempt}/{max_retries}): "
                    f"결과값이 유효하지 않음"
                )
        except Exception as e:
            logger.warning(
                f"❌ Helper 호출 실패 (시도 {attempt}/{max_retries}): {e}"
            )

    # ── 모든 시도 실패: Worker에게 Fallback ──────────────────
    logger.warning(
        f"⚠️ Helper {max_retries}회 실패. Fallback to Worker. "
        f"Task: {task[:100]}..."
    )
    return None
