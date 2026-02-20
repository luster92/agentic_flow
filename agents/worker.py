"""
Worker Agent - Qwen 2.5 Coder 32B (Int4)
=========================================
핵심 코드 구현 및 모듈 개발 역할:
- 복잡한 논리와 코딩을 직접 수행
- 단순 반복 작업은 Helper에게 위임 (call_helper)
- [NEW] 도구 사용 (Tools): FileRead, ListDir 등 외부 상호작용
- [NEW] 장기 기억 (Memory): 과거의 경험(VectorDB)을 바탕으로 문제 해결
- [NEW] MCP 확장 (Model Context Protocol): 외부 도구 동적 로드
- Helper 실패 시 직접 처리 (Do It Yourself Fallback)
- 도저히 해결 불가능한 난제에만 [ESCALATE] 출력

검증 파이프라인 (AI Dunning-Kruger 방어):
1. 결정론적 검증 (ast.parse) — 코드 문법 기계적 검증
2. Critic Agent — 까칠한 코드 리뷰어가 [PASS]/[REJECT] 판정
   → 멀티턴 Critic: REJECT 시 suggestions 기반 재생성 (최대 2회)
3. Self-Reflection — 시스템 프롬프트 내 자기 검증 체크리스트
"""

import asyncio
import json
import logging
from openai import AsyncOpenAI

from agents.helper import ask_helper_safe
from agents.critic import critique
from utils.validator import validate_response, format_error_feedback
from utils.introspector import generate_context as generate_knowledge_context
from utils.knowledge_updater import record_learning
from utils.tools import AVAILABLE_TOOLS
from utils.memory import global_memory
from utils.mcp_client import global_mcp_manager
from core.observability import TokenUsageTracker

logger = logging.getLogger(__name__)

# ── Worker 시스템 프롬프트 (Self-Reflection 포함) ──────────────
WORKER_SYSTEM_PROMPT = """너는 노련한 수석 개발자(Worker)다.

1. 복잡한 논리와 코딩은 네가 직접 수행해라.
2. 단순 반복 작업(주석, 포맷팅)은 'helper_tool'을 사용해라.
3. 정보가 부족하면 제공된 도구(Tools)를 사용하여 파일 시스템 등을 탐색해라.
4. 만약 도저히 해결 불가능한 난제에 봉착하면 '[ESCALATE]'라고 출력해라.
5. 단, Helper의 실패 때문에 에스컬레이션하지 마라. Helper가 못하면 네가 직접 처리해라.

## Self-Reflection (자기 검증 체크리스트)
답변을 최종 출력하기 전에 다음을 스스로 점검해라:
1. 사용자의 요구사항을 100% 충족했는가?
2. 코드가 실제로 실행 가능한 상태인가? (import 누락, 들여쓰기 오류 없는가?)
3. 엣지 케이스(Edge Case)는 고려했는가?
4. 변수명과 함수명이 명확한가?

⚠️ 만약 1%라도 확신이 없다면, 억지로 답을 만들지 말고 '[ESCALATE]'를 출력해라.
응답할 때는 항상 명확하고 실용적인 코드를 제공해라."""

# ── Helper 위임 가능한 작업 키워드 ─────────────────────────────
HELPER_DELEGATABLE_KEYWORDS = [
    "주석 추가", "add comments", "comment",
    "포맷팅", "formatting", "format",
    "번역", "translate", "translation",
    "docstring", "독스트링",
    "타입 힌트", "type hint",
    "린트", "lint", "linting",
]

# ── 검증 설정 ─────────────────────────────────────────────────
MAX_VALIDATION_RETRIES = 2  # 문법 오류 시 최대 재시도 횟수
MAX_CRITIC_ROUNDS = 2       # Critic 멀티턴 최대 라운드
MAX_TOOL_STEPS = 5          # 도구 연속 호출 최대 횟수 (Re-act Loop Limit)


