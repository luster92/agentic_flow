# Agentic Flow: Mac Mini M4 Hybrid AI Orchestration

**Agentic Flow**는 Mac Mini (Apple Silicon M4) 환경에 최적화된 하이브리드 AI 오케스트레이션 시스템입니다. 로컬 LLM의 빠른 속도와 클라우드 모델의 강력한 추론 능력을 결합하여 효율적인 에이전트 워크플로우를 제공합니다.

## 🚀 Key Features

*   **Hybrid Architecture**: 간단한 작업은 로컬(Ollama)에서, 복잡한 추론은 클라우드(Gemini/Claude)에서 처리합니다.
*   **Intelligent Routing**: `DeepSeek-R1` 기반의 Router가 사용자 입력의 난이도를 판단하여 최적의 모델로 경로를 지정합니다.
*   **Multi-Agent System**:
    *   **Router**: 작업 분석 및 경로 설정
    *   **Worker**: 실제 코드 작성 및 문제 해결 (Qwen 2.5 Coder)
    *   **Cloud PM**: 고난도 기획 및 에스컬레이션 처리 (Gemini 1.5 Pro / Claude 3.5 Sonnet)
*   **MCP (Model Context Protocol)**: 표준화된 프로토콜을 통해 파일 시스템, 웹 검색 등 외부 도구를 확장성 있게 연결합니다.
*   **Context Management**: 프로젝트별 대화 기록 및 컨텍스트를 독립적으로 관리합니다.

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

## 📂 Project Structure

```
agentic_flow/
├── agents/             # 각 에이전트 구현체 (Router, Worker, etc.)
├── utils/              # 유틸리티 (History, MCP Client, Tools)
├── config.yaml         # 모델 및 시스템 설정
├── main.py             # 메인 실행 파일
└── requirements.txt    # 의존성 패키지 목록
```

## 📄 License

MIT License
