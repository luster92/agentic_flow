# Clawflow: Hybrid AI Orchestration Framework (V5.4-dev)

**Clawflow**는 Apple Silicon 로컬 모델과 외부 LLM API를 하나의 정책 기반 실행 그래프로 연결하는 하이브리드 AI 오케스트레이션 프레임워크입니다.

현재 개발 브랜치는 기존 `LOCAL | CLOUD` 이진 라우팅을 구조화된 multi-tier 정책으로 확장하고, CLI/API가 공유할 수 있는 dependency-injected LangGraph 실행 코어를 도입합니다.

---

## Core capabilities

- **Hybrid execution**: 반복·저위험 작업은 로컬 모델로 처리하고, 복잡하거나 전문 모델이 필요한 작업만 클라우드로 승격합니다.
- **Structured routing policy**: 작업 유형, 실행 티어, 위험도, 도구·비전·HITL 요구사항, 로컬 전용 여부를 분리하여 판단합니다.
- **Quality-based escalation**: 로컬 Worker의 deterministic validation 또는 Critic 검증이 실패하면 Cloud Specialist로 승격합니다.
- **Semantic cache**: 재사용 가능한 응답은 모델 호출 전에 단락 처리합니다.
- **Shared LangGraph runtime**: 캐시, 분류, 승인, 로컬 실행, 클라우드 승격, 저장 단계를 CLI/API/Web이 공유할 수 있습니다.
- **MCP and tool use**: Worker가 내장 도구와 MCP 서버 도구를 동일한 실행 루프에서 사용할 수 있습니다.
- **Human-in-the-loop**: 배포, 삭제, 결제 등 위험 작업은 실행 전에 승인 게이트를 통과해야 합니다.
- **Persistent memory and checkpoints**: 대화 기록, 장기 기억, 실행 체크포인트를 용도별로 관리합니다.

---

## Execution flow

```text
User request
    │
    ▼
Semantic cache ── HIT ──→ Persist / return
    │ MISS
    ▼
Structured router
    │
    ├─ local_fast / local_quality / deep_local
    │          │
    │          ▼
    │      Local Worker
    │          │
    │          ├─ validation PASS ──→ Persist
    │          └─ validation/critic FAIL
    │                         │
    └─ cloud_general / cloud_specialist
                              │
                              ▼
                     Cloud execution
                              │
                              ▼
                           Persist
```

이 흐름은 `core/orchestration_graph.py`에 dependency-injected LangGraph로 구현되어 있습니다. Router, Worker, Cloud caller, Cache, HITL, persistence adapter는 transport 계층에서 주입합니다.

---

## Model aliases

애플리케이션은 실제 provider 모델명이 아니라 안정적인 역할 alias만 사용합니다.

```text
local-fast
local-quality
deep-local
cloud-general
cloud-coding
cloud-reasoning
cloud-long-context
cloud-specialist
```

LiteLLM은 각 alias 아래에서 직접 API, OpenRouter, Ollama, MLX 또는 OpenAI-compatible endpoint의 timeout, retry, fallback과 비용 정책을 담당합니다.

---

## Prerequisites

- macOS 또는 Linux
- Python 3.11+
- Ollama 또는 다른 OpenAI-compatible 로컬 endpoint
- Docker: 격리 실행이 필요한 경우
- PostgreSQL/Redis: 영속 체크포인트 및 분산 이벤트를 사용할 경우

---

## Quick start

```bash
git clone https://github.com/luster92/clawflow.git
cd clawflow
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

LiteLLM Proxy:

```bash
litellm --config config.yaml --port 4000
```

Graph-native CLI:

```bash
python main_graph.py
```

기존 전체 기능 CLI는 마이그레이션 기간에 계속 사용할 수 있습니다.

```bash
python main.py
```

로컬 모델 예시:

```bash
ollama pull deepseek-r1:8b
ollama pull qwen2.5-coder:32b
ollama pull phi4-mini
```

`deep-local`은 기본적으로 `http://localhost:8000/v1`의 OpenAI-compatible endpoint와 `local-secret` 키를 사용합니다. 다른 주소나 키를 사용할 경우 `config.yaml`의 해당 deployment를 변경합니다.

---

## Project structure

```text
clawflow/
├── api/                         # FastAPI transport and authentication
├── core/
│   ├── orchestration_graph.py   # Shared dependency-injected LangGraph runtime
│   ├── routing_schema.py        # Structured routing contract
│   ├── model_policy.py          # Routing decision → stable model alias
│   ├── graph.py                 # Graph factory and legacy checkpoint graph
│   ├── state.py                 # Persistent session state
│   └── observability.py         # Token and cost accounting
├── agents/
│   ├── router.py                # Rule-first + LLM structured router
│   ├── worker.py                # Tool-using local Worker and quality escalation
│   ├── critic.py
│   └── helper.py
├── engine/                      # HITL, sandbox, persona, adversarial evaluation
├── utils/                       # Cache, memory, MCP, history, key management
├── frontend/                    # Next.js UI
├── tests/
├── main_graph.py                # Graph-native CLI entrypoint
├── main.py                      # Legacy full-feature CLI during migration
└── config.yaml                  # LiteLLM model aliases, fallback, and MCP config
```

---

## Migration status

완료된 작업:

1. Structured routing contract와 provider-independent model policy
2. 공통 LangGraph 실행 코어
3. Semantic cache, HITL gate, local execution, quality escalation, persistence 상태 전이
4. Graph-native CLI entrypoint
5. LiteLLM alias 및 fallback 설정

남은 핵심 작업:

1. FastAPI adapter를 공통 graph invocation으로 전환
2. Graph-native CLI에 HITL resume와 전체 legacy 명령어 이식
3. PostgreSQL checkpointer를 shared runtime에 연결
4. conversation store, vector memory, semantic cache의 저장 책임 명확화

---

## License

MIT License