class Worker:
    """
    Qwen 2.5 Coder 32B 기반 핵심 워커.
    복잡한 코드 구현을 수행하며, 단순 작업은 Helper에 위임합니다.
    3단계 검증 파이프라인(결정론적 검증 + Critic + Self-Reflection)을 통해
    'AI Dunning-Kruger Effect'를 방지합니다.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:4000",
        model: str = "local-worker",
    ):
        self.client = AsyncOpenAI(base_url=base_url, api_key="not-needed")
        # Knowledge Context: Golden Snippet + 설치된 패키지 버전
        self._knowledge_context = generate_knowledge_context()
        self.model = model
        self.base_url = base_url
        
        # 기본 도구 초기화
        self.tools_map = {tool.name: tool for tool in AVAILABLE_TOOLS}
        self.tool_schemas = [tool.to_schema() for tool in AVAILABLE_TOOLS]
        
        self.memory = global_memory  # Vector Memory 연결

    async def initialize_mcp_tools(self, mcp_config: dict):
        """
        MCP 서버에 연결하고 도구를 가져와 시스템에 등록합니다.
        """
        if not mcp_config:
            return

        logger.info("🔌 initializing MCP Tools...")
        
        # 1. Connect to Servers
        for name, config in mcp_config.items():
            if not config: continue
            
            command = config.get("command")
            args = config.get("args", [])
            env = config.get("env", {})
            
            if command:
                await global_mcp_manager.connect_server(name, command, args, env)

        # 2. Fetch Tools
        mcp_tools = await global_mcp_manager.get_tools()
        
        # 3. Register Tools
        count = 0
        for tool in mcp_tools:
            self.tools_map[tool.name] = tool
            self.tool_schemas.append(tool.to_schema())
            count += 1
            
        logger.info(f"✅ MCP Tools initialized: {count} tools added.")


    async def execute(
        self,
        task: str,
        context: list[dict] | None = None,
    ) -> dict:
        """
        작업을 실행합니다. (RAG + MCP 적용)
        """
        # ── 0단계: Recall (기억 인출) ────────────────────────
        relevant_memories = self.memory.search(task, top_k=3)
        retrieved_context = ""
        if relevant_memories:
            logger.info(f"🧠 [Recall] 관련 기억 {len(relevant_memories)}개 인출 성공")
            retrieved_context = "\n".join([
                f"- [Past Experience] {m['text']} (유사도: {1 - m['distance']:.2f})"
                for m in relevant_memories
            ])
        
        # ── 1단계: 단순 작업인지 판별하여 Helper 위임 시도 ────
        helper_result = None
        helper_used = False
        helper_fallback = False

        if self._is_helper_delegatable(task):
            logger.info("📋 단순 반복 작업 감지 → Helper에 위임 시도")
            helper_result = await self._call_helper(task)

            if helper_result is not None:
                helper_used = True
                logger.info("✅ Helper가 작업을 성공적으로 처리함")
            else:
                helper_fallback = True
                logger.info(
                    "⚠️ Helper 실패 → Worker가 직접 처리 (Do It Yourself)"
                )

        # ── 2단계: Worker 본인이 처리 (Tool Use + RAG Context) 
        worker_response = await self._generate_response(
            task=task,
            context=context,
            helper_result=helper_result,
            helper_fallback=helper_fallback,
            retrieved_context=retrieved_context,
        )

        # [ESCALATE] 체크 (검증 전에 먼저 확인)
        if worker_response is None or "[ESCALATE]" in (worker_response or ""):
            if "[ESCALATE]" in (worker_response or ""):
                logger.warning("🚨 Worker가 에스컬레이션을 요청함: [ESCALATE]")
            return {
                "response": worker_response or "[ERROR] Worker failed",
                "escalated": True,
                "helper_used": helper_used,
                "helper_fallback": helper_fallback,
                "validation_passed": False,
                "critic_passed": None,
            }

        # ── 3단계: Layer 1 — 결정론적 검증 ───────────────────
        validation = validate_response(worker_response)
        validation_passed = validation.valid

        if not validation_passed:
            logger.warning("❌ [Layer 1] 결정론적 검증 실패 → 재시도 시작")
            worker_response, validation_passed = await self._retry_with_feedback(
                task=task,
                context=context,
                validation=validation,
                helper_result=helper_result,
                helper_fallback=helper_fallback,
            )

            # 재시도 후에도 실패 → 강제 에스컬레이션
            if not validation_passed:
                logger.error("🚨 [Layer 1] 재시도 실패 → Cloud PM 강제 에스컬레이션")
                return {
                    "response": worker_response,
                    "escalated": True,
                    "helper_used": helper_used,
                    "helper_fallback": helper_fallback,
                    "validation_passed": False,
                    "critic_passed": None,
                }

        # ── 4단계: Layer 2 — Critic Agent (멀티턴) ─────────────
        critic_passed = None
        if validation.has_code:
            logger.info("🔍 [Layer 2] Critic Agent 검증 시작 (멀티턴)...")
            worker_response, critic_passed = await self._critic_loop(
                response=worker_response,
                task=task,
                context=context,
                helper_result=helper_result,
                helper_fallback=helper_fallback,
            )

            if not critic_passed:
                logger.warning(
                    "❌ [Layer 2] Critic 멀티턴 루프 실패 → Cloud PM 에스컬레이션"
                )
                return {
                    "response": worker_response,
                    "escalated": True,
                    "helper_used": helper_used,
                    "helper_fallback": helper_fallback,
                    "validation_passed": validation_passed,
                    "critic_passed": False,
                }
            else:
                logger.info("✅ [Layer 2] Critic 검증 통과")
                
                # [NEW] 성공적인 결과 기억 (Memorize)
                self._memorize_success(task, worker_response)

        # ── 전체 통과 ────────────────────────────────────────
        return {
            "response": worker_response,
            "escalated": False,
            "helper_used": helper_used,
            "helper_fallback": helper_fallback,
            "validation_passed": validation_passed,
            "critic_passed": critic_passed,
        }

    def _memorize_success(self, task: str, response: str):
        """성공한 작업 내용을 벡터 메모리에 저장합니다."""
        try:
            snippet = f"Task: {task}\n\nSolution:\n{response[:1000]}"
            self.memory.add(snippet, metadata={"type": "solution", "task": task})
            logger.info("💾 [Memorize] 성공적인 해결책을 장기 기억에 저장했습니다.")
        except Exception as e:
            logger.warning(f"⚠️ 기억 저장 실패: {e}")

    async def _critic_loop(
        self,
        response: str,
        task: str,
        context: list[dict] | None,
        helper_result: str | None,
        helper_fallback: bool,
        max_rounds: int = MAX_CRITIC_ROUNDS,
    ) -> tuple[str, bool]:
        """Critic과의 대화형 비평 루프."""
        current_response = response

        for round_num in range(1, max_rounds + 1):
            critic_result = await critique(
                response=current_response,
                task=task,
                base_url=self.base_url,
            )

            if critic_result["passed"]:
                return current_response, True

            suggestions = critic_result.get("suggestions", [critic_result["reason"]])
            reason = critic_result["reason"]
            logger.warning(
                f"❌ [Critic Round {round_num}/{max_rounds}] REJECT: {reason[:200]}"
            )

            if round_num < max_rounds:
                feedback = (
                    f"Critic 피드백 (Round {round_num}):\n"
                    f"판정: REJECT\n"
                    f"사유: {reason}\n"
                    f"수정 제안:\n"
                    + "\n".join(f"- {s}" for s in suggestions)
                    + "\n\n위 피드백을 반영하여 응답을 수정해주세요."
                )

                new_response = await self._generate_response(
                    task=task,
                    context=context,
                    helper_result=helper_result,
                    helper_fallback=helper_fallback,
                    error_feedback=feedback,
                )

                if new_response is None or "[ESCALATE]" in (new_response or ""):
                    return current_response, False

                current_response = new_response
                logger.info(
                    f"🔄 [Critic Round {round_num}] Worker 응답 재생성 완료 → 재평가"
                )

        return current_response, False

    async def _generate_response(
        self,
        task: str,
        context: list[dict] | None,
        helper_result: str | None,
        helper_fallback: bool,
        error_feedback: str | None = None,
        retrieved_context: str = "",
    ) -> str | None:
        """
        Worker LLM을 호출하여 응답을 생성합니다. (Tool Use Loop 포함)
        """
        messages = self._build_messages(
            task=task,
            context=context,
            helper_result=helper_result,
            helper_fallback=helper_fallback,
            retrieved_context=retrieved_context,
        )

        if error_feedback:
            messages.append({
                "role": "user",
                "content": error_feedback,
            })

        # ── Tool Use Loop (Re-act) ───────────────────────────
        tracker = TokenUsageTracker(agent_name=self.model)
        for step in range(MAX_TOOL_STEPS):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.4,
                    max_tokens=4096,
                    tools=self.tool_schemas,  # 동적 도구 포함
                    tool_choice="auto",
                )
                
                # 수동 토큰 트래킹 파싱
                if hasattr(response, "usage") and response.usage:
                    prompt_info = getattr(response.usage, "prompt_tokens", 0)
                    completion_info = getattr(response.usage, "completion_tokens", 0)
                    mock_res = type('Result', (), {'llm_output': {'token_usage': {'prompt_tokens': prompt_info, 'completion_tokens': completion_info}, 'model_name': self.model}})()
                    tracker.on_llm_end(mock_res)
                
                msg = response.choices[0].message
                content = msg.content or ""
                tool_calls = msg.tool_calls

                if not tool_calls:
                    return content

                messages.append(msg)
                
                for tool_call in tool_calls:
                    func_name = tool_call.function.name
                    func_args = json.loads(tool_call.function.arguments)
                    
                    logger.info(f"🛠️ Tool Call: {func_name}({func_args})")
                    
                    # 도구 조회 (Static + MCP)
                    tool = self.tools_map.get(func_name)
                    
                    if tool:
                        result = await tool.validate_and_execute(**func_args)
                    else:
                        result = f"❌ Error: Tool '{func_name}' not found."
                    
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": str(result),
                    })
                    logger.info(f"  └─ Result: {str(result)[:100]}...")

            except Exception as e:
                logger.error(f"❌ Worker 실행 실패 (Step {step}): {e}")
                return None
        
        logger.warning(f"⚠️ Tool Loop Limit Reached ({MAX_TOOL_STEPS})")
        return None

    async def _retry_with_feedback(
        self,
        task: str,
        context: list[dict] | None,
        validation,
        helper_result: str | None,
        helper_fallback: bool,
    ) -> tuple[str, bool]:
        """결정론적 검증 실패 시 재시도."""
        last_response = ""
        first_errors = []

        for attempt in range(1, MAX_VALIDATION_RETRIES + 1):
            logger.info(f"🔄 [Layer 1] 재시도 {attempt}/{MAX_VALIDATION_RETRIES}")

            if attempt == 1:
                first_errors = list(validation.errors)

            error_feedback = format_error_feedback(validation)
            new_response = await self._generate_response(
                task=task,
                context=context,
                helper_result=helper_result,
                helper_fallback=helper_fallback,
                error_feedback=error_feedback,
            )

            if new_response is None:
                last_response = "[ERROR] Worker retry failed"
                break

            last_response = new_response
            new_validation = validate_response(new_response)

            if new_validation.valid:
                logger.info(f"✅ [Layer 1] 재시도 {attempt}회에서 검증 통과!")
                
                if first_errors and new_validation.code_blocks:
                    # Record Learning
                    record_learning(
                        error_message="; ".join(first_errors),
                        original_code="(검증 실패한 코드)",
                        fixed_code=new_validation.code_blocks[0][:300],
                    )
                    self._memorize_success(task, new_response)

                return new_response, True

            validation = new_validation

        return last_response, False

    def _is_helper_delegatable(self, task: str) -> bool:
        task_lower = task.lower()
        return any(keyword in task_lower for keyword in HELPER_DELEGATABLE_KEYWORDS)

    async def _call_helper(self, task: str) -> str | None:
        return await ask_helper_safe(task, max_retries=3, base_url=self.base_url)

    def _build_messages(
        self,
        task: str,
        context: list[dict] | None,
        helper_result: str | None,
        helper_fallback: bool,
        retrieved_context: str = "",
    ) -> list[dict]:
        """Worker에게 전달할 메시지 목록을 구성합니다."""
        system_prompt = WORKER_SYSTEM_PROMPT
        
        # [NEW] Long-term Memory Injection
        if retrieved_context:
            system_prompt += f"\n\n## [Long-term Memory] 유사한 과거 경험\n{retrieved_context}"
            
        if self._knowledge_context:
            system_prompt += "\n\n" + self._knowledge_context

        messages = [{"role": "system", "content": system_prompt}]

        if context:
            messages.extend(context)

        if helper_result is not None:
            user_content = (
                f"작업 요청: {task}\n\n"
                f"보조 도구(Helper)가 다음 결과를 생성했습니다:\n"
                f"--- Helper 결과 ---\n{helper_result}\n--- 끝 ---"
            )
        elif helper_fallback:
            user_content = (
                f"작업 요청: {task}\n\n"
                f"[참고] Helper가 실패했습니다. 직접 처리하십시오."
            )
        else:
            user_content = task

        messages.append({"role": "user", "content": user_content})
        return messages
