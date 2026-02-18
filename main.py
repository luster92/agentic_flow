"""
Mac Mini M4 Hybrid AI Orchestration System — Enterprise Edition
================================================================
메인 오케스트레이터: 사용자 입력을 받아 5계층 에이전트 시스템을 조율합니다.

Enterprise 기능:
- 영속적 상태 관리 + 체크포인팅 (SQLite)
- 동적 페르소나 토글 (YAML 기반)
- 적대적 검증 (Devil's Advocate 토론 루프)
- Human-in-the-loop (인터럽트 기반)

멀티 프로젝트(Contextualized Framework) 지원:
- /new <project>: 새 프로젝트 생성
- /load <project>: 프로젝트 전환
- /list: 프로젝트 목록
- /current: 현재 상태

Cloud PM 전환:
- /model <name>: 클라우드 모델 변경 (gemini, claude, gpt4)

Enterprise 명령어:
- /checkpoint [label]: 수동 마일스톤 체크포인트
- /rollback [step]: 특정 단계로 롤백
- /persona [id]: 페르소나 전환
- /debate: 마지막 응답에 적대적 검증 실행
- /approve: HITL 승인
- /reject: HITL 거절

워크플로우:
1. 사용자 입력 → Router(DeepSeek-R1)가 분석
2. LOCAL 라우팅 → Worker(Qwen 32B)가 실행
3. CLOUD 라우팅 또는 [ESCALATE] → Cloud PM(Gemini/Claude/GPT)이 처리
4. 적대적 검증 (선택적) → Devil's Advocate 토론 루프
5. 결과 반환 및 대화 기록 + 체크포인트 저장

실행: python main.py
"""

import os
import sys
import asyncio
import logging
import yaml
from dotenv import load_dotenv
from openai import AsyncOpenAI

from agents.router import Router
from agents.worker import Worker
from core.state import AgentState, SessionStatus, CheckpointType
from core.checkpoint import CheckpointManager
from core.config_loader import ConfigLoader
from engine.persona import PersonaManager
from engine.adversarial import DebateLoop
from engine.hitl import HITLManager, WaitApproval
from utils.history_manager import HistoryManager, DEFAULT_HISTORY_DIR
from utils.mcp_client import global_mcp_manager
from utils.semantic_cache import SemanticCache

# ── 환경 설정 ─────────────────────────────────────────────────
load_dotenv()

LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "http://localhost:4000")
CONTEXT_WINDOW = int(os.getenv("CONTEXT_WINDOW_SIZE", "20"))
HISTORY_DIR = os.getenv("HISTORY_DIR", "history")
CONFIG_FILE = "config.yaml"

# 기본 클라우드 모델
CLOUD_MODEL_NAME = "cloud-pm-gemini"

# 모델 매핑 (단축어 -> 실제 모델명)
MODEL_MAP = {
    "gemini": "cloud-pm-gemini",
    "claude": "cloud-pm-claude",
    "gpt4": "cloud-pm-gpt4",
}

# ── 로깅 설정 ─────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-7s │ %(name)-20s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("orchestrator")


def load_config() -> dict:
    """config.yaml 파일을 로드합니다."""
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"❌ Failed to load config.yaml: {e}")
        return {}


