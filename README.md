# Clawflow: Hybrid AI Orchestration Framework (V5.4-dev)

**Clawflow**는 Apple Silicon 로컬 모델과 외부 LLM API를 하나의 정책 기반 실행 그래프로 연결하는 하이브리드 AI 오케스트레이션 프레임워크입니다.

현재 개발 브랜치는 기존 `LOCAL | CLOUD` 이진 라우팅을 구조화된 multi-tier 정책으로 확장하고, CLI/API/Web이 공유할 수 있는 dependency-injected LangGraph 실행 코어를 도입합니다.

> 현재 상태는 production-ready가 아니라 **production-oriented experimental runtime**입니다. 기존 `main.py`는 호환성을 위해 유지하며, 신규 개발은 `main_graph.py`와 `core/orchestration_graph.py`를 기준으로 진행합니다.

---

## 1. Agent handoff: 먼저 읽을 내용

다른 개발자나 AI agent가 작업을 이어받을 때는 다음 순서로 확인합니다.

1. `README.md` — 전체 구조, migration 경계, 다음 작업
2. `core/routing_schema.py` — Router와 runtime 사이의 계약
3. `core/model_policy.py` — routing decision을 LiteLLM alias로 변환하는 정책
4. `core/orchestration_graph.py` — 실제 공통 실행 상태 머신
5. `main_graph.py` — graph runtime에 기존 구성요소를 연결하는 CLI adapter
6. `config.yaml` — LiteLLM alias와 provider deployment
7. `tests/test_routing_policy.py`, `tests/test_orchestration_graph.py` — 기대 동작

### 작업 원칙

- 신규 오케스트레이션 로직을 `main.py`에 추가하지 않습니다.
- provider의 실제 모델명을 agent/runtime 코드에 직접 넣지 않습니다.
- Router는 모델명을 선택하지 않고 **작업 속성**을 반환합니다.
- 모델 선택과 fallback은 `ModelPolicy`와 LiteLLM 설정에서 처리합니다.
- 인프라 장애 fallback과 품질 실패 escalation을 구분합니다.
- CLI, FastAPI, Web은 동일한 compiled graph를 호출해야 합니다.
- 기존 legacy 기능을 제거하기 전 동일 기능의 graph adapter와 회귀 테스트를 먼저 만듭니다.

---

## 2. Architecture responsibility map

| 계층 | 책임 | 주요 파일 |
|---|---|---|
| Transport | CLI, API, Web 입력·출력과 사용자 세션 | `main_graph.py`, `main.py`, `api/` |
| Orchestration | 상태 전이, cache short-circuit, 승인, 실행, escalation, persist | `core/orchestration_graph.py` |
| Routing contract | 작업 유형, 실행 티어, 위험도, privacy, tool/HITL 요구사항 | `core/routing_schema.py` |
| Model policy | routing decision → 안정적인 LiteLLM alias | `core/model_policy.py` |
| Model gateway | provider 연결, timeout, retry, deployment fallback | `config.yaml`, LiteLLM |
| Agents | Router, Worker, Helper, Critic의 실제 추론 동작 | `agents/` |
| Execution safety | HITL, Docker sandbox, tmux verification | `engine/` |
| Persistence | history, cache, memory, checkpoint | `utils/`, `core/checkpoint.py` |

### 명확한 경계

**Clawflow가 담당하는 것**

- task classification
- sensitivity와 local-only 판정
- quality escalation
- tool/HITL 필요 여부
- agent state와 실행 흐름
- 결과 검증 및 persistence hook

**LiteLLM이 담당하는 것**

- provider timeout/retry
- 동일 alias 내 deployment 선택
- rate-limit 및 provider 장애 fallback
- API key, budget, 비용 관측
- OpenRouter, 직접 API, Ollama, MLX, OpenAI-compatible endpoint 통합

---

## 3. Runtime flow

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
    ├─ requires approval ──→ HITL gate ── reject ──→ Persist error
    │                              │ approve
    │                              ▼
    ├─ local_fast / local_quality / deep_local
    │          │
    │          ▼
    │      Local Worker
    │          │
    │          ├─ validation PASS ───────────────→ Persist
    │          └─ validation/critic/escalate FAIL
    │                                 │
    └─ cloud_general / cloud_specialist
                                      │
                                      ▼
                              Cloud execution
                                      │
                                      ▼
                                   Persist
