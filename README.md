# Agentic Flow: Enterprise Hybrid AI Orchestration (V4)

**Agentic Flow**는 Mac Mini (Apple Silicon M4) 환경에 최적화된 하이브리드 AI 오케스트레이션 시스템입니다. 
V4 업데이트를 통해 **LangGraph 상태 관리, Human-in-the-Loop(HITL), Next.js 기반 Generative UI, 그리고 보안/Docker 배포 아키텍처**를 전면 도입했습니다.

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

### 🍎 M4 Deep Integration (v3)

*   **🔗 MCP Server (`server.py`)**: FastMCP 기반 상주형 서버. OpenClaw가 표준 프로토콜로 에이전트를 호출합니다. 서버 시작 시 모델 warm-up으로 콜드 스타트를 제거합니다.
*   **⚡ MLX Inference Engine**: Apple Silicon GPU 직접 활용. PyTorch/CUDA 없이 M4 10-core GPU 100% 활용합니다.
*   **RAM Tiering**: 16GB(Edge), 32GB(Standard), 64GB(Workstation), 128GB(Enterprise) 다이내믹 로딩
*   **🎹 Auto-Tune Skill**: `scripts/autotune.py`로 시스템에 맞는 최적 설정을 자동 적용합니다.

### 🌊 Enterprise Flow & Generative UI (v4 - 🚀 NEW)

*   **🔀 LangGraph Orchestration**: 기존 비동기 큐 로직을 벗어나 `StateGraph` 기반의 신뢰성 높은 그래프 워크플로우를 구축했습니다. `AsyncPostgresSaver`를 통한 완벽한 영속성(Persistence)과 무한 타임트래블(Time-Travel) 기능을 제공합니다.
*   **⏸️ Human-in-the-Loop (HITL) 2.0**: 결제, 보안 등 고위험 노드에서 실행을 멈추고(`interrupt_before`), 운영자가 개입하여 파라미터를 수정(`aupdate_state`)하거나 거부할 수 있습니다.
*   **🛑 Global Halt Control**: 무한 루프나 폭주를 막기 위해 Redis Pub/Sub을 활용한 실시간 강제 종료 데몬(`HaltManager`)을 탑재했습니다.
*   **📊 Observability & Cost Tracking**: OpenTelemetry + Prometheus 엔드포인트를 노출하여 실시간 애플리케이션 지표를 수집하며, LangSmith를 통합해 토큰 사용량과 예상 비용을 정산합니다.
*   **✨ Generative UI (Next.js & CopilotKit)**: 칙칙한 콘솔 로그를 버리고, `TailwindCSS`와 `shadcn/ui` 기반의 수려한 React 프론트엔드를 도입했습니다. `CopilotKit`을 통해 에이전트 상태를 실시간 연동하고 AI Assistant와 대화할 수 있는 대시보드를 제공합니다.
*   **🔐 Security & Deployment**: JWT 인증 기반 API 설계, `slowapi` 속도 제한(Rate Limiting), 역할 기반 인가(RBAC) 등 프로덕션 레벨 보안을 구축했습니다. 전체 스택은 `docker-compose` 하나로 완벽히 배포됩니다.

### 🧠 Claude Code Paradigm (V5 - 🚀 NEW)

*   **🧩 Task Decomposition & DAG Pipeline**: 고도화된 `TaskPlanner`를 통해 복잡한 프롬프트를 방향성 비순환 그래프(DAG) 형태의 하위 작업으로 자동 분해하여 순차 실행합니다.
*   **🔄 Context Lifecycle & Handoff**: `ContextMonitor`가 컨텍스트 열화(Context Rot)를 감지하면 `HANDOFF.md`를 자동 생성하고 새로운 세션을 스폰하여 안정적인 장기 기억을 유지합니다.
*   **💻 Enterprise Terminal & Input Engine**: `prompt_toolkit` 기반으로 터미널을 개편했습니다. `!` 접두어로 빠른 로컬 명령어 실행, `Shift+Tab`을 통한 Plan Mode 토글, `Esc` 입력을 통한 즉시 Rewind(실행 취소/스냅샷 롤백)를 지원합니다.
*   **⚖️ Meta-Governance & Intent Injection**: `CLAUDE.md` 등 규칙 파일을 파싱하여 "의도(Intent)"를 프롬프트에 자동 주입하며, 복잡도 기반 평가(`evaluate_complexity`)를 통해 고위험 작업 시 인간의 승인을 요구하는 강력한 제어망을 구축했습니다.
*   **🛡️ Autonomous Verification Sandbox**: 위험한 명령어는 격리된 `Safeclaw` (Docker 샌드박스)에서 실행되며, 백그라운드 `tmux` 세션을 활용해 자율 Write-Test 루프를 수행하고 그 결과를 LLM 컨텍스트에 캡처합니다.
*   **🧭 Alternative Exploration**: 실행 전 `AlternativeExplorer`가 비판적 사고를 강제하여 성능, 보안, 가독성을 최적화한 3가지 대안을 추가로 모색합니다.