async def call_cloud_pm(
    task: str,
    context: list[dict] | None = None,
    base_url: str = LITELLM_BASE_URL,
    stream: bool = True,
    persona_manager: PersonaManager | None = None,
) -> str:
    """Cloud PM 호출 (동적 모델 선택, 스트리밍 지원, 페르소나 적용)"""
    client = AsyncOpenAI(base_url=base_url, api_key="not-needed")
    model_name = CLOUD_MODEL_NAME

    # 페르소나 기반 시스템 프롬프트
    if persona_manager and persona_manager.current:
        system_content = persona_manager.get_system_prompt()
    else:
        system_content = (
            "You are a senior project manager and architect with deep expertise "
            "in software design, complex reasoning, and strategic planning. "
            "Provide thorough, well-structured solutions."
        )

    messages = [{"role": "system", "content": system_content}]

    if context:
        messages.extend(context)

    messages.append({"role": "user", "content": task})

    try:
        if stream:
            response_stream = await client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=persona_manager.get_temperature() if persona_manager else 0.5,
                max_tokens=4096,
                stream=True,
            )
            chunks = []
            print("\n🤖 Assistant > ", end="", flush=True)
            async for chunk in response_stream:
                content = chunk.choices[0].delta.content or ""
                print(content, end="", flush=True)
                chunks.append(content)
            print()
            return "".join(chunks) or "[Cloud PM returned empty response]"
        else:
            response = await client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=persona_manager.get_temperature() if persona_manager else 0.5,
                max_tokens=4096,
            )
            return response.choices[0].message.content or "[Cloud PM returned empty response]"
    except Exception as e:
        logger.error(f"❌ Cloud PM 호출 실패 ({model_name}): {e}")
        return f"[ERROR] Cloud PM ({model_name}) failed: {e}"


