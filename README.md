# Clawflow: Hybrid AI Orchestration Framework (V5.4-dev)

**Clawflow**는 Apple Silicon 로컬 모델과 외부 LLM API를 하나의 정책 기반 실행 그래프로 연결하는 하이브리드 AI 오케스트레이션 프레임워크입니다.

현재 개발 브랜치는 기존 `LOCAL | CLOUD` 이진 라우팅을 구조화된 multi-tier 정책으로 확장하고, CLI/API/Web이 공유할 수 있는 dependency-injected LangGraph 실행 코어를 도입합니다.

> 현재 상태는 production-ready가 아니라 **production-oriented experimental runtime**입니다. 기존 `main.py`는 호환성을 위해 유지하며, 신규 개발은 `main_graph.py`와 `core/orchestration_graph.py`를 기준으로 진행합니다.

## Agent handoff

다른 개발자나 AI agent가 작업을 이어받을 때는 다음 순서로 확인합니다.

1. `README.md`
2. `core/routing_schema.py`
3. `core/model_policy.py`
4. `core/orchestration_graph.py`
5. `core/runtime.py`
6. `main_graph.py`
7. `config.yaml`
8. `tests/`

### 작업 원칙

- 신규 오케스트레이션 로직을 `main.py`에 추가하지 않습니다.
- provider의 실제 모델명을 agent/runtime 코드에 직접 넣지 않습니다.
- Router는 모델명을 선택하지 않고 작업 속성을 반환합니다.
- 모델 선택과 fallback은 `ModelPolicy`와 LiteLLM 설정에서 처리합니다.
- 인프라 장애 fallback과 품질 실패 elevation을 구분합니다.
- CLI, FastAPI, Web은 동일한 compiled graph를 호출해야 합니다.
- 기존 legacy 기능을 제거하기 전 동일 기능의 graph adapter와 회귀 테스트를 먼저 만듭니다.

## Runtime flow

```text
User request
    │
    ▼
Semantic cache ── HIT ──→ Persist / return
    │ MISS
    ▼
Structured Router
    │
    ▼
Model Policy → LiteLLM alias
    │
    ├─ requires approval ──→ HITL interrupt/resume
    │
    ├─ local_fast / local_quality / deep_local
    │          │
    │          ├─ validation PASS ───────────────→ Persist
    │          └─ validation/critic/escalate FAIL
    │                                 │
    │                                 ▼
    │                         nvidia-glm52 elevation
    │                                 │
    └─ cloud_general / cloud_specialist
                                      │
                                      ▼
                                   Persist
```

`local_only=true` 요청은 NVIDIA 또는 다른 외부 endpoint로 elevation하지 않습니다.

## Model aliases

애플리케이션은 실제 provider 모델명이 아니라 역할 alias만 사용합니다.

```text
local-router
local-fast
local-quality
local-helper
deep-local
nvidia-glm52
cloud-general
cloud-coding
cloud-reasoning
cloud-long-context
cloud-specialist
```

### NVIDIA GLM-5.2

`nvidia-glm52`는 local-quality 결과가 검증 또는 critic 단계에서 실패했을 때 사용하는 명시적 elevation target입니다.

```text
alias:       nvidia-glm52
model:       z-ai/glm-5.2
API base:    https://integrate.api.nvidia.com/v1
environment: NVIDIA_API_KEY
```

상세 내용은 `docs/NVIDIA_GLM52.md`를 확인합니다.

## Entry points

Graph-native CLI:

```bash
python main_graph.py
```

Legacy CLI:

```bash
python main.py
```

FastAPI:

```bash
uvicorn api.server:app --reload
```

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
export NVIDIA_API_KEY="..."
litellm --config config.yaml --port 4000
```

## Environment

```text
LITELLM_BASE_URL=http://localhost:4000
LITELLM_API_KEY=not-needed
NVIDIA_API_KEY=...
GEMINI_API_KEY=...
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
OPENROUTER_API_KEY=...
COLI_API_KEY=local-secret
```

## Project structure

```text
clawflow/
├── api/
├── core/
│   ├── orchestration_graph.py
│   ├── runtime.py
│   ├── cli_controller.py
│   ├── routing_schema.py
│   ├── model_policy.py
│   └── graph.py
├── agents/
├── engine/
├── utils/
├── frontend/
├── docs/
├── tests/
├── main_graph.py
├── main.py
└── config.yaml
```

## Testing

```bash
pytest tests/test_routing_policy.py
pytest tests/test_orchestration_graph.py
pytest tests/test_graph_factory.py
pytest tests/test_graph_runtime_entrypoint.py
pytest tests/test_api_graph_adapter.py
pytest tests/test_native_hitl_resume.py
pytest tests/test_graph_cli_controller.py
```

필수 시나리오:

- cache hit 시 Router와 Worker가 호출되지 않음
- local 성공 시 외부 endpoint가 호출되지 않음
- Worker validation/Critic 실패 시 `nvidia-glm52`로 elevation
- local-only 요청이 외부 alias를 선택하지 않음
- high-risk 요청은 approval 없이 실행되지 않음
- API thread별 graph state가 격리됨
- HITL interrupt 이후 동일 thread에서 approve/reject/modify 재개
- planner가 dependency 순서로 shared graph를 호출함

## Current migration status

완료:

1. Structured routing contract
2. Provider-independent model policy
3. Shared LangGraph orchestration core
4. Semantic cache short-circuit
5. Native persisted HITL pause/resume
6. FastAPI shared graph adapter
7. Local execution과 NVIDIA GLM-5.2 quality elevation
8. Result persistence hook
9. Graph-native CLI command controller
10. LiteLLM role aliases와 회귀 테스트

남은 작업:

- PR stack CI 수정 및 순차 병합
- keyboard rewind/plan mode
- automatic context handoff
- MCP initialization
- dynamic cloud model shortcuts
- Redis halt를 각 graph node에 연결
- production secret/CORS/default-account 정리
- 실제 LiteLLM, NVIDIA, Ollama, PostgreSQL 통합 smoke test