```

이 흐름은 `core/orchestration_graph.py`에 구현되어 있습니다. Router, Worker, Cloud caller, Cache, approval checker, result hook은 `OrchestrationDependencies`를 통해 transport 계층에서 주입합니다.

### 현재 graph state

`OrchestrationState`의 주요 필드:

```text
request
context
routing
model_alias
cached_response
worker_result
final_response
escalation_reason
approved
error
```

state 필드를 추가할 때는 다음도 함께 수정합니다.

1. `OrchestrationState`
2. 관련 node 반환값
3. conditional edge
4. `result_hook` adapter
5. 회귀 테스트

---

## 4. Structured routing

Router의 신규 기본 인터페이스는 다음입니다.

```python
async def decide(user_message: str) -> RoutingDecision
```

기존 코드 호환을 위해 아래 인터페이스도 유지합니다.

```python
async def route(user_message: str) -> dict
```

`route()`는 legacy `destination`, `reason`, `thinking` 형식을 반환하고 내부적으로 structured decision을 사용합니다.

### RoutingDecision 주요 속성

```text
task_type
execution_tier
risk_level
requires_tools
requires_vision
requires_human_approval
local_only
latency_tolerance_seconds
reason
confidence
```

### 현재 execution tiers

```text
local_fast
local_quality
cloud_general
cloud_specialist
deep_local
```

`deep_local`은 Colibri GLM-5.2처럼 매우 느리지만 외부 전송 없이 고난도 추론이 필요한 endpoint를 위한 명시적 티어입니다. 일반 local fallback으로 자동 선택하지 않습니다.

---

## 5. Model aliases

애플리케이션은 실제 provider 모델명이 아니라 역할 alias만 사용합니다.

```text
local-router
local-fast
local-quality
local-helper
deep-local
cloud-general
cloud-coding
cloud-reasoning
cloud-long-context
cloud-specialist
```

현재 기본 매핑은 `config.yaml`에서 확인합니다.

- `local-fast`: 작은 로컬 모델
- `local-quality`: 주력 로컬 Worker
- `cloud-general`: 일반 클라우드 PM
- `cloud-coding`: 코딩 특화 클라우드 모델
- `cloud-reasoning`: 고난도 추론 모델
- `cloud-long-context`: 긴 문맥 모델
- `cloud-specialist`: 최종 specialist escalation
- `deep-local`: OpenAI-compatible 느린 로컬 추론 endpoint

새 provider를 추가할 때 agent 코드는 수정하지 않고 `config.yaml`의 동일 alias 아래 deployment를 추가합니다.

---

## 6. Entry points

### Graph-native CLI — 신규 개발 기준

```bash
python main_graph.py
```

이 진입점은 다음 구성요소를 shared graph에 연결합니다.

- `Router`
- `Worker`
- `HistoryManager`
- `SemanticCache`
- `CheckpointManager`
- `HITLManager`
- `EventBus`
- LiteLLM cloud caller

### Legacy full-feature CLI — migration source

```bash
python main.py
```

`main.py`에는 아직 다음 기능이 남아 있습니다.

- project switch
- planner와 task queue
- persona command
- debate command
- HITL resume commands
- sandbox/tmux lifecycle
- context handoff
- rollback/checkpoint CLI

이 기능을 수정해야 할 때는 먼저 `main_graph.py` 또는 별도 adapter로 이식한 뒤 legacy 구현을 제거합니다.

---

## 7. Quick start

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

로컬 모델 예시:

```bash
ollama pull deepseek-r1:8b
ollama pull qwen2.5-coder:32b
ollama pull phi4-mini
```

`deep-local`은 기본적으로 `http://localhost:8000/v1`의 OpenAI-compatible endpoint와 `local-secret` 키를 사용합니다. 다른 주소나 키를 사용할 경우 `config.yaml`을 변경합니다.

---

## 8. Environment and prerequisites

- macOS 또는 Linux
- Python 3.11+
- LiteLLM Proxy
- Ollama 또는 다른 OpenAI-compatible 로컬 endpoint
- Docker: 격리 실행 사용 시
- PostgreSQL: LangGraph 영속 checkpointer 사용 시
- Redis: 분산 event/cooldown/rate-limit 상태 사용 시

주요 환경 변수 예시:

```text
LITELLM_BASE_URL=http://localhost:4000
LITELLM_API_KEY=not-needed
GEMINI_API_KEY=...
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
OPENROUTER_API_KEY=...
COLI_API_KEY=local-secret
```

실제 사용 여부는 `config.yaml`과 adapter 구현을 기준으로 확인합니다.

---

## 9. Project structure