async def process_request(
    user_input: str,
    router: Router,
    worker: Worker,
    history: HistoryManager,
    state: AgentState,
    cache: SemanticCache | None = None,
    checkpoint_mgr: CheckpointManager | None = None,
    persona_mgr: PersonaManager | None = None,
    debate_loop: DebateLoop | None = None,
    hitl_mgr: HITLManager | None = None,
    enterprise_config: dict | None = None,
) -> str:
    """사용자 요청 처리 파이프라인 (Enterprise Edition)"""
    ecfg = enterprise_config or {}
    history.add_message("user", user_input)
    state.increment_turn()
    state.increment_step()

    # ── 0단계: Semantic Cache Lookup (Short-Circuit) ──────
    if cache:
        cached = cache.get(user_input)
        if cached is not None:
            history.add_message(
                "assistant", cached,
                metadata={"handler": "semantic-cache", "cache_hit": True},
            )
            return cached

    # ── 1단계: Sticky Routing 또는 Router 호출 ───────────────
    logger.info("=" * 60)

    if state.current_agent is not None:
        destination = state.current_agent
        reason = "Sticky Routing (이전 턴과 동일 에이전트)"
        logger.info(f"🧭 [Sticky Route] Router 스킵 → {destination} | {reason}")
    else:
        logger.info("🧭 [Router] 작업 분석 중...")
        routing = await router.route(user_input)
        destination = routing["destination"]
        reason = routing["reason"]
        state.current_agent = destination
        logger.info(f"🧭 [Router] 결정: {destination} | 사유: {reason}")

    history.add_message(
        "system",
        f"[ROUTING] {destination}: {reason}",
        metadata={"type": "routing", "sticky": state.current_agent is not None},
    )

    # ── 체크포인트: 라우팅 직후 (TRANSACTION) ─────────────────
    if checkpoint_mgr and ecfg.get("checkpoint_enabled", True):
        checkpoint_mgr.save_checkpoint(
            state, CheckpointType.TRANSACTION, label="post-routing"
        )

    # ── 2단계: 라우팅에 따라 실행 ────────────────────────────
    context = history.get_context()
    state.conversation_history = context

    if destination == "CLOUD":
        logger.info(f"☁️  [Cloud PM: {CLOUD_MODEL_NAME}] 고난도 작업 처리 중...")
        final_response = await call_cloud_pm(
            user_input, context=context, persona_manager=persona_mgr,
        )
        history.add_message(
            "assistant", final_response,
            metadata={
                "handler": CLOUD_MODEL_NAME,
                "reason": reason,
                "streamed": True,
                "persona": persona_mgr.current_id if persona_mgr else "default",
            },
        )
    else:
        logger.info("🔨 [Worker] 작업 실행 중...")
        result = await worker.execute(user_input, context=context)

        # Worker 실행 메타 로깅
        if result["helper_used"]:
            logger.info("  └─ ✅ Helper 활용 완료")
        if result["helper_fallback"]:
            logger.info("  └─ ⚠️ Helper 실패 → Worker 직접 처리")

        v_passed = result.get("validation_passed", True)
        c_passed = result.get("critic_passed")
        if v_passed is False:
            logger.warning("  └─ ❌ [Validator] 문법 검증 실패")
        if c_passed is False:
            logger.warning("  └─ ❌ [Critic] 비평가 거절")

        if result["escalated"]:
            if c_passed is False:
                esc_reason = "critic-reject"
            elif v_passed is False:
                esc_reason = "validation-fail"
            else:
                esc_reason = "worker-escalation"

            logger.info(f"🚨 [Worker → Cloud PM] 에스컬레이션 발생! (사유: {esc_reason})")
            logger.info(f"☁️  [Cloud PM: {CLOUD_MODEL_NAME}] 난제 처리 중...")

            state.reset_routing()

            escalation_context = (
                f"이전 Worker의 분석:\n{result['response']}\n\n"
                f"원본 요청:\n{user_input}"
            )
            final_response = await call_cloud_pm(
                escalation_context, context=context, persona_manager=persona_mgr,
            )
            history.add_message(
                "assistant", final_response,
                metadata={
                    "handler": CLOUD_MODEL_NAME,
                    "reason": esc_reason,
                    "validation_passed": v_passed,
                    "critic_passed": c_passed,
                    "worker_response": result["response"][:500],
                },
            )
        else:
            final_response = result["response"]
            history.add_message(
                "assistant", final_response,
                metadata={
                    "handler": "local-worker",
                    "helper_used": result["helper_used"],
                    "helper_fallback": result["helper_fallback"],
                    "validation_passed": v_passed,
                    "critic_passed": c_passed,
                },
            )

    # ── 3단계: 적대적 검증 (선택적) ──────────────────────────
    if (
        debate_loop
        and ecfg.get("debate_enabled", False)
        and ecfg.get("debate_auto_trigger_on_cloud", False)
        and destination == "CLOUD"
    ):
        logger.info("⚔️ Auto-triggering adversarial debate...")
        debate_result = await debate_loop.run(
            proposal=final_response,
            task=user_input,
            max_rounds=ecfg.get("debate_max_rounds", 3),
            approval_threshold=ecfg.get("debate_approval_threshold", 7.0),
        )
        if debate_result.approved:
            final_response = debate_result.final_proposal
            logger.info(
                f"⚔️ Debate approved after {debate_result.total_rounds} rounds"
            )
        elif debate_result.escalated:
            logger.warning("🚨 Debate escalated → HITL required")
            if hitl_mgr:
                await hitl_mgr.suspend(
                    state, "Adversarial debate escalation",
                    {"debate_report": debate_result.report},
                )

    # ── 체크포인트: 작업 완료 (MILESTONE) ─────────────────────
    if checkpoint_mgr and ecfg.get("checkpoint_enabled", True):
        checkpoint_mgr.save_checkpoint(
            state, CheckpointType.MILESTONE, label="task-complete"
        )

    logger.info("=" * 60)

    # 성공적인 응답을 캐시에 저장
    if cache and not final_response.startswith("[ERROR]"):
        cache.put(user_input, final_response)

    return final_response


