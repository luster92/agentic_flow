# Clawflow: Enterprise Hybrid AI Orchestration (V5.3)

**Clawflow**는 Mac Mini (Apple Silicon M4) 환경에 최적화된 하이브리드 AI 오케스트레이션 시스템입니다. 
V5.3 업데이트를 통해 **Intelligent API Key Discovery, Semantic Memory Compression, LangGraph 상태 관리, Human-in-the-Loop(HITL)** 기능을 완벽히 통합하여 엔터프라이즈 레벨의 프로덕션 안정성을 달성했습니다.

---

## 🚀 Ocherstration Core (V4)

*   **Hybrid Architecture**: 간단한 작업은 로컬(Ollama)에서, 복잡한 추론은 클라우드(Gemini/Claude)에서 처리하여 비용과 속도를 최적화합니다.
*   **Intelligent Routing**: `DeepSeek-R1` 기반의 Router가 사용자 입력의 난이도를 판단하여 최적의 모델(Worker, Critic, Cloud PM)로 경로를 지정합니다.
*   **Semantic Cache**: ChromaDB 벡터 유사도(≥0.95)로 FAQ/정적 응답을 즉시 반환하여 LLM 호출 비용을 제로화합니다.
*   **Generative UI (Next.js)**: 칙칙한 콘솔 로그를 버리고, `TailwindCSS`와 `shadcn/ui` 기반의 React 프론트엔드를 도입했습니다.
*   **Human-in-the-Loop (HITL)**: 인터럽트 기반 제어 메커니즘으로 결제/보안 등 민감한 작업 전 인간 승인을 요구하고, 파라미터를 수정한 뒤 재개할 수 있습니다.

---

## 🌟 The V5 Paradigm: Autonomy & Memory

### 🧠 Task & Context Mastery (V5.0)
*   **Task Decomposition & DAG**: 고도화된 `TaskPlanner`를 통해 복잡한 프롬프트를 방향성 비순환 그래프(DAG) 형태의 하위 작업으로 자동 분해하여 순차 실행합니다.
*   **Context Lifecycle & Handoff**: `ContextMonitor`가 컨텍스트 열화(Context Rot)를 감지하면 `HANDOFF.md`를 자동 생성하고 새로운 세션을 스폰하여 안정적인 장기 기억을 유지합니다.
*   **Autonomous Verification Sandbox**: 위험한 명령어는 격리된 `Safeclaw` (Docker 샌드박스)에서 실행되며, 백그라운드 `tmux` 세션을 활용해 자율 Write-Test 루프를 수행합니다.

### 🏰 Production Hardening & Core Unification (V5.1)
*   **Real PostgreSQL Authentication**: `api/server.py`에 실제 비동기 DB 쿼리(`asyncpg`)를 활용한 JWT 기반 RBAC 로직을 도입했습니다.
*   **Unified AgentState**: LangGraph의 `TypedDict`와 Pydantic 모델을 결합하여 상태 파편화를 완벽히 제거했습니다.
*   **Zero-Day Dependency Pinning**: `mcp`, `pydantic`, `langgraph` 등 코어 라이브러리를 최신 안정화 버전으로 100% 고정(`==`)하여 재현성을 보장합니다.

### 🧠 Deep Memory Optimization (V5.2)
*   **Semantic Memory Compression (Context Pruning)**: 긴 대화로 인한 Context Rot 방지 및 토큰 오버플로우를 막기 위해, 임계치 초과 시 과거 기억을 백그라운드에서 **`Dense English Shorthand`** (기계-중심적 축약어, e.g. `req:auth|db:ok`)로 자동 압축하여 시계열 데이터(SQLite)에 병합합니다.

### 🔑 Intelligent Onboarding UX (V5.3 - 🚀 LATEST)
*   **Auto-Sensing OpenClaw Keys**: 번거로운 `.env` 파일 수동 편집 없이, 부팅 시 백그라운드에서 `~/.openclaw` 환경을 스캔하여 활성화된 클라우드 LLM 모델의 API 키를 자동으로 발견합니다.
*   **Interactive Security Prompt**: OpenClaw 환경이 없더라도 CLI에서 안전하게 모델 선택 리스트를 띄워 마스킹 입력(`getpass`)을 받은 후 `.env` 생태계를 자율적으로 구성합니다.

---

## 🏗️ Architecture

