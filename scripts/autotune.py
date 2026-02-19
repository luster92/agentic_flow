#!/usr/bin/env python3
"""
AutoTune — 자가 적응형 하드웨어-모델 최적화 스킬
=====================================================
시스템 RAM을 진단하고, HuggingFace Hub에서 최신 MLX 호환 모델을
탐색하여 최적의 구성을 추천/적용합니다.

사용법:
    python scripts/autotune.py --mode check       # 현재 상태 + 추천 (변경 없음)
    python scripts/autotune.py --mode update      # 최적 모델로 설정 변경
    python scripts/autotune.py --type coder       # 코딩 특화 모델 우선 탐색
    python scripts/autotune.py --tier 32gb        # 특정 티어 강제
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-7s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("autotune")

# ── 상수 ──────────────────────────────────────────────────────
CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config"
)
SYSTEM_RESERVE_GB = 4.0  # OS + 런타임 예약 메모리

# RAM 티어별 모델 크기 상한 (GB 단위)
TIER_BUDGETS: dict[str, float] = {
    "16gb": 10.0,   # 모델 예산 10GB (16 - 4 OS - 2 여유)
    "32gb": 22.0,   # 모델 예산 22GB
    "64gb": 44.0,   # 모델 예산 44GB
    "128gb": 80.0,  # 모델 예산 80GB
}


# ── 데이터 클래스 ─────────────────────────────────────────────


@dataclass
class ModelCandidate:
    """HuggingFace에서 탐색된 모델 후보."""

    model_id: str
    size_est_gb: float
    downloads: int
    likes: int
    quantization: str = "4bit"


# ── 시스템 정보 수집 ──────────────────────────────────────────


def get_system_ram_gb() -> float:
    """총 물리적 RAM 용량을 GB 단위로 반환합니다."""
    try:
        import psutil  # type: ignore[import-untyped]
        mem = psutil.virtual_memory()
        return round(mem.total / (1024 ** 3), 1)
    except ImportError:
        # macOS fallback
        import subprocess
        try:
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True, text=True, timeout=5,
            )
            return round(int(result.stdout.strip()) / (1024 ** 3), 1)
        except Exception:
            return 0.0


def detect_ram_tier(ram_gb: float) -> str:
    """RAM 용량에 따른 티어 문자열을 반환합니다."""
    if ram_gb >= 128:
        return "128gb"
    elif ram_gb >= 64:
        return "64gb"
    elif ram_gb >= 32:
        return "32gb"
    else:
        return "16gb"


# ── 모델 크기 추정 ────────────────────────────────────────────

# 모델 이름에서 파라미터 수를 파싱하고 양자화 비트에 맞게 메모리 추정
PARAM_SIZE_MAP: list[tuple[str, float]] = [
    # (패턴, 4-bit 양자화 기준 GB)
    ("405B", 230.0),
    ("72B", 42.0),
    ("70B", 40.0),
    ("32B", 19.5),
    ("24B", 14.0),
    ("14B", 9.0),
    ("13B", 8.5),
    ("8B", 6.0),
    ("7B", 5.0),
    ("3B", 2.2),
    ("1.5B", 1.2),
    ("1B", 0.7),
    ("0.5B", 0.4),
]


def estimate_model_size_gb(model_name: str) -> float:
    """모델 이름에서 4-bit 기준 메모리 점유량(GB)을 추정합니다."""
    name_upper = model_name.upper()
    for pattern, size_gb in PARAM_SIZE_MAP:
        if pattern in name_upper:
            # 8-bit 모델은 2배
            if "8bit" in model_name.lower() or "8-bit" in model_name.lower():
                return size_gb * 2.0
            # 3-bit 모델은 0.75배
            if "3bit" in model_name.lower() or "3-bit" in model_name.lower():
                return size_gb * 0.75
            return size_gb
    return 0.0


# ── HuggingFace 모델 탐색 ─────────────────────────────────────


def find_best_models(
    max_model_gb: float,
    task_type: str = "instruct",
    limit: int = 50,
) -> list[ModelCandidate]:
    """HuggingFace에서 RAM 용량 내 구동 가능한 최신 MLX 모델을 검색합니다.

    Args:
        max_model_gb: 모델에 할당 가능한 최대 메모리 (GB)
        task_type: "instruct" 또는 "coder"
        limit: 검색 결과 수

    Returns:
        크기 → 다운로드 수 순으로 정렬된 최대 5개 후보 목록
    """
    try:
        from huggingface_hub import HfApi  # type: ignore[import-untyped]
    except ImportError:
        logger.error(
            "❌ huggingface_hub 패키지가 필요합니다: "
            "pip install huggingface_hub"
        )
        return []

    api = HfApi()
    candidates: list[ModelCandidate] = []

    try:
        models = api.list_models(
            search="mlx-community",
            sort="downloads",
            direction=-1,
            limit=limit,
        )
    except Exception as e:
        logger.error(f"❌ HuggingFace API 호출 실패: {e}")
        return []

    for m in models:
        name = m.modelId or ""

        # 양자화 필터: 4bit 또는 8bit만
        is_4bit = "4bit" in name.lower()
        is_8bit = "8bit" in name.lower()
        if not (is_4bit or is_8bit):
            continue

        # Instruct 모델 필터
        if "instruct" not in name.lower() and task_type == "instruct":
            continue

        # Coder 필터
        if task_type == "coder" and "coder" not in name.lower():
            continue

        size_gb = estimate_model_size_gb(name)
        if size_gb <= 0:
            continue

        # 가용 메모리 범위 내 필터
        if size_gb > max_model_gb:
            continue

        quant = "8bit" if is_8bit else "4bit"
        candidates.append(ModelCandidate(
            model_id=name,
            size_est_gb=size_gb,
            downloads=m.downloads or 0,
            likes=m.likes or 0,
            quantization=quant,
        ))

    # 크기(지능) 우선, 동일 크기면 다운로드 수 순
    candidates.sort(
        key=lambda x: (x.size_est_gb, x.downloads), reverse=True
    )
    return candidates[:5]


# ── 구성 업데이트 ─────────────────────────────────────────────


def get_current_config(tier: str) -> Optional[dict[str, object]]:
    """현재 티어의 YAML 설정을 읽습니다."""
    import yaml

    profile_name = f"m4_{tier}"
    config_path = os.path.join(CONFIG_DIR, f"{profile_name}.yaml")
    if not os.path.exists(config_path):
        return None
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"❌ 설정 로드 실패: {e}")
        return None


def update_config(tier: str, model_id: str) -> bool:
    """하드웨어 프로파일 YAML에서 main_model을 업데이트합니다."""
    import yaml

    profile_name = f"m4_{tier}"
    config_path = os.path.join(CONFIG_DIR, f"{profile_name}.yaml")

    if not os.path.exists(config_path):
        logger.error(f"❌ 프로파일 파일 없음: {config_path}")
        return False

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()

        data = yaml.safe_load(content) or {}
        current_model = data.get("mlx", {}).get("main_model", "")

        if current_model == model_id:
            logger.info(f"✅ 이미 최적 모델({model_id})을 사용 중입니다.")
            return True

        # main_model 값만 교체 (YAML 포맷 유지)
        new_content = content.replace(
            f'main_model: "{current_model}"',
            f'main_model: "{model_id}"',
        )

        with open(config_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        logger.info(
            f"✅ 설정 업데이트 완료: {current_model} → {model_id}"
        )
        return True

    except Exception as e:
        logger.error(f"❌ 설정 업데이트 실패: {e}")
        return False


# ── 메인 ──────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AgenticFlow 자가 적응형 모델 최적화 스킬",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "예시:\n"
            "  python scripts/autotune.py --mode check\n"
            "  python scripts/autotune.py --mode update --type coder\n"
            "  python scripts/autotune.py --tier 64gb --mode check\n"
        ),
    )
    parser.add_argument(
        "--mode",
        choices=["check", "update"],
        default="check",
        help="check: 현재 상태 + 추천 / update: 설정 자동 변경",
    )
    parser.add_argument(
        "--type",
        choices=["instruct", "coder"],
        default="instruct",
        help="탐색할 모델 유형 (기본: instruct)",
    )
    parser.add_argument(
        "--tier",
        choices=["16gb", "32gb", "64gb", "128gb"],
        default=None,
        help="특정 RAM 티어 강제 (미지정 시 자동 감지)",
    )
    args = parser.parse_args()

    # ── 1. 시스템 자원 성찰 (Introspect) ──────────────────
    total_ram = get_system_ram_gb()
    tier = args.tier or detect_ram_tier(total_ram)
    model_budget = TIER_BUDGETS.get(tier, 10.0)

    print(f"\n{'=' * 60}")
    print(f"  🔍 System Auto-Tune Report")
    print(f"{'=' * 60}")
    print(f"  시스템 RAM   : {total_ram:.1f} GB")
    print(f"  감지된 티어  : {tier}")
    print(f"  모델 예산    : {model_budget:.1f} GB")

    # 현재 설정 표시
    current = get_current_config(tier)
    if current:
        mlx_cfg = current.get("mlx", {})
        print(f"  현재 모델    : {mlx_cfg.get('main_model', 'N/A')}")
        print(f"  드래프트     : {mlx_cfg.get('draft_model', 'N/A')}")
        print(
            f"  투기적 디코딩: "
            f"{'✅' if mlx_cfg.get('speculative_decoding') else '❌'}"
        )
        print(f"  컨텍스트     : {mlx_cfg.get('max_context_length', 'N/A')}")

    # ── 2. 모델 탐색 (Scout) ──────────────────────────────
    print(f"\n  📡 HuggingFace에서 MLX 모델 탐색 중...")
    print(f"     (필터: {args.type}, 최대 {model_budget:.0f}GB)")

    candidates = find_best_models(model_budget, args.type)

    if not candidates:
        print("  ⚠️ 조건에 맞는 모델을 찾을 수 없습니다.")
        print(f"{'=' * 60}\n")
        return

    # ── 3. 평가 결과 표시 (Evaluate) ──────────────────────
    print(f"\n  🏆 추천 모델 (상위 5개):")
    print(f"  {'─' * 56}")
    for i, c in enumerate(candidates):
        marker = " 👈 최적" if i == 0 else ""
        print(
            f"  {i + 1}. {c.model_id}\n"
            f"     메모리: ~{c.size_est_gb:.1f}GB ({c.quantization}) | "
            f"다운로드: {c.downloads:,} | "
            f"좋아요: {c.likes:,}{marker}"
        )

    # ── 4. 적응 (Adapt) ──────────────────────────────────
    if args.mode == "update" and candidates:
        best = candidates[0]
        print(f"\n  🔧 최적 모델 자동 적용 중: {best.model_id}")
        success = update_config(tier, best.model_id)
        if success:
            print("  ✅ 구성 업데이트 완료!")
            print("  ℹ️  변경 사항 적용을 위해 서버를 재시작하세요.")
        else:
            print("  ❌ 구성 업데이트에 실패했습니다.")
    elif args.mode == "check":
        print(f"\n  ℹ️  적용하려면 --mode update 옵션을 사용하세요.")

    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