def print_banner() -> None:
    """시작 배너 출력"""
    banner = f"""
╔══════════════════════════════════════════════════════════════╗
║       🤖 Mac Mini M4 Hybrid AI — Enterprise Edition        ║
║       ──────────────────────────────────────────            ║
║   Commands:                                                  ║
║    /new <project>    : 새 프로젝트 생성 및 전환               ║
║    /load <project>   : 기존 프로젝트 로드                     ║
║    /model <name>     : Cloud PM 모델 변경 (gemini/claude...) ║
║                        (Current: {CLOUD_MODEL_NAME})         ║
║    /list             : 프로젝트 목록 확인                     ║
║    /current          : 현재 상태 확인                         ║
║    /clear            : 대화 기록 초기화                       ║
║    /stats            : 대화 통계                              ║
║   Enterprise:                                                ║
║    /persona <id>     : 페르소나 전환                          ║
║    /checkpoint [lbl] : 수동 체크포인트 저장                    ║
║    /rollback [step]  : 체크포인트 롤백                        ║
║    /debate           : 마지막 응답에 적대적 검증               ║
║    /approve | /reject: HITL 승인/거절                          ║
║    /exit             : 종료                                   ║
╚══════════════════════════════════════════════════════════════╝
"""
    print(banner)


def switch_project(project_name: str) -> HistoryManager:
    """프로젝트 세션 전환"""
    history = HistoryManager(
        project_name=project_name,
        base_dir=HISTORY_DIR,
        context_window=CONTEXT_WINDOW,
    )
    print(f"\n📂 프로젝트 전환 완료: [{project_name}]")
    logger.info(f"📂 Active Project switched to: {project_name}")
    return history