### 🏰 Production Hardening & Core Unification (V5.1 - 🚀 NEW)

*   **🛡️ Real PostgreSQL Authentication**: `api/server.py`의 Mock 계정을 실제 비동기 DB 쿼리(`asyncpg`)를 활용한 JWT 기반 RBAC 로직으로 전면 교체했습니다.
*   **🔗 Unified AgentState**: LangGraph의 `TypedDict`와 기존 Pydantic 모델을 결합하여, 그래프 오케스트레이션과 체크포인트 메타데이터 간의 상태 파편화를 완벽히 제거했습니다.
*   **🔒 Docker Native Sandbox (Safeclaw)**: YAML 블랙리스트 기반 방식을 폐기하고 실제 `SandboxManager`의 브릿지 네트워크 모드와 Volume 마운트 제어 명세로 샌드박스 무결성을 높였습니다.
*   **📌 Zero-Day Dependency Pinning**: `mcp`, `pydantic`, `langgraph` 등 코어 라이브러리에 대해 PyPI API를 탐색해 2026년 기준 가장 강력한 안정화 최신 버전으로 100% 고정(`==`)했습니다.
*   **✂️ Architectural Code Pruning**: 사용되지 않던 Mock 노드(결제/영업/티어별 지원 등)를 삭제하고 `Router` 패스를 `Worker`로 직결해 워크플로우를 대폭 경량화했습니다.

### 🧠 Deep Memory Optimization (V5.2 - 🚀 NEW)

*   **🗜️ Semantic Memory Compression (Context Pruning)**: 긴 대화로 인한 Context Rot 방지 및 토큰 오버플로우를 막기 위해, 임계치 초과 시 과거 기억을 백그라운드에서 **`Dense English Shorthand`** (기계-중심적 축약어, e.g. `req:auth|db:ok`)로 자동 압축하여 시계열 데이터(SQLite)에 병합합니다.

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

openClaw:
  enabled: true
  mcp_server:
    enabled: true
    transport: "stdio"
    auto_warmup: true
  hardware_profile: "auto"       # "auto" (RAM 감지) 또는 "m4_64gb" 등 수동 지정
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

### 3. Run MCP Server (OpenClaw 연동)
OpenClaw와 연동할 때는 MCP 서버 모드로 실행합니다.
```bash
source .venv/bin/activate
python server.py                    # stdio 모드 (OpenClaw 연동)
python server.py --transport sse    # SSE 모드 (디버깅용)
```