```text
clawflow/
├── api/                         # FastAPI transport and authentication
├── core/
│   ├── orchestration_graph.py   # Shared dependency-injected LangGraph runtime
│   ├── routing_schema.py        # Structured routing contract
│   ├── model_policy.py          # Routing decision → stable model alias
│   ├── graph.py                 # Graph factory and legacy checkpoint graph
│   ├── state.py                 # Legacy/persistent session state
│   └── observability.py         # Token and cost accounting
├── agents/
│   ├── router.py                # Rule-first + LLM structured router
│   ├── worker.py                # Tool-using Worker and quality escalation
│   ├── critic.py
│   └── helper.py
├── engine/                      # HITL, sandbox, persona, adversarial evaluation
├── utils/                       # Cache, memory, MCP, history, key management
├── frontend/                    # Next.js UI
├── tests/
├── main_graph.py                # Graph-native CLI entrypoint
├── main.py                      # Legacy full-feature CLI during migration
└── config.yaml                  # LiteLLM model aliases, fallback, MCP config
```

---

## 10. Testing

주요 회귀 테스트:

```bash
pytest tests/test_routing_policy.py
pytest tests/test_orchestration_graph.py
pytest tests/test_graph_factory.py
pytest tests/test_graph_runtime_entrypoint.py
```

전체 테스트:

```bash
pytest
```

필수 검증 시나리오:

- cache hit 시 Router와 Worker가 호출되지 않음
- local 성공 시 cloud가 호출되지 않음
- Worker validation/Critic 실패 시 cloud로 escalation
- local-only 요청이 cloud alias를 선택하지 않음
- high-risk 요청은 approval 없이 실행되지 않음
- cloud task type별 alias가 cloud caller까지 전달됨
- persistence hook이 handler, model alias, routing metadata를 기록함

---

## 11. Current migration status

### 완료

1. Structured routing contract
2. Provider-independent model policy
3. Shared LangGraph orchestration core
4. Semantic cache short-circuit
5. HITL approval gate
6. Local execution과 quality-based cloud escalation
7. Result persistence hook
8. Graph-native CLI entrypoint
9. LiteLLM role aliases와 기본 fallback
10. Routing/graph/entrypoint 회귀 테스트

### 다음 작업 — 우선순위 순

#### P0. FastAPI를 shared graph로 전환

- `api/server.py`가 독자 실행 로직을 가지지 않게 변경
- 앱 startup에서 graph를 한 번 compile
- 요청마다 `graph.ainvoke()` 호출
- user/session별 thread ID와 checkpointer 연결

#### P0. HITL pause/resume를 LangGraph native 방식으로 연결

- 현재 approval checker는 즉시 boolean adapter
- 향후 interrupt와 persisted checkpoint를 사용
- `/approve`, `/reject` 또는 API endpoint가 동일 graph thread를 재개해야 함

#### P1. Legacy CLI 기능 이식

- project/session switch
- planner와 task queue
- persona
- debate
- sandbox/tmux
- context handoff
- rollback/checkpoint

#### P1. Persistence 책임 정리

권장 책임:

```text
Postgres/LangGraph checkpoint = 실행 상태
Conversation store            = 원문 대화
Vector memory                 = 장기 의미 기억
Semantic cache                = 재사용 가능한 최종 응답
HANDOFF                        = 세션 이동용 압축 요약
```

#### P2. LiteLLM production policy

- 동일 alias의 직접 API + OpenRouter backup
- retry/cooldown
- tenant virtual key
- budget/rate limit
- provider별 timeout
- observability metadata 통일

---

## 12. Known limitations

- 전체 `main.py` 기능이 아직 graph-native CLI로 이식되지 않았습니다.
- shared graph에 PostgreSQL checkpointer가 기본 연결되어 있지 않습니다.
- HITL resume는 아직 완전한 durable interrupt 방식이 아닙니다.
- `deep-local` endpoint는 설치 여부에 따라 사용할 수 없을 수 있습니다.
- LiteLLM alias는 설정돼 있지만 실제 provider model availability와 API key는 환경에서 검증해야 합니다.
- repository 전체 테스트는 의존성이 설치된 로컬 또는 CI 환경에서 수행해야 합니다.

---

## 13. Do not do this

- `main.py`와 `main_graph.py`에 동일 orchestration 로직을 복제하지 않습니다.
- Router prompt에서 특정 provider 모델명을 직접 반환하지 않습니다.
- `LOCAL/CLOUD`만으로 신규 기능을 설계하지 않습니다.
- validation 실패와 provider timeout을 같은 fallback으로 처리하지 않습니다.
- 고위험 tool action을 approval 없이 자동 실행하지 않습니다.
- session별 설정을 global mutable variable로 저장하지 않습니다.
- README의 완료 상태를 실제 구현보다 과장하지 않습니다.

---

## License

MIT License
