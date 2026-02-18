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
         │ CLOUD
         ▼
┌─────────────────┐
│    Cloud PM      │
│ (Gemini/Claude)  │
└─────────────────┘
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
에이전트 실행 후 다음 명령어를 사용할 수 있습니다.
*   `/new <project>`: 새 프로젝트 세션 생성
*   `/load <project>`: 기존 프로젝트 로드
*   `/model <name>`: Cloud PM 모델 변경 (예: `/model claude`)
*   `/list`, `/current`: 프로젝트 목록 및 현재 상태 확인
*   `/stats`: 성능 메트릭 및 토큰 비용 요약
*   `/clear`: 대화 기록 및 상태 초기화

## 📂 Project Structure

```
agentic_flow/
├── agents/
│   ├── router.py           # Rule-based + LLM 라우팅
│   ├── worker.py           # ReAct 도구 사용 루프 + Critic/Helper 위임
│   ├── critic.py           # JSON 기반 코드 리뷰
│   └── helper.py           # 경량 작업 위임
├── utils/
│   ├── history_manager.py  # SQLite 대화 기록 + Semantic Context Filter
│   ├── memory.py           # ChromaDB 벡터 메모리
│   ├── semantic_cache.py   # 시맨틱 응답 캐시 (ChromaDB)
│   ├── tools.py            # Pydantic 검증 도구 프레임워크
│   ├── metrics.py          # 토큰/비용/캐시 추적 메트릭
│   ├── mcp_client.py       # MCP 프로토콜 어댑터
│   ├── validator.py        # AST + Sandbox 코드 검증
│   ├── rate_limiter.py     # 슬라이딩 윈도우 속도 제한
│   └── introspector.py     # 런타임 라이브러리 체크
├── state.py                # AgenticState 구조화 상태 객체
├── tests/
│   └── test_improvements.py
├── config.yaml             # 모델 및 시스템 설정
├── main.py                 # 메인 오케스트레이터
└── requirements.txt        # 의존성 패키지 목록
```

## 🧪 Testing

```bash
python3 -m pytest tests/ -v
```

## 📄 License

MIT License