### 4. Auto-Tune (New)
시스템에 가장 적합한 모델을 자동으로 찾아 설정합니다.
```bash
# 현재 상태 진단 및 추천
python scripts/autotune.py --mode check

# 최적 모델로 설정 자동 업데이트
python scripts/autotune.py --mode update
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
├── api/                        # FastAPI 엔드포인트 계층 (v4)
│   └── server.py               #   LangGraph 트리거, HITL, JWT 인증 및 프로메테우스 메트릭
├── core/                       # 코어 인프라 계층
│   ├── graph.py                #   LangGraph StateGraph 파이프라인 (v4)
│   ├── auth.py                 #   JWT Middleware & RBAC (v4)
│   ├── observability.py        #   Token Tracking & 비용 산출 (v4)
│   ├── redis_events.py         #   Pub/Sub 기반 HaltManager (v4)
│   ├── state.py                #   Pydantic AgentState 
│   ├── checkpoint.py           #   SQLite 체크포인트 (Legacy)
│   ├── config_loader.py        #   계층적 YAML 설정 + Jinja2
│   ├── sandbox.py              #   보안 샌드박스 (경로/명령어 검증)
│   └── engine_mlx.py           #   MLX 추론 엔진
├── frontend/                   # 🆕 Next.js Generative UI (v4)
│   ├── src/app/                #   CopilotKit 통합 라우터 및 대시보드
│   ├── src/components/         #   HITLApproval UI 및 shadcn 컴포넌트
│   └── Dockerfile              #   Next.js Standalone 빌드 설정
├── docker-compose.yml          # 🆕 V4 통합 오케스트레이션 (Postgres, Redis, API, UI)
├── Dockerfile.api              # 🆕 FastAPI 백엔드 이미지
├── core/                       # 코어 인프라 계층
│   ├── state.py                #   Pydantic v2 AgentState (직렬화/체크포인팅)
│   ├── checkpoint.py           #   SQLite 체크포인트 저장/롤백
│   ├── config_loader.py        #   계층적 YAML 설정 + Jinja2
│   ├── event_bus.py            #   비동기 EventBus (pub/sub, 12 이벤트 타입)
│   ├── sandbox.py              #   보안 샌드박스 (경로/명령어 검증)
│   ├── model_router.py         #   작업 티어 분류 + 비용 추적
│   └── engine_mlx.py           #   🆕 MLX 추론 엔진 (투기적 디코딩, KV Cache)
├── engine/                     # 엔진 계층
│   ├── persona.py              #   PersonaManager (핫스왑 + 전환 로깅)
│   ├── adversarial.py          #   DebateLoop (정-반-합 토론 루프)
│   ├── hitl.py                 #   HITL 인터럽트 핸들러
│   ├── soul.py                 #   SOUL.md 파서 → 시스템 프롬프트 주입
│   └── memory_file.py          #   MEMORY.md 읽기/쓰기/검색
├── agents/                     # 에이전트 계층
│   ├── router.py               #   Rule-based + LLM 라우팅
│   ├── worker.py               #   ReAct 도구 사용 루프 + Critic/Helper 위임
│   ├── critic.py               #   JSON 기반 코드 리뷰
│   └── helper.py               #   경량 작업 위임
├── gateway/                    # 외부 연동 계층
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
│   ├── structured_logger.py    #   구조화 이벤트 (JSONL 출력)
│   ├── hardware_probe.py       #   🆕 Apple Silicon 감지 + 메모리 모니터링
│   └── introspector.py         #   런타임 라이브러리 체크
├── config/                     # 🆕 하드웨어 프로파일 (RAM Tier)
│   ├── m4_16gb.yaml            #   16GB Edge (14B Q4)
│   ├── m4_32gb.yaml            #   32GB Standard (32B Q4)
│   ├── m4_64gb.yaml            #   64GB Workstation (70B Q4 + Speculative)
│   └── m4_128gb.yaml           #   128GB Enterprise (72B Q8 + In-Memory RAG)
├── configs/                    # 설정 파일
│   ├── base.yaml               #   전역 설정 (system/security/tiering/openclaw)
│   └── personas/               #   페르소나 YAML 정의
│       ├── worker.yaml
│       ├── architect.yaml
│       ├── coder.yaml
│       ├── devil.yaml
│       ├── moderator.yaml
│       └── security_auditor.yaml
├── openclaw_integration/       # 🆕 OpenClaw 스킬
│   ├── SKILL.md                #   스킬 정의 (트리거, 도구, 리소스)
│   └── install_skill.sh        #   스킬 설치 헬퍼
├── tests/
│   ├── test_improvements.py    #   기본 기능 테스트 (17 tests)
│   ├── test_enterprise.py      #   Enterprise 기능 테스트 (32 tests)
│   └── test_openclaw_integration.py  # OpenClaw 통합 테스트 (64 tests)
├── state.py                    # 하위 호환 alias → core.state
├── config.yaml                 # LiteLLM 프록시 설정
├── main.py                     # 메인 오케스트레이터 (EventBus 연동)
├── server.py                   # 🆕 FastMCP 상주형 서버 (OpenClaw 연동)
├── setup_m4.sh                 # 🆕 M4 원클릭 설치 스크립트
└── requirements.txt            # 의존성 패키지
```

## 🧪 Testing

```bash
# 전체 테스트 (113 tests)
python3 -m pytest tests/ -v

# OpenClaw 통합 테스트 (64 tests)
python3 -m pytest tests/test_openclaw_integration.py -v

# M4/MCP 관련 테스트만
python3 -m pytest tests/test_openclaw_integration.py -v -k "MLX or Hardware or MCP"

# Enterprise 테스트만 (32 tests)
python3 -m pytest tests/test_enterprise.py -v

# 기존 기능 테스트만 (17 tests)
python3 -m pytest tests/test_improvements.py -v
```

## 🍎 M4 Quick Start

Mac Mini M4에서 OpenClaw과 연동하려면:

```bash
# 1. 원클릭 설치
bash setup_m4.sh

# 2. OpenClaw 스킬 등록
bash openclaw_integration/install_skill.sh

# 3. MCP 서버 실행
source .venv/bin/activate
python server.py
```

## 📄 License

MIT License
