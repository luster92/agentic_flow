# Latest Syntax Reference (Golden Snippet)
> 이 문서는 Worker(LLM)가 코드를 작성할 때 **최우선순위**로 참조해야 하는 최신 API 문법입니다.
> Worker의 학습 데이터보다 이 문서의 규칙이 항상 우선합니다.

---

## OpenAI Python SDK (v1.0+ / 2024~2026)

### ❌ Old (v0.x — 사용 금지)
```python
import openai
openai.api_key = "sk-..."
response = openai.ChatCompletion.create(
    model="gpt-4",
    messages=[{"role": "user", "content": "Hello"}]
)
print(response["choices"][0]["message"]["content"])
```

### ✅ New (v1.0+ — 반드시 이 방식 사용)
```python
from openai import OpenAI

client = OpenAI(api_key="sk-...", base_url="http://localhost:4000")
response = client.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": "Hello"}]
)
print(response.choices[0].message.content)
```

**핵심 변경:**
- `openai.ChatCompletion.create()` → `client.chat.completions.create()`
- `response["choices"][0]` (dict) → `response.choices[0]` (object)
- `openai.api_key = ...` → `OpenAI(api_key=...)`

---

## Pydantic (v2 / 2024~2026)

### ❌ Old (v1 — 사용 금지)
```python
from pydantic import BaseModel, validator

class User(BaseModel):
    name: str

    class Config:
        orm_mode = True

    @validator("name")
    def validate_name(cls, v):
        return v.strip()
```

### ✅ New (v2 — 반드시 이 방식 사용)
```python
from pydantic import BaseModel, field_validator, ConfigDict

class User(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        return v.strip()
```

**핵심 변경:**
- `class Config:` → `model_config = ConfigDict(...)`
- `orm_mode` → `from_attributes`
- `@validator` → `@field_validator` + `@classmethod`
- `.dict()` → `.model_dump()`
- `.json()` → `.model_dump_json()`

---

## LangChain (v0.2+ / 2024~2026)

### ❌ Old
```python
from langchain.llms import OpenAI
from langchain.chains import LLMChain
```

### ✅ New
```python
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
```

**핵심 변경:**
- `langchain.llms` → `langchain_openai`
- `LLMChain` → LCEL (`prompt | llm | parser`)

---

## LiteLLM (v1.50+ / 2025~2026)

### ✅ Current Usage
```python
import litellm

# 프록시 모드: OpenAI SDK로 LiteLLM 프록시에 연결
from openai import OpenAI
client = OpenAI(base_url="http://localhost:4000", api_key="not-needed")

# 직접 호출 모드
response = litellm.completion(
    model="ollama/qwen2.5-coder:32b",
    messages=[{"role": "user", "content": "Hello"}],
    api_base="http://localhost:11434"
)
```

---

## Python 표준 (3.10+)

### 타입 힌팅
```python
# ❌ Old
from typing import Optional, List, Dict, Union
def foo(x: Optional[str]) -> List[Dict[str, Any]]: ...

# ✅ New (3.10+)
def foo(x: str | None) -> list[dict[str, Any]]: ...
```

### Match Statement (3.10+)
```python
match command:
    case "quit":
        sys.exit()
    case "hello":
        print("Hello!")
    case _:
        print("Unknown")
```

<!-- AUTO-GENERATED: Learning Loop -->
### 🔴 오답 노트 (test_pkg) — 2026-02-18 16:03

**에러:** `Line 5: expected indentation`

❌ 잘못된 코드:
```python
def bad():
return 42
```

✅ 수정된 코드:
```python
def good():
    return 42
```

---

<!-- AUTO-GENERATED: Learning Loop -->
### 🔴 오답 노트 (test_pkg) — 2026-02-18 16:04

**에러:** `Line 5: expected indentation`

❌ 잘못된 코드:
```python
def bad():
return 42
```

✅ 수정된 코드:
```python
def good():
    return 42
```

---

<!-- AUTO-GENERATED: Learning Loop -->
## openai v2.21.0 (Auto-scanned)

### 주요 클래스
- `APIConnectionError` — methods: `add_note, with_traceback`
- `APIError` — methods: `add_note, with_traceback`
- `APIResponse` — methods: `close, iter_bytes, iter_lines, iter_text, json`
- `APIResponseValidationError` — methods: `add_note, with_traceback`
- `APIStatusError` — methods: `add_note, with_traceback`
- `APITimeoutError` — methods: `add_note, with_traceback`
- `AssistantEventHandler` — methods: `close, get_final_messages, get_final_run, get_final_run_steps, on_end`
- `AsyncAPIResponse` — methods: `close, iter_bytes, iter_lines, iter_text, json`

### 주요 함수
- `file_from_path(path: 'str') -> 'FileTypes'`
- `override(method: F, /) -> F`
- `pydantic_function_tool(model: 'type[pydantic.BaseModel]', *, name: 'str | None' = None, description: 'str | None' = None) -> 'ChatCompletionFunctionToolParam'`
> Auto-generated on 2026-02-18 16:04

---
