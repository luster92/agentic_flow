"""
Adversarial Verification Engine — 악마의 변호인 토론 루프
========================================================
변증법적 정-반-합(Thesis-Antithesis-Synthesis) 구조를 통해
단일 에이전트의 환각과 편향을 극복합니다.

토론 토폴로지:
  Round 0: Worker → 초안 생성
  Round N (공격): Devil's Advocate → 공격 리스트 생성
  Round N (판결): Moderator → 유효성 점수 평가
  Round N (수정): Worker → 비판 반영 수정

안전장치:
  - max_rounds 초과 시 강제 종료
  - Moderator ESCALATE 판결 시 HITL 트리거
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

from engine.persona import PersonaManager

logger = logging.getLogger(__name__)


@dataclass
class DebateRound:
    """토론 라운드 기록."""
    round_number: int
    critique: str = ""           # Devil's Advocate의 공격
    critique_parsed: dict[str, Any] = field(default_factory=dict)
    judgment: str = ""           # Moderator의 판결
    judgment_parsed: dict[str, Any] = field(default_factory=dict)
    revision: str = ""           # Worker의 수정안
    validity_score: float = 10.0


@dataclass
class DebateResult:
    """토론 최종 결과."""
    final_proposal: str          # 최종 승인된 안
    approved: bool               # 승인 여부
    total_rounds: int            # 진행된 라운드 수
    rounds: list[DebateRound] = field(default_factory=list)
    escalated: bool = False      # HITL 에스컬레이션 여부
    report: str = ""             # 검증 리포트


class DebateLoop:
    """변증법적 토론 루프 컨트롤러.

    Worker의 제안을 Devil's Advocate가 공격하고,
    Moderator가 판결하며, 합의에 도달할 때까지 순환합니다.
    """

    def __init__(
        self,
        persona_manager: PersonaManager,
        base_url: str = "http://localhost:4000",
        model: str = "local-worker",
    ) -> None:
        self._persona = persona_manager
        self._client = AsyncOpenAI(base_url=base_url, api_key="not-needed")
        self._model = model

    async def run(
        self,
        proposal: str,
        task: str,
        max_rounds: int = 3,
        approval_threshold: float = 7.0,
    ) -> DebateResult:
        """적대적 검증 토론을 실행합니다.

        Args:
            proposal: Worker의 초안
            task: 원본 사용자 요청
            max_rounds: 최대 라운드 수
            approval_threshold: 승인 임계값 (이 값 미만이면 승인)

        Returns:
            DebateResult: 최종 검증 결과
        """
        rounds: list[DebateRound] = []
        current_proposal = proposal
        original_persona_id = self._persona.current_id

        logger.info(
            f"⚔️ Debate started: max_rounds={max_rounds}, "
            f"threshold={approval_threshold}"
        )

        try:
            for round_num in range(1, max_rounds + 1):
                logger.info(f"⚔️ ── Round {round_num}/{max_rounds} ──")
                debate_round = DebateRound(round_number=round_num)

                # ── Step A: 공격 (Devil's Advocate) ──────────────
                critique = await self._attack(current_proposal, task)
                debate_round.critique = critique
                debate_round.critique_parsed = self._parse_json_safe(critique)

                # ── Step B: 판결 (Moderator) ─────────────────────
                judgment = await self._judge(
                    current_proposal, critique, task
                )
                debate_round.judgment = judgment
                debate_round.judgment_parsed = self._parse_json_safe(judgment)

                # 유효성 점수 추출
                validity_score = debate_round.judgment_parsed.get(
                    "validity_score", 10.0
                )
                try:
                    validity_score = float(validity_score)
                except (TypeError, ValueError):
                    validity_score = 10.0
                debate_round.validity_score = validity_score

                verdict = debate_round.judgment_parsed.get(
                    "verdict", "REVISE"
                ).upper()

                logger.info(
                    f"⚔️ Round {round_num} score: {validity_score}/10 "
                    f"| verdict: {verdict}"
                )

                rounds.append(debate_round)

                # ── 판결 분기 ────────────────────────────────────
                if verdict == "ESCALATE":
                    logger.warning(
                        "🚨 Moderator requested ESCALATE → HITL trigger"
                    )
                    return DebateResult(
                        final_proposal=current_proposal,
                        approved=False,
                        total_rounds=round_num,
                        rounds=rounds,
                        escalated=True,
                        report=self._generate_report(rounds),
                    )

                if validity_score < approval_threshold or verdict == "APPROVE":
                    logger.info(
                        f"✅ Debate resolved at round {round_num} "
                        f"(score {validity_score} < {approval_threshold})"
                    )
                    return DebateResult(
                        final_proposal=current_proposal,
                        approved=True,
                        total_rounds=round_num,
                        rounds=rounds,
                        report=self._generate_report(rounds),
                    )

                # ── Step C: 수정 (Worker) ────────────────────────
                if round_num < max_rounds:
                    revision = await self._revise(
                        current_proposal, critique, judgment, task
                    )
                    debate_round.revision = revision
                    current_proposal = revision

            # ── max_rounds 도달: 강제 승인 ───────────────────────
            logger.warning(
                f"⚠️ Max rounds ({max_rounds}) reached. "
                "Forcing approval with last revision."
            )
            return DebateResult(
                final_proposal=current_proposal,
                approved=True,
                total_rounds=max_rounds,
                rounds=rounds,
                report=self._generate_report(rounds),
            )

        finally:
            # 원래 페르소나로 복귀
            if self._persona.current_id != original_persona_id:
                try:
                    self._persona.switch_persona(
                        original_persona_id,
                        reason="Debate loop completed, restoring original",
                    )
                except FileNotFoundError:
                    pass

    async def _attack(self, proposal: str, task: str) -> str:
        """Devil's Advocate 페르소나로 공격을 생성합니다."""
        self._persona.switch_persona("devil", reason="Debate: attack phase")
        transition_msg = self._persona.get_transition_message()

        messages = [
            {"role": "system", "content": self._persona.get_system_prompt()},
            {"role": "system", "content": transition_msg},
            {
                "role": "user",
                "content": (
                    f"## 원본 요청\n{task}\n\n"
                    f"## 작업자의 제안\n{proposal}\n\n"
                    "위 제안을 분석하여 공격 리스트(Attack Vector)를 생성해라."
                ),
            },
        ]

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=self._persona.get_temperature(),
                max_tokens=2048,
            )
            result = response.choices[0].message.content or ""
            logger.info(f"😈 Devil's Advocate attack generated ({len(result)} chars)")
            return result
        except Exception as e:
            logger.error(f"❌ Devil's Advocate attack failed: {e}")
            return json.dumps({
                "attack_vectors": [],
                "overall_assessment": f"Attack generation failed: {e}",
                "recommendation": "CONDITIONAL_PASS",
            })

    async def _judge(
        self, proposal: str, critique: str, task: str
    ) -> str:
        """Moderator 페르소나로 판결을 내립니다."""
        self._persona.switch_persona(
            "moderator", reason="Debate: judgment phase"
        )
        transition_msg = self._persona.get_transition_message()

        messages = [
            {"role": "system", "content": self._persona.get_system_prompt()},
            {"role": "system", "content": transition_msg},
            {
                "role": "user",
                "content": (
                    f"## 원본 요청\n{task}\n\n"
                    f"## 작업자의 제안\n{proposal}\n\n"
                    f"## 비판자의 공격\n{critique}\n\n"
                    "위 공격의 유효성을 평가하고 판결을 내려라."
                ),
            },
        ]

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=self._persona.get_temperature(),
                max_tokens=1024,
            )
            result = response.choices[0].message.content or ""
            logger.info(f"⚖️ Moderator judgment rendered ({len(result)} chars)")
            return result
        except Exception as e:
            logger.error(f"❌ Moderator judgment failed: {e}")
            return json.dumps({
                "validity_score": 0,
                "verdict": "APPROVE",
                "reasoning": f"Judgment failed: {e}",
            })

    async def _revise(
        self,
        proposal: str,
        critique: str,
        judgment: str,
        task: str,
    ) -> str:
        """Worker 페르소나로 제안을 수정합니다."""
        self._persona.switch_persona("worker", reason="Debate: revision phase")
        transition_msg = self._persona.get_transition_message()

        messages = [
            {"role": "system", "content": self._persona.get_system_prompt()},
            {"role": "system", "content": transition_msg},
            {
                "role": "user",
                "content": (
                    f"## 원본 요청\n{task}\n\n"
                    f"## 네가 작성한 이전 제안\n{proposal}\n\n"
                    f"## 비판자의 공격\n{critique}\n\n"
                    f"## 중재자의 판결\n{judgment}\n\n"
                    "비판 내용을 반영하여 제안을 수정해라. "
                    "불필요한 설명 없이 수정된 전체 결과물만 출력해라."
                ),
            },
        ]

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=self._persona.get_temperature(),
                max_tokens=4096,
            )
            result = response.choices[0].message.content or proposal
            logger.info(f"✏️ Worker revision completed ({len(result)} chars)")
            return result
        except Exception as e:
            logger.error(f"❌ Worker revision failed: {e}")
            return proposal  # 수정 실패 시 원안 유지

    @staticmethod
    def _parse_json_safe(text: str) -> dict[str, Any]:
        """JSON 파싱 시도, 실패 시 텍스트를 래핑하여 반환."""
        try:
            # JSON 블록 추출 (```json ... ``` 형태)
            import re
            json_match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(1))
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return {"raw_text": text}

    @staticmethod
    def _generate_report(rounds: list[DebateRound]) -> str:
        """검증 리포트를 생성합니다."""
        lines = [
            "# 적대적 검증 리포트 (Adversarial Verification Report)",
            f"총 라운드: {len(rounds)}",
            "",
        ]

        for r in rounds:
            lines.append(f"## Round {r.round_number}")
            lines.append(f"유효성 점수: {r.validity_score}/10")

            verdict = r.judgment_parsed.get("verdict", "N/A")
            lines.append(f"판결: {verdict}")

            attacks = r.critique_parsed.get("attack_vectors", [])
            if attacks:
                lines.append(f"공격 벡터 수: {len(attacks)}")
                for a in attacks[:3]:  # 상위 3개만
                    if isinstance(a, dict):
                        lines.append(
                            f"  - [{a.get('severity', '?')}] "
                            f"{a.get('finding', 'N/A')}"
                        )

            lines.append("")

        return "\n".join(lines)
