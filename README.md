# Agentic Flow: Mac Mini M4 Hybrid AI Orchestration

**Agentic Flow**는 Mac Mini (Apple Silicon M4) 환경에 최적화된 하이브리드 AI 오케스트레이션 시스템입니다. 로컬 LLM의 빠른 속도와 클라우드 모델의 강력한 추론 능력을 결합하여 효율적인 에이전트 워크플로우를 제공합니다.

## 🚀 Key Features

*   **Hybrid Architecture**: 간단한 작업은 로컬(Ollama)에서, 복잡한 추론은 클라우드(Gemini/Claude)에서 처리합니다.
*   **Intelligent Routing**: `DeepSeek-R1` 기반의 Router가 사용자 입력의 난이도를 판단하여 최적의 모델로 경로를 지정합니다.
*   **Sticky Routing**: 연속 대화 시 Router를 우회하여 동일 에이전트가 계속 처리, 라우팅 토큰 비용 ~80% 절감.
*   **Multi-Agent System**:
    *   **Router**: 작업 분석 및 경로 설정 (Rule-based 프리필터 + LLM 라우팅)
    *   **Worker**: 실제 코드 작성 및 문제 해결 (Qwen 2.5 Coder)
    *   **Critic**: JSON 기반 코드 리뷰 (PASS/REJECT/NEEDS_WORK)
    *   **Helper**: 간단한 작업 위임 (Phi-4 Mini)
    *   **Cloud PM**: 고난도 기획 및 에스컬레이션 처리 (Gemini / Claude / GPT)
*   **MCP (Model Context Protocol)**: 표준화된 프로토콜을 통해 파일 시스템, 웹 검색 등 외부 도구를 확장성 있게 연결합니다.
*   **Semantic Cache**: ChromaDB 벡터 유사도(≥0.95)로 FAQ/정적 응답을 즉시 반환, LLM 호출 제로.
*   **Context Engineering**: 에이전트 간 핸드오프 시 요약 + 엔티티 기반 컨텍스트 전달로 토큰 낭비 방지.
*   **Tool Safety**: Pydantic 기반 도구 입력 검증으로 런타임 에러 대신 에이전트 피드백 제공.
*   **Observability**: 토큰 사용량, 추정 비용, 캐시 히트율, Sticky 라우팅율 등 종합 메트릭 추적.

### 🏢 Enterprise Edition (v2)

