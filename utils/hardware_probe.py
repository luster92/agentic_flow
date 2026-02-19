"""
HardwareProbe — Apple Silicon 하드웨어 감지 및 자원 관리
=======================================================
M4 Mac Mini의 하드웨어 상태를 실시간으로 모니터링하고,
모델 설정을 동적으로 조정합니다.

기능:
- Apple Silicon 칩 모델 감지 (M4/M4 Pro/M4 Max)
- 메모리 압박 수준 모니터링 (psutil + vm_stat)
- GPU 코어 수 감지
- 가용 메모리 기반 모델/양자화 추천
- QoS 수준 설정 (P-core 할당 권고)
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# ── psutil import guard ───────────────────────────────────────
_PSUTIL_AVAILABLE = False
try:
    import psutil  # type: ignore[import-untyped]
    _PSUTIL_AVAILABLE = True
except ImportError:
    logger.debug("psutil not available, limited monitoring")


# ── Enums ─────────────────────────────────────────────────────

class ChipFamily(str, Enum):
    """Apple Silicon 칩 계열."""
    M4 = "m4"
    M4_PRO = "m4_pro"
    M4_MAX = "m4_max"
    M3 = "m3"
    M2 = "m2"
    M1 = "m1"
    UNKNOWN = "unknown"
    NON_APPLE = "non_apple"


class MemoryPressure(str, Enum):
    """메모리 압박 수준."""
    NOMINAL = "nominal"       # 여유 상태
    WARN = "warn"             # 경고 (적극적 캐시 정리)
    CRITICAL = "critical"     # 임계 (모델 전환 필요)


class ModelRecommendation(str, Enum):
    """추천 모델 크기."""
    LARGE_32B = "32b"
    MEDIUM_14B = "14b"
    SMALL_7B = "7b"
    TINY_3B = "3b"


# ── Data Classes ──────────────────────────────────────────────

@dataclass
class ChipInfo:
    """칩 정보."""
    family: ChipFamily = ChipFamily.UNKNOWN
    brand_string: str = ""
    cpu_cores: int = 0
    p_cores: int = 0
    e_cores: int = 0
    gpu_cores: int = 0


@dataclass
class MemoryInfo:
    """메모리 정보."""
    total_gb: float = 0.0
    available_gb: float = 0.0
    used_gb: float = 0.0
    wired_gb: float = 0.0
    pressure: MemoryPressure = MemoryPressure.NOMINAL
    swap_used_gb: float = 0.0


@dataclass
class ModelConfig:
    """추천 모델 설정."""
    recommendation: ModelRecommendation = ModelRecommendation.LARGE_32B
    main_model: str = "mlx-community/Qwen2.5-32B-Instruct-4bit"
    draft_model: str = "mlx-community/Qwen2.5-0.5B-Instruct-4bit"
    quantization_bits: int = 4
    kv_cache_bits: int = 4
    max_context_length: int = 8192
    speculative_decoding: bool = True
    reason: str = ""


# ── Hardware Probe ────────────────────────────────────────────

class HardwareProbe:
    """Apple Silicon 하드웨어 감지 및 자원 관리자.

    시스템 정보를 수집하고, 현재 리소스 상태에 따라
    최적의 모델 설정을 추천합니다.
    """

    # M4 칩 계열별 표준 코어 구성
    CHIP_PROFILES: dict[str, dict[str, int]] = {
        "m4": {"p_cores": 4, "e_cores": 6, "gpu_cores": 10},
        "m4 pro": {"p_cores": 10, "e_cores": 4, "gpu_cores": 16},
        "m4 max": {"p_cores": 12, "e_cores": 4, "gpu_cores": 40},
        "m3": {"p_cores": 4, "e_cores": 4, "gpu_cores": 10},
        "m2": {"p_cores": 4, "e_cores": 4, "gpu_cores": 10},
        "m1": {"p_cores": 4, "e_cores": 4, "gpu_cores": 8},
    }

    def __init__(self) -> None:
        self._chip_info: ChipInfo | None = None
        self._is_apple_silicon: bool | None = None

    # ── 칩 감지 ───────────────────────────────────────────

    def detect_chip(self) -> ChipInfo:
        """Apple Silicon 칩 정보를 감지합니다.

        Returns:
            ChipInfo 데이터 객체
        """
        if self._chip_info is not None:
            return self._chip_info

        info = ChipInfo()

        # macOS가 아니면 non_apple
        if platform.system() != "Darwin":
            info.family = ChipFamily.NON_APPLE
            self._chip_info = info
            return info

        # ARM64 확인
        if platform.machine() != "arm64":
            info.family = ChipFamily.NON_APPLE
            self._chip_info = info
            return info

        # 칩 브랜드 문자열 가져오기
        try:
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True, timeout=5,
            )
            brand = result.stdout.strip().lower()
            info.brand_string = result.stdout.strip()
        except Exception:
            brand = ""

        # CPU 코어 수
        try:
            result = subprocess.run(
                ["sysctl", "-n", "hw.ncpu"],
                capture_output=True, text=True, timeout=5,
            )
            info.cpu_cores = int(result.stdout.strip())
        except Exception:
            info.cpu_cores = os.cpu_count() or 1

        # 칩 계열 판별
        family_map = {
            "m4 max": ChipFamily.M4_MAX,
            "m4 pro": ChipFamily.M4_PRO,
            "m4": ChipFamily.M4,
            "m3": ChipFamily.M3,
            "m2": ChipFamily.M2,
            "m1": ChipFamily.M1,
        }
        info.family = ChipFamily.UNKNOWN
        for key, fam in family_map.items():
            if key in brand:
                info.family = fam
                break

        # 코어 프로파일 적용
        for key, profile in self.CHIP_PROFILES.items():
            if key in brand:
                info.p_cores = profile["p_cores"]
                info.e_cores = profile["e_cores"]
                info.gpu_cores = profile["gpu_cores"]
                break

        if info.p_cores == 0:
            # 기본값 추정
            info.p_cores = max(1, info.cpu_cores // 2)
            info.e_cores = info.cpu_cores - info.p_cores

        self._chip_info = info
        self._is_apple_silicon = info.family != ChipFamily.NON_APPLE
        logger.info(
            f"🔍 Detected: {info.brand_string} "
            f"(P:{info.p_cores} E:{info.e_cores} GPU:{info.gpu_cores})"
        )
        return info

    # ── 메모리 정보 ───────────────────────────────────────

    def get_memory_info(self) -> MemoryInfo:
        """현재 메모리 상태를 조회합니다.

        Returns:
            MemoryInfo 데이터 객체
        """
        mem = MemoryInfo()

        if _PSUTIL_AVAILABLE:
            vm = psutil.virtual_memory()
            mem.total_gb = round(vm.total / (1024 ** 3), 1)
            mem.available_gb = round(vm.available / (1024 ** 3), 1)
            mem.used_gb = round(vm.used / (1024 ** 3), 1)

            swap = psutil.swap_memory()
            mem.swap_used_gb = round(swap.used / (1024 ** 3), 1)
        else:
            # macOS fallback: sysctl
            try:
                result = subprocess.run(
                    ["sysctl", "-n", "hw.memsize"],
                    capture_output=True, text=True, timeout=5,
                )
                mem.total_gb = round(
                    int(result.stdout.strip()) / (1024 ** 3), 1
                )
            except Exception:
                pass

        # macOS vm_stat으로 wired memory 조회
        if platform.system() == "Darwin":
            try:
                result = subprocess.run(
                    ["vm_stat"],
                    capture_output=True, text=True, timeout=5,
                )
                lines = result.stdout.strip().split("\n")
                page_size = 16384  # M4 default
                # 첫 줄에서 page size 파싱
                if "page size of" in lines[0]:
                    parts = lines[0].split("page size of")
                    page_size = int(
                        parts[1].strip().rstrip(" bytes").strip()
                    )

                wired = 0
                for line in lines:
                    if "wired" in line.lower():
                        parts = line.split(":")
                        if len(parts) == 2:
                            pages = int(
                                parts[1].strip().rstrip(".")
                            )
                            wired = pages * page_size
                            break

                mem.wired_gb = round(wired / (1024 ** 3), 1)
            except Exception:
                pass

        # 압박 수준 판별
        if mem.available_gb < 2.0:
            mem.pressure = MemoryPressure.CRITICAL
        elif mem.available_gb < 4.0:
            mem.pressure = MemoryPressure.WARN
        else:
            mem.pressure = MemoryPressure.NOMINAL

        return mem

    # ── 모델 추천 ─────────────────────────────────────────

    def recommend_model_config(self) -> ModelConfig:
        """현재 하드웨어 상태에 맞는 최적 모델 설정을 추천합니다.

        Returns:
            ModelConfig 추천 설정
        """
        chip = self.detect_chip()
        mem = self.get_memory_info()

        # 비-Apple Silicon
        if chip.family == ChipFamily.NON_APPLE:
            return ModelConfig(
                recommendation=ModelRecommendation.SMALL_7B,
                main_model="local-worker",
                draft_model="",
                quantization_bits=4,
                speculative_decoding=False,
                reason="Non-Apple Silicon: using LiteLLM proxy",
            )

        # 메모리 기반 추천
        available = mem.total_gb

        if available >= 64:
            return ModelConfig(
                recommendation=ModelRecommendation.LARGE_32B,
                main_model="mlx-community/Qwen2.5-32B-Instruct-4bit",
                draft_model="mlx-community/Qwen2.5-0.5B-Instruct-4bit",
                quantization_bits=4,
                kv_cache_bits=8,
                max_context_length=16384,
                speculative_decoding=True,
                reason=f"64GB+ RAM: Full 32B with 8-bit KV cache",
            )
        elif available >= 32:
            return ModelConfig(
                recommendation=ModelRecommendation.LARGE_32B,
                main_model="mlx-community/Qwen2.5-32B-Instruct-4bit",
                draft_model="mlx-community/Qwen2.5-0.5B-Instruct-4bit",
                quantization_bits=4,
                kv_cache_bits=4,
                max_context_length=8192,
                speculative_decoding=True,
                reason=f"32GB RAM: 32B with 4-bit KV cache (tight fit)",
            )
        elif available >= 16:
            return ModelConfig(
                recommendation=ModelRecommendation.MEDIUM_14B,
                main_model="mlx-community/Qwen2.5-14B-Instruct-4bit",
                draft_model="mlx-community/Qwen2.5-0.5B-Instruct-4bit",
                quantization_bits=4,
                kv_cache_bits=4,
                max_context_length=8192,
                speculative_decoding=True,
                reason=f"16GB RAM: 14B model recommended",
            )
        else:
            return ModelConfig(
                recommendation=ModelRecommendation.SMALL_7B,
                main_model="mlx-community/Qwen2.5-7B-Instruct-4bit",
                draft_model="",
                quantization_bits=4,
                kv_cache_bits=4,
                max_context_length=4096,
                speculative_decoding=False,
                reason=f"<16GB RAM: 7B model, no speculative decoding",
            )

    # ── 메모리 압박 체크 ──────────────────────────────────

    def check_memory_pressure(self) -> MemoryPressure:
        """실시간 메모리 압박 수준을 확인합니다.

        Returns:
            MemoryPressure 수준
        """
        return self.get_memory_info().pressure

    def should_fallback(self) -> bool:
        """경량 모델로 전환해야 하는지 확인합니다.

        가용 메모리가 4GB 미만이면 True.

        Returns:
            True if fallback needed
        """
        mem = self.get_memory_info()
        if mem.pressure == MemoryPressure.CRITICAL:
            logger.warning(
                f"⚠️ Memory pressure CRITICAL: "
                f"{mem.available_gb:.1f}GB available"
            )
            return True
        return False

    # ── 시스템 정보 요약 ──────────────────────────────────

    @property
    def is_apple_silicon(self) -> bool:
        """Apple Silicon 여부."""
        if self._is_apple_silicon is None:
            self.detect_chip()
        return self._is_apple_silicon or False

    def get_summary(self) -> dict[str, Any]:
        """전체 하드웨어 정보 요약."""
        chip = self.detect_chip()
        mem = self.get_memory_info()
        rec = self.recommend_model_config()

        return {
            "chip": {
                "family": chip.family.value,
                "brand": chip.brand_string,
                "cpu_cores": chip.cpu_cores,
                "p_cores": chip.p_cores,
                "e_cores": chip.e_cores,
                "gpu_cores": chip.gpu_cores,
            },
            "memory": {
                "total_gb": mem.total_gb,
                "available_gb": mem.available_gb,
                "wired_gb": mem.wired_gb,
                "pressure": mem.pressure.value,
                "swap_used_gb": mem.swap_used_gb,
            },
            "recommendation": {
                "model_size": rec.recommendation.value,
                "main_model": rec.main_model,
                "draft_model": rec.draft_model,
                "speculative_decoding": rec.speculative_decoding,
                "reason": rec.reason,
            },
        }
