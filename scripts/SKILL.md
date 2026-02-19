---
name: system-autotune
description: 가용 RAM과 최신 MLX 모델 트렌드를 분석하여 에이전트 구성을 최적화합니다.
version: 1.0.0
author: luster92
permissions:
  read: ["config/*.yaml"]
  write: ["config/*.yaml"]
  exec: ["python3"]
  net: ["huggingface.co"]
---

# System Auto-Tune Skill

> 시스템 하드웨어를 자동 진단하고, HuggingFace Hub에서 최신 MLX 모델을
> 탐색하여 에이전트 구성을 최적화합니다.

## 💡 이 스킬을 사용할 때

| 트리거 키워드 | 설명 |
|:---|:---|
| 성능 최적화 | 현재 설정의 성능 진단 및 개선 |
| 최신 모델 확인 | HuggingFace에서 새 MLX 모델 탐색 |
| 모델 업그레이드 | 더 좋은 모델로 자동 전환 |
| 시스템 진단 | 하드웨어 리소스 상태 확인 |

## ⚠️ 이 스킬을 사용하지 않을 때

- 수동으로 특정 모델을 지정하고 싶을 때 → `config/m4_*.yaml` 직접 편집
- 클라우드 모델 관련 설정 변경

## 🔧 사용법

```bash
# 현재 상태 감지 + 추천 (변경 없음)
python scripts/autotune.py --mode check

# 최적 모델로 설정 자동 변경
python scripts/autotune.py --mode update

# 코딩 특화 모델 탐색
python scripts/autotune.py --mode check --type coder

# 특정 RAM 티어 강제 적용
python scripts/autotune.py --tier 64gb --mode update
```

## 🔄 자동 실행 (Cron)

OpenClaw에서 주기적 자동 실행 설정:

```
"매주 월요일 오전 9시에 system-autotune 스킬을 check 모드로 실행하고,
 새로운 모델이 발견되면 나에게 보고해 줘."
```

## 📊 출력 예시

```
============================================================
  🔍 System Auto-Tune Report
============================================================
  시스템 RAM   : 32.0 GB
  감지된 티어  : 32gb
  모델 예산    : 22.0 GB
  현재 모델    : mlx-community/Qwen2.5-32B-Instruct-4bit

  🏆 추천 모델 (상위 5개):
  ────────────────────────────────────────────────────────
  1. mlx-community/Qwen2.5-32B-Instruct-4bit
     메모리: ~19.5GB (4bit) | 다운로드: 12,345 | 좋아요: 89 👈 최적
============================================================
```

## ⚙️ 의존성

- `psutil` — 시스템 메모리 감지
- `huggingface_hub` — 모델 탐색 API
- `pyyaml` — 설정 파일 처리