*   **🎭 Dynamic Persona System**: 6개 전문 페르소나(Worker, Architect, Coder, Devil's Advocate, Moderator, Security Auditor)를 YAML 기반으로 정의하고 런타임에 핫스왑합니다.
*   **⚔️ Adversarial Verification**: 변증법적 정-반-합(Thesis-Antithesis-Synthesis) 토론 루프를 통해 단일 에이전트의 환각과 편향을 극복합니다.
*   **💾 Persistent Checkpointing**: SQLite 기반 체크포인트로 에이전트 상태를 영속적으로 저장하고 임의 시점으로 롤백할 수 있습니다.
*   **⏸️ Human-in-the-Loop (HITL)**: 인터럽트 기반 제어 메커니즘으로 민감한 작업 전 인간 승인을 요구하고, 상태를 수정한 뒤 재개할 수 있습니다.
*   **⚙️ Hierarchical Config**: 계층적 YAML 설정 + Jinja2 템플릿으로 런타임 변수 주입을 지원합니다.

### 🌐 OpenClaw Integration (v3)

*   **📡 Event-Driven Architecture**: `asyncio.Queue` 기반 비동기 이벤트 버스. 12가지 이벤트 타입(USER_MESSAGE, AGENT_RESPONSE, TOOL_CALL 등)의 pub/sub 패턴으로 컴포넌트 간 느슨한 결합을 구현합니다.
*   **🛡️ Sandboxed Tool Execution**: 경로 화이트리스트, 명령어 블랙리스트, 심볼릭 링크 탐지로 도구 실행 보안을 강화합니다. 모든 파일 접근이 `SandboxManager`를 통해 검증됩니다.
*   **📊 Model Tiering & Cost Tracking**: 작업 복잡도를 SIMPLE/STANDARD/COMPLEX로 분류하고 최적 모델을 자동 선택합니다. 세션별 토큰 비용을 실시간 추적합니다.
*   **📈 Structured Observability**: thought/tool_call/decision/error/metric 5가지 이벤트 타입을 JSONL 파일로 기록합니다. 외부 UI에서 에이전트 내부 상태를 시각화할 수 있습니다.
*   **📜 SOUL/MEMORY Integration**: OpenClaw의 `SOUL.md`에서 에이전트 성격/말투/원칙을 파싱하여 시스템 프롬프트에 주입합니다. `MEMORY.md`로 장기 기억을 관리하고 키워드 검색을 지원합니다.
*   **🔌 Gateway Approval Bridge**: HITL 승인 채널을 추상화하여 CLI, WebSocket, HTTP 등 다양한 승인 경로를 지원합니다. 타임아웃 기반 자동 거절 기능을 포함합니다.

## 🏗️ Architecture

```
User Input
    │
    ▼
┌─────────────────┐
│  Semantic Cache  │──── HIT ──→ Cached Response (Latency ~0ms)
└────────┬────────┘
         │ MISS
         ▼
┌─────────────────┐
│ Sticky Routing?  │──── Same Agent ──→ Worker / Cloud PM (Router 스킵)
└────────┬────────┘
         │ New Context
         ▼
┌─────────────────┐
│     Router       │──── LOCAL ──→ Worker ──→ Validator ──→ Critic
│  (DeepSeek-R1)   │                                          │
└────────┬────────┘                              REJECT ──→ Cloud PM
         │ CLOUD                                               │
         ▼                                                     ▼
┌─────────────────┐                              ┌─────────────────────┐
│    Cloud PM      │──────────────────────────────│  ⚔️ DebateLoop       │
│ (Gemini/Claude)  │                              │ Devil → Moderator   │
└─────────────────┘                              │ → Worker (수정)     │
                                                  └─────────┬───────────┘
                                                            │ ESCALATE
                                                            ▼
                                                  ┌─────────────────────┐
                                                  │ ⏸️ HITL Manager      │
                                                  │ /approve · /reject  │
                                                  └─────────────────────┘
```

## 🛠 Prerequisites

*   **macOS** (Apple Silicon 권장)
*   **Python 3.11+**
*   **Ollama**: 로컬 모델 실행용 ([Download](https://ollama.com))

## 📦 Installation

1.  **Repository Clone**
    ```bash
    git clone https://github.com/luster92/agentic_flow.git
    cd agentic_flow
    ```

2.  **Virtual Environment Setup**
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    ```

3.  **Install Dependencies**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Environment Variables**
    `.env.example`을 복사하여 `.env` 파일을 생성하고 API 키를 설정합니다.
    ```bash
    cp .env.example .env
    vi .env
    # GEMINI_API_KEY, ANTHROPIC_API_KEY 등 설정
    ```

5.  **Prepare Local Models (Ollama)**
    `config.yaml`에 정의된 모델을 다운로드합니다.
    ```bash
    ollama pull deepseek-r1:8b        # Router
    ollama pull qwen2.5-coder:32b     # Worker
    ollama pull phi4-mini             # Helper
    ```

## ⚙️ Configuration

`config.yaml` 파일에서 모델 매핑 및 설정을 변경할 수 있습니다.

*   `local-router`: 라우팅 담당 (Default: DeepSeek-R1)
*   `local-worker`: 메인 작업 담당 (Default: Qwen 2.5 Coder)
*   `cloud-pm`: 에스컬레이션 담당 (Gemini, Claude, GPT 선택 가능)

Enterprise 설정은 `configs/base.yaml`에서 관리됩니다:
```yaml
system:
  default_persona: "worker"
  checkpoint_enabled: true
  debate_enabled: true
  debate_max_rounds: 3
  hitl_enabled: true
```

## ▶️ Usage

이 시스템은 **LiteLLM Proxy**와 **Main Agent**가 동시에 실행되어야 합니다.

### 1. Start LiteLLM Proxy (Background)
로컬 및 클라우드 모델을 통합하는 프록시 서버를 실행합니다.
```bash
litellm --config config.yaml --port 4000
```

### 2. Run Main Agent
별도의 터미널에서 메인 에이전트를 실행합니다.
```bash
source .venv/bin/activate
python main.py
```

### 3. Commands

#### 기본 명령어
| 명령어 | 설명 |
|---|---|
| `/new <project>` | 새 프로젝트 세션 생성 |
| `/load <project>` | 기존 프로젝트 로드 |
| `/model <name>` | Cloud PM 모델 변경 (gemini / claude / gpt4) |
| `/list` | 프로젝트 목록 확인 |
| `/current` | 현재 상태 확인 |
| `/stats` | 성능 메트릭 및 토큰 비용 |
| `/clear` | 대화 기록 초기화 |
| `/exit` | 종료 |

#### Enterprise 명령어
| 명령어 | 설명 |
|---|---|
| `/persona <id>` | 페르소나 전환 (worker / architect / coder / devil / moderator / security_auditor) |
| `/checkpoint [label]` | 수동 마일스톤 체크포인트 저장 |
| `/rollback [step]` | 특정 단계로 롤백 (인자 없으면 목록 표시) |
| `/debate` | 마지막 응답에 적대적 검증(Devil's Advocate) 실행 |
| `/approve` | HITL 승인 (에이전트 재개) |
| `/reject` | HITL 거절 |

### 4. Persona Examples

```bash
# Devil's Advocate로 전환하여 비판적 분석
/persona devil
이 아키텍처에 보안 취약점이 있을까?

# Security Auditor로 전환하여 레드팀 분석
/persona security_auditor
main.py의 보안 감사를 수행해줘

# Worker로 복귀
/persona worker
```

## 📂 Project Structure

```
agentic_flow/
├── core/                       # 코어 인프라 계층
│   ├── state.py                #   Pydantic v2 AgentState (직렬화/체크포인팅)
│   ├── checkpoint.py           #   SQLite 체크포인트 저장/롤백
│   ├── config_loader.py        #   계층적 YAML 설정 + Jinja2
│   ├── event_bus.py            #   🆕 비동기 EventBus (pub/sub, 12 이벤트 타입)
│   ├── sandbox.py              #   🆕 보안 샌드박스 (경로/명령어 검증)
│   └── model_router.py         #   🆕 작업 티어 분류 + 비용 추적
├── engine/                     # 엔진 계층
│   ├── persona.py              #   PersonaManager (핫스왑 + 전환 로깅)
│   ├── adversarial.py          #   DebateLoop (정-반-합 토론 루프)
│   ├── hitl.py                 #   HITL 인터럽트 핸들러
│   ├── soul.py                 #   🆕 SOUL.md 파서 → 시스템 프롬프트 주입
│   └── memory_file.py          #   🆕 MEMORY.md 읽기/쓰기/검색
├── agents/                     # 에이전트 계층
│   ├── router.py               #   Rule-based + LLM 라우팅
│   ├── worker.py               #   ReAct 도구 사용 루프 + Critic/Helper 위임
│   ├── critic.py               #   JSON 기반 코드 리뷰
│   └── helper.py               #   경량 작업 위임
├── gateway/                    # 🆕 외부 연동 계층
│   └── approval_bridge.py      #   승인 채널 추상화 (CLI/Callback)
├── utils/                      # 유틸리티
│   ├── history_manager.py      #   SQLite 대화 기록 + Context Filter
│   ├── memory.py               #   ChromaDB 벡터 메모리
│   ├── semantic_cache.py       #   시맨틱 응답 캐시
│   ├── tools.py                #   Pydantic 검증 도구 + Sandbox 연동
│   ├── metrics.py              #   토큰/비용/캐시 추적
│   ├── mcp_client.py           #   MCP 프로토콜 어댑터
│   ├── validator.py            #   AST + Sandbox 코드 검증
│   ├── rate_limiter.py         #   슬라이딩 윈도우 속도 제한
│   ├── structured_logger.py    #   🆕 구조화 이벤트 (JSONL 출력)
│   └── introspector.py         #   런타임 라이브러리 체크
├── configs/                    # 설정 파일
│   ├── base.yaml               #   전역 설정 (system/security/tiering/openclaw)
│   └── personas/               #   페르소나 YAML 정의
│       ├── worker.yaml
│       ├── architect.yaml
│       ├── coder.yaml
│       ├── devil.yaml
│       ├── moderator.yaml
│       └── security_auditor.yaml
├── tests/
│   ├── test_improvements.py    #   기본 기능 테스트 (17 tests)
│   ├── test_enterprise.py      #   Enterprise 기능 테스트 (32 tests)
│   └── test_openclaw_integration.py  #  🆕 OpenClaw 통합 테스트 (44 tests)
├── state.py                    # 하위 호환 alias → core.state
├── config.yaml                 # LiteLLM 프록시 설정
├── main.py                     # 메인 오케스트레이터 (EventBus 연동)
└── requirements.txt            # 의존성 패키지
```

## 🧪 Testing

```bash
# 전체 테스트 (93 tests)
python3 -m pytest tests/ -v

# OpenClaw 통합 테스트 (44 tests)
python3 -m pytest tests/test_openclaw_integration.py -v

# Enterprise 테스트만 (32 tests)
python3 -m pytest tests/test_enterprise.py -v

# 기존 기능 테스트만 (17 tests)
python3 -m pytest tests/test_improvements.py -v
```

## 📄 License

MIT License