async def main() -> None:
    """메인 루프 (async)"""
    global CLOUD_MODEL_NAME
    print_banner()

    # ── 초기 설정 ─────────────────────────────────────────────
    if not os.path.exists(HISTORY_DIR):
        os.makedirs(HISTORY_DIR)

    # Config 로드
    config = load_config()
    mcp_config = config.get("mcp_servers", {})

    # Enterprise 설정 로드
    enterprise_config_loader = ConfigLoader()
    enterprise_config = enterprise_config_loader.base.get("system", {})

    router = Router(base_url=LITELLM_BASE_URL)
    worker = Worker(base_url=LITELLM_BASE_URL)

    # MCP 도구 초기화
    if mcp_config:
        await worker.initialize_mcp_tools(mcp_config)

    # 기본 프로젝트로 시작
    history = HistoryManager(
        project_name="default",
        base_dir=HISTORY_DIR,
        context_window=CONTEXT_WINDOW,
    )

    # Enterprise 인프라 초기화
    state = AgentState()
    cache = SemanticCache()
    checkpoint_mgr = CheckpointManager(db_dir=HISTORY_DIR)
    persona_mgr = PersonaManager(config_loader=enterprise_config_loader)
    debate_loop = DebateLoop(
        persona_manager=persona_mgr,
        base_url=LITELLM_BASE_URL,
    )
    hitl_mgr = HITLManager(checkpoint_manager=checkpoint_mgr)

    # 마지막 응답 추적 (적대적 검증용)
    last_response: str = ""

    logger.info("✅ 시스템 초기화 완료 (Enterprise Edition)")
    logger.info(f"📡 LiteLLM Proxy: {LITELLM_BASE_URL}")
    logger.info(f"🎭 Active Persona: {persona_mgr.current_id}")

    # ── 인터랙티브 루프 ──────────────────────────────────────
    try:
        while True:
            try:
                persona_label = persona_mgr.current_id
                prompt_text = (
                    f"\n[{history.project_name} | "
                    f"{CLOUD_MODEL_NAME.split('-')[-1]} | "
                    f"🎭 {persona_label}] 🧑 You > "
                )
                user_input = await asyncio.to_thread(input, prompt_text)
                user_input = user_input.strip()
            except EOFError:
                print("\n👋 종료합니다.")
                break

            if not user_input:
                continue

            # ── CLI 명령어 처리 ──────────────────────────────────
            if user_input.startswith("/"):
                parts = user_input.split()
                cmd = parts[0].lower()
                args = parts[1:] if len(parts) > 1 else []

                if cmd in ("/exit", "/quit"):
                    print("👋 종료합니다.")
                    break

                elif cmd == "/clear":
                    history.clear()
                    state = AgentState()
                    continue

                elif cmd == "/stats":
                    stats = history.get_stats()
                    print(f"\n📊 통계 ({stats['project']}):")
                    print(f"   메시지 수: {stats['total_messages']}")
                    print(f"   파일 경로: {stats['file_path']}")
                    full = history.get_full_history()
                    handlers: dict[str, int] = {}
                    for msg in full:
                        h = (msg.get("metadata") or {}).get("handler", "")
                        if h:
                            handlers[h] = handlers.get(h, 0) + 1
                    if handlers:
                        print("   핸들러 분포:")
                        for h, cnt in sorted(handlers.items(), key=lambda x: -x[1]):
                            print(f"     {h}: {cnt}회")
                    continue

                elif cmd == "/list":
                    projects = HistoryManager.list_projects(HISTORY_DIR)
                    print("\n📂 저장된 프로젝트 목록:")
                    for p in projects:
                        print(f"   - {p}")
                    continue

                elif cmd == "/current":
                    print(f"\n🔍 현재 상태:")
                    print(f"   프로젝트: {history.project_name}")
                    print(f"   Cloud PM: {CLOUD_MODEL_NAME}")
                    print(f"   페르소나: {persona_mgr.current_id}")
                    print(f"   세션 ID: {state.session_id[:8]}...")
                    print(f"   단계: {state.step}")
                    print(f"   상태: {state.status.value}")
                    continue

                elif cmd == "/new":
                    if not args:
                        print("⚠️ 사용법: /new <project_name>")
                        continue
                    history = switch_project(args[0])
                    state = AgentState()
                    continue

                elif cmd == "/load":
                    if not args:
                        print("⚠️ 사용법: /load <project_name>")
                        continue
                    history = switch_project(args[0])
                    state = AgentState()
                    continue

                elif cmd == "/model":
                    if not args:
                        print(f"⚠️ 사용법: /model <name>")
                        print(f"   이름: {', '.join(MODEL_MAP.keys())} (gpt4=GPT-5.3-Codex)")
                        continue

                    new_model = args[0].lower()
                    if new_model in MODEL_MAP:
                        CLOUD_MODEL_NAME = MODEL_MAP[new_model]
                        print(f"✅ Cloud PM 모델이 변경되었습니다: {CLOUD_MODEL_NAME}")
                        logger.info(f"🔄 Switched Cloud PM model to {CLOUD_MODEL_NAME}")
                    else:
                        print(f"⚠️ 알 수 없는 모델입니다: {new_model}")
                        print(f"   사용 가능: {', '.join(MODEL_MAP.keys())}")
                    continue

                # ── Enterprise 명령어 ────────────────────────────

                elif cmd == "/persona":
                    if not args:
                        available = persona_mgr.available_personas()
                        print(f"\n🎭 현재 페르소나: {persona_mgr.current_id}")
                        print(f"   사용 가능: {', '.join(available)}")
                        continue
                    try:
                        new_persona = persona_mgr.switch_persona(
                            args[0], reason="Manual switch via CLI"
                        )
                        print(
                            f"🎭 페르소나 전환: {new_persona.display_name} "
                            f"(temp={new_persona.temperature})"
                        )
                    except FileNotFoundError:
                        print(f"⚠️ 페르소나를 찾을 수 없습니다: {args[0]}")
                        print(f"   사용 가능: {', '.join(persona_mgr.available_personas())}")
                    continue

                elif cmd == "/checkpoint":
                    label = " ".join(args) if args else "manual"
                    checkpoint_mgr.save_checkpoint(
                        state, CheckpointType.MILESTONE, label=label
                    )
                    print(f"💾 체크포인트 저장 완료: step={state.step}, label='{label}'")
                    continue

                elif cmd == "/rollback":
                    if not args:
                        cps = checkpoint_mgr.list_checkpoints(state.session_id)
                        if cps:
                            print("\n💾 체크포인트 목록:")
                            for cp in cps:
                                print(
                                    f"   step={cp['step']} | "
                                    f"type={cp['type']} | "
                                    f"label='{cp['label']}' | "
                                    f"{cp['created_at']}"
                                )
                        else:
                            print("⚠️ 저장된 체크포인트가 없습니다.")
                        continue
                    try:
                        step = int(args[0])
                        restored = checkpoint_mgr.rollback(state.session_id, step)
                        if restored:
                            state = restored
                            print(f"⏪ 롤백 완료: step={step}")
                        else:
                            print(f"⚠️ step={step}에 해당하는 체크포인트를 찾을 수 없습니다.")
                    except ValueError:
                        print("⚠️ 사용법: /rollback <step_number>")
                    continue

                elif cmd == "/debate":
                    if not last_response:
                        print("⚠️ 검증할 마지막 응답이 없습니다.")
                        continue
                    print("⚔️ 적대적 검증을 시작합니다...")
                    debate_result = await debate_loop.run(
                        proposal=last_response,
                        task="(마지막 응답 검증)",
                        max_rounds=enterprise_config.get("debate_max_rounds", 3),
                        approval_threshold=enterprise_config.get(
                            "debate_approval_threshold", 7.0
                        ),
                    )
                    print(f"\n⚔️ 검증 결과:")
                    print(f"   승인: {'✅' if debate_result.approved else '❌'}")
                    print(f"   라운드: {debate_result.total_rounds}")
                    if debate_result.report:
                        print(f"\n{debate_result.report}")
                    if debate_result.approved and debate_result.final_proposal != last_response:
                        last_response = debate_result.final_proposal
                        print(f"\n🤖 수정된 응답 > {last_response}")
                    continue

                elif cmd == "/approve":
                    restored = await hitl_mgr.resume(
                        state.session_id, action="approve"
                    )
                    if restored:
                        state = restored
                        print("✅ 승인 완료. 에이전트가 재개됩니다.")
                    else:
                        print("⚠️ 승인 대기 중인 요청이 없습니다.")
                    continue

                elif cmd == "/reject":
                    result = await hitl_mgr.resume(
                        state.session_id, action="reject"
                    )
                    print("❌ 거절 완료.")
                    continue

                else:
                    print(f"⚠️ 알 수 없는 명령어입니다: {cmd}")
                    print("   기본: /new, /load, /model, /list, /current, /clear, /stats, /exit")
                    print("   Enterprise: /persona, /checkpoint, /rollback, /debate, /approve, /reject")
                    continue

            # ── HITL 중단 상태 확인 ───────────────────────────────
            if state.status == SessionStatus.SUSPENDED:
                pending = hitl_mgr.get_pending(state.session_id)
                if pending:
                    print(
                        f"⏸️ 에이전트가 승인 대기 중입니다: {pending.get('reason', '')}"
                    )
                    print("   /approve 또는 /reject 명령어를 사용하세요.")
                    continue

            # ── 일반 처리 ────────────────────────────────────────
            try:
                response = await process_request(
                    user_input, router, worker, history, state, cache,
                    checkpoint_mgr=checkpoint_mgr,
                    persona_mgr=persona_mgr,
                    debate_loop=debate_loop,
                    hitl_mgr=hitl_mgr,
                    enterprise_config=enterprise_config,
                )
                last_response = response

                if not response.startswith("[ERROR]"):
                    last_msgs = history.get_full_history()[-1:]
                    streamed = any(
                        (m.get("metadata") or {}).get("streamed")
                        for m in last_msgs
                    )
                    if not streamed:
                        print(f"\n🤖 Assistant > {response}")

            except WaitApproval as e:
                # HITL 인터럽트 처리
                await hitl_mgr.suspend(
                    state, e.reason,
                    {"function": e.function_name, "args": e.function_args},
                )
                print(
                    f"\n⏸️ 에이전트가 승인을 요청합니다: {e.reason}"
                )
                print("   /approve 또는 /reject 명령어를 사용하세요.")

    except KeyboardInterrupt:
        print("\n👋 종료합니다.")
    finally:
        # MCP 연결 종료
        await global_mcp_manager.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
