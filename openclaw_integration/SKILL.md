---
name: AgenticFlow (M4 Optimized)
description: Mac Mini M4에서 구동되는 고성능 로컬 AI 에이전트. 심층 분석, 코드 리팩토링, 복잡한 계획 수립에 특화.
version: 2.0.0
author: luster92
transport: stdio
command: python
args: ["server.py"]
---

# AgenticFlow — M4 Optimized Agent

> Apple Silicon M4 전용 고성능 에이전트. MLX 기반 추론 + 투기적 디코딩으로
> 32B 모델을 로컬에서 30 TPS로 구동합니다.

## 💡 이 스킬을 사용할 때

| 트리거 키워드 | 설명 |
|:---|:---|
| 심층 분석 | 복잡한 주제에 대한 구조화된 분석 |
| 코드 리팩토링 | 전체 아키텍처 수준의 코드 개선 |
| 복잡한 계획 수립 | 다단계 프로젝트 계획 |
| 시스템 설계 | 아키텍처 설계/리뷰 |
| 보안 감사 | 코드 보안 분석 |

## ⚠️ 이 스킬을 사용하지 않을 때

- 단순 질문/답변 (예: "Python에서 리스트 정렬 방법")
- 간단한 번역/요약
- 일상적인 대화

## 🔧 사용 가능한 도구

### `run_flow`
에이전트 플로우를 실행합니다.

**Parameters:**
- `topic` (str, required): 작업 주제
- `mode` (str): research | code | plan | analyze
- `max_tokens` (int): 최대 생성 토큰 (기본 2048)

### `get_thought_trace`
에이전트의 사고 과정(Thinking Process)을 조회합니다.

**Parameters:**
- `session_id` (str, required): 세션 UUID
- `limit` (int): 최대 항목 수

### `get_status`
세션 상태를 조회합니다.

### `list_sessions`
활성 세션 목록을 반환합니다.

### `get_hardware_info`
하드웨어 정보 및 모델 추천을 확인합니다.

## 🧠 Thinking Process 시각화

이 도구를 사용할 때는 반드시 `thinking` 블록을 활용하여
현재 어떤 단계를 수행 중인지 실시간으로 표시하세요:

```
<thinking>
1. 문서 파싱 중... ✅
2. 코드 구조 분석 중... 🔄
3. 리팩토링 계획 생성 대기 중...
</thinking>
```

## 📊 리소스 사용

- **메모리**: ~22GB (모델 + KV Cache)
- **GPU**: 10-core M4 GPU 100% 활용
- **속도**: 25-30 tokens/sec (투기적 디코딩 시)

> [!WARNING]
> 실행 중 시스템 메모리가 부족할 수 있습니다.
> 다른 메모리 집약적 앱(Xcode, Docker 등)을 닫으세요.

## 🔗 결과물 관리

응답이 500자 이상일 경우:
1. 전체 내용을 파일로 저장 (`~/antigravity/output/`)
2. 대화창에는 요약본만 출력

## 📦 설치

```bash
cd ~/antigravity/agentic_flow
bash setup_m4.sh
```