```
User Input
    │
    ▼
┌─────────────────┐
│  Semantic Cache │──── HIT ──→ Cached Response (Latency ~0ms)
└────────┬────────┘
         │ MISS
         ▼
┌─────────────────┐
│ Sticky Routing? │──── Same Agent ──→ Worker / Cloud PM (Router 스킵)
└────────┬────────┘
         │ New Context
         ▼
┌─────────────────┐
│     Router      │──── LOCAL ──→ Worker ──→ Validator ──→ Critic
│  (DeepSeek-R1)  │                                          │
└────────┬────────┘                              REJECT ──→ Cloud PM
         │ CLOUD                                               │
         ▼                                                     ▼
┌─────────────────┐                              ┌─────────────────────┐
│    Cloud PM     │──────────────────────────────│  ⚔️ DebateLoop       │
│ (Gemini/Claude) │                              │ Devil → Moderator   │
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

*   **macOS** (Apple Silicon M4 Native 최적화)
*   **Python 3.11+**
*   **Ollama**: 로컬 모델 실행용 ([Download](https://ollama.com))
*   **Docker**: Safeclaw 샌드박스 실행 보장용

## 📦 Quick Start

1.  **Repository Clone & Env Setup**
    ```bash
    git clone https://github.com/luster92/clawflow.git
    cd clawflow
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    ```

2.  **Run Orchestrator (Auto-Onboarding)**
    `.env` 파일을 직접 수동 생성할 필요가 없습니다. 아래 명령어를 치면 **V5.3 Intelligent Key Discovery**가 자동으로 LLM API 키를 세팅해 줍니다.
    ```bash
    python main.py
    ```

3.  **Prepare Local Models (Ollama)**
    ```bash
    ollama pull deepseek-r1:8b        # Router
    ollama pull qwen2.5-coder:32b     # Worker
    ollama pull phi4-mini             # Helper
    ```

4.  **API / Web Server (Background)**
    ```bash
    uvicorn api.server:app --reload
    ```

## 💻 CLI Commands (Interactive Terminal)

| 명령어 | 설명 |
|---|---|
| `/new <project>` | 새 프로젝트 세션 생성 |
| `/load <project>` | 기존 프로젝트 세션 로드 (SQLite 체크포인트 복원) |
| `/model <name>` | Cloud PM 모델 핫스왑 (gemini / claude / gpt4 / deepseek) |
| `/persona <id>` | 동작 페르소나 전환 (worker / architect / devil / security_auditor) |
| `/checkpoint` | 수동 마일스톤 체크포인트 강제 저장 |
| `/debate` | 마지막 AI 응답에 대해 적대적 검증(Devil's Advocate) 강제 실행 |
| `/approve` | HITL (Human-in-the-Loop) 일시정지 승인 |
| `/stats` | 토큰 사용량 및 발생 누적 비용 리포트 출력 |
| `/clear` | 현재 세션 메모리 및 컨텍스트 초기화 |
| `/exit` | 안전 종료 (MCP, EventBus, Tmux 해제) |

## 📂 Project Structure

```text
clawflow/
├── api/                        # FastAPI 엔드포인트 계층 (v5.1 Postgres Auth)
├── core/                       # 코어 인프라 계층
│   ├── graph.py                # LangGraph StateGraph 파이프라인 (Unified State)
│   ├── auth.py                 # JWT Middleware & RBAC 
│   ├── observability.py        # Token Tracking & 비용 산출
│   ├── redis_events.py         # Pub/Sub 기반 HaltManager
│   ├── state.py                # Pydantic AgentState 
│   ├── config_loader.py        # 계층적 YAML 설정
│   └── engine_mlx.py           # MLX 추론 엔진
├── frontend/                   # Next.js Generative UI
├── engine/                     # 동작 제어 엔진 계층
│   ├── persona.py              # PersonaManager (핫스왑)
│   ├── adversarial.py          # DebateLoop (정-반-합 토론)
│   ├── hitl.py                 # HITL 인터럽트 핸들러
│   ├── sandbox.py              # Docker Native Safeclaw Sandbox
│   └── tmux_integration.py     # 터미널용 백그라운드 세션 세팅
├── agents/                     # 워커 및 라우터 모델 계층
│   ├── router.py               # Rule-based + LLM 라우팅
│   ├── worker.py               # ReAct 도구 사용 루프
│   ├── critic.py               # JSON 코드 리뷰어
│   └── helper.py               # 경량 작업 위임 처리 (Phi-4)
├── utils/                      # 유틸리티 (V5.X 핫-피처 모음)
│   ├── history_manager.py      # SQLite 대화기록 + **Semantic Memory Compression**
│   ├── key_manager.py          # **Intelligent API Key Discovery** 로그
│   ├── mcp_client.py           # MCP 프로토콜 어댑터
│   └── semantic_cache.py       # 시맨틱 응답 캐시 엔진
├── scripts/                    # 오토 튜닝, Dep 패키지 Fetch 관리 스크립트 등
├── tests/                      # 파이테스트 100+ Suites (Memory Compression 등)
├── main.py                     # CLI 메인 오케스트레이터
└── requirements.txt            # Zero-Day Pinning Dependencies
```

## 📄 License
MIT License
