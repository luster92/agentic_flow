"""
Tests for RAM Tier Configurations (16GB / 32GB / 64GB / 128GB)
==============================================================
하드웨어 프로파일 YAML 로딩, 동적 티어 선택, autotune 로직을 검증합니다.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

# ── Profile YAML Tests ────────────────────────────────────────

CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config"
)

EXPECTED_PROFILES = ["m4_16gb", "m4_32gb", "m4_64gb", "m4_128gb"]


class TestProfileYAML:
    """하드웨어 프로파일 YAML 파일 검증."""

    @pytest.mark.parametrize("profile", EXPECTED_PROFILES)
    def test_profile_exists(self, profile: str) -> None:
        """각 프로파일 YAML 파일이 존재해야 합니다."""
        path = os.path.join(CONFIG_DIR, f"{profile}.yaml")
        assert os.path.exists(path), f"{profile}.yaml not found"

    @pytest.mark.parametrize("profile", EXPECTED_PROFILES)
    def test_profile_valid_yaml(self, profile: str) -> None:
        """각 프로파일이 유효한 YAML이어야 합니다."""
        path = os.path.join(CONFIG_DIR, f"{profile}.yaml")
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)

    @pytest.mark.parametrize("profile", EXPECTED_PROFILES)
    def test_profile_has_required_sections(self, profile: str) -> None:
        """필수 섹션(hardware, mlx, memory_limits, fallback, qos)이 존재해야 합니다."""
        path = os.path.join(CONFIG_DIR, f"{profile}.yaml")
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        for section in ["hardware", "mlx", "memory_limits", "fallback", "qos"]:
            assert section in data, f"Section '{section}' missing in {profile}"

    @pytest.mark.parametrize("profile", EXPECTED_PROFILES)
    def test_mlx_section_fields(self, profile: str) -> None:
        """mlx 섹션에 main_model, max_context_length, temperature가 있어야 합니다."""
        path = os.path.join(CONFIG_DIR, f"{profile}.yaml")
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        mlx = data["mlx"]
        assert "main_model" in mlx
        assert "max_context_length" in mlx
        assert "temperature" in mlx
        assert isinstance(mlx["max_context_length"], int)
        assert mlx["max_context_length"] > 0

    def test_16gb_profile_no_speculative(self) -> None:
        """16GB 프로파일은 투기적 디코딩이 비활성화되어야 합니다."""
        path = os.path.join(CONFIG_DIR, "m4_16gb.yaml")
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data["mlx"]["speculative_decoding"] is False
        assert data["mlx"]["draft_model"] == ""

    def test_64gb_profile_speculative_enabled(self) -> None:
        """64GB 프로파일은 투기적 디코딩이 활성화되어야 합니다."""
        path = os.path.join(CONFIG_DIR, "m4_64gb.yaml")
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data["mlx"]["speculative_decoding"] is True
        assert "70B" in data["mlx"]["main_model"]

    def test_128gb_profile_high_precision(self) -> None:
        """128GB 프로파일은 8-bit 모델을 사용해야 합니다."""
        path = os.path.join(CONFIG_DIR, "m4_128gb.yaml")
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert "8bit" in data["mlx"]["main_model"]
        assert data["mlx"]["kv_cache_bits"] == 8
        assert data["mlx"]["max_context_length"] >= 131072

    def test_128gb_has_rag_section(self) -> None:
        """128GB 프로파일에 RAG 설정이 있어야 합니다."""
        path = os.path.join(CONFIG_DIR, "m4_128gb.yaml")
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert "rag" in data
        assert data["rag"]["enabled"] is True

    def test_context_window_ordering(self) -> None:
        """컨텍스트 윈도우는 RAM이 클수록 커야 합니다."""
        contexts: dict[str, int] = {}
        for profile in EXPECTED_PROFILES:
            path = os.path.join(CONFIG_DIR, f"{profile}.yaml")
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            contexts[profile] = data["mlx"]["max_context_length"]

        assert contexts["m4_16gb"] <= contexts["m4_32gb"]
        assert contexts["m4_32gb"] <= contexts["m4_64gb"]
        assert contexts["m4_64gb"] <= contexts["m4_128gb"]

    def test_memory_budget_ordering(self) -> None:
        """모델 예산은 RAM이 클수록 커야 합니다."""
        budgets: dict[str, float] = {}
        for profile in EXPECTED_PROFILES:
            path = os.path.join(CONFIG_DIR, f"{profile}.yaml")
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            budgets[profile] = data["memory_limits"]["model_budget_gb"]

        assert budgets["m4_16gb"] < budgets["m4_32gb"]
        assert budgets["m4_32gb"] < budgets["m4_64gb"]
        assert budgets["m4_64gb"] < budgets["m4_128gb"]


# ── HardwareProbe Tests ───────────────────────────────────────

from utils.hardware_probe import (
    HardwareProbe,
    ChipFamily,
    ModelRecommendation,
    ModelConfig,
    MemoryInfo,
    MemoryPressure,
)


class TestHardwareProbeRamTiers:
    """HardwareProbe RAM 티어별 추천 검증."""

    def test_model_recommendation_enum_has_new_tiers(self) -> None:
        """ModelRecommendation에 XLARGE_70B와 ULTRA_72B가 있어야 합니다."""
        values = {e.value for e in ModelRecommendation}
        assert "70b" in values
        assert "72b_8bit" in values
        # 기존 값도 유지
        assert "32b" in values
        assert "14b" in values
        assert "7b" in values
        assert "3b" in values

    def test_chip_family_has_ultra(self) -> None:
        """ChipFamily에 M4_ULTRA가 있어야 합니다."""
        assert hasattr(ChipFamily, "M4_ULTRA")
        assert ChipFamily.M4_ULTRA.value == "m4_ultra"

    def _make_probe_with_ram(self, ram_gb: float) -> HardwareProbe:
        """특정 RAM으로 mocked된 HardwareProbe를 생성합니다."""
        probe = HardwareProbe()
        # detect_chip도 mock해서 Apple Silicon으로 설정
        probe._chip_info = MagicMock()
        probe._chip_info.family = ChipFamily.M4
        return probe

    @pytest.mark.parametrize(
        "ram_gb,expected_rec",
        [
            (8.0, ModelRecommendation.SMALL_7B),
            (16.0, ModelRecommendation.MEDIUM_14B),
            (32.0, ModelRecommendation.LARGE_32B),
            (64.0, ModelRecommendation.XLARGE_70B),
            (128.0, ModelRecommendation.ULTRA_72B),
        ],
    )
    def test_recommend_by_ram(
        self, ram_gb: float, expected_rec: ModelRecommendation
    ) -> None:
        """RAM 크기별 올바른 모델 추천."""
        probe = self._make_probe_with_ram(ram_gb)
        with patch.object(
            probe, "get_memory_info",
            return_value=MemoryInfo(
                total_gb=ram_gb,
                available_gb=ram_gb * 0.7,
                pressure=MemoryPressure.NOMINAL,
            ),
        ):
            config = probe.recommend_model_config()
            assert config.recommendation == expected_rec

    def test_128gb_recommends_8bit(self) -> None:
        """128GB는 8-bit 양자화를 추천해야 합니다."""
        probe = self._make_probe_with_ram(128.0)
        with patch.object(
            probe, "get_memory_info",
            return_value=MemoryInfo(
                total_gb=128.0,
                available_gb=100.0,
                pressure=MemoryPressure.NOMINAL,
            ),
        ):
            config = probe.recommend_model_config()
            assert config.quantization_bits == 8
            assert config.kv_cache_bits == 8
            assert config.max_context_length == 131072

    def test_64gb_recommends_speculative(self) -> None:
        """64GB는 투기적 디코딩이 활성화되어야 합니다."""
        probe = self._make_probe_with_ram(64.0)
        with patch.object(
            probe, "get_memory_info",
            return_value=MemoryInfo(
                total_gb=64.0,
                available_gb=50.0,
                pressure=MemoryPressure.NOMINAL,
            ),
        ):
            config = probe.recommend_model_config()
            assert config.speculative_decoding is True
            assert "70B" in config.main_model

    def test_16gb_no_speculative(self) -> None:
        """16GB는 투기적 디코딩이 비활성화되어야 합니다."""
        probe = self._make_probe_with_ram(16.0)
        with patch.object(
            probe, "get_memory_info",
            return_value=MemoryInfo(
                total_gb=16.0,
                available_gb=10.0,
                pressure=MemoryPressure.NOMINAL,
            ),
        ):
            config = probe.recommend_model_config()
            assert config.speculative_decoding is False
            assert config.draft_model == ""


# ── AutoTune Logic Tests ─────────────────────────────────────

# autotune은 scripts/ 디렉토리에 있으므로 sys.path 추가
import sys
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "scripts",
    ),
)
from autotune import (
    detect_ram_tier,
    estimate_model_size_gb,
    TIER_BUDGETS,
)


class TestAutoTune:
    """AutoTune 스킬 로직 검증."""

    @pytest.mark.parametrize(
        "ram_gb,expected_tier",
        [
            (8.0, "16gb"),
            (16.0, "16gb"),
            (31.9, "16gb"),
            (32.0, "32gb"),
            (48.0, "32gb"),
            (64.0, "64gb"),
            (96.0, "64gb"),
            (128.0, "128gb"),
            (192.0, "128gb"),
        ],
    )
    def test_detect_ram_tier(
        self, ram_gb: float, expected_tier: str
    ) -> None:
        """RAM 크기별 올바른 티어 감지."""
        assert detect_ram_tier(ram_gb) == expected_tier

    @pytest.mark.parametrize(
        "model_name,expected_gb",
        [
            ("mlx-community/Qwen2.5-14B-Instruct-4bit", 9.0),
            ("mlx-community/Qwen2.5-32B-Instruct-4bit", 19.5),
            ("mlx-community/Llama-3.3-70B-Instruct-4bit", 40.0),
            ("mlx-community/Qwen2.5-72B-Instruct-8bit", 84.0),
            ("mlx-community/Llama-3.2-1B-Instruct-4bit", 0.7),
            ("mlx-community/Qwen2.5-0.5B-Instruct-4bit", 0.4),
        ],
    )
    def test_estimate_model_size(
        self, model_name: str, expected_gb: float
    ) -> None:
        """모델 이름에서 올바른 크기 추정."""
        estimated = estimate_model_size_gb(model_name)
        assert estimated == pytest.approx(expected_gb, rel=0.1)

    def test_tier_budgets_ordering(self) -> None:
        """티어 예산은 RAM이 클수록 커야 합니다."""
        assert TIER_BUDGETS["16gb"] < TIER_BUDGETS["32gb"]
        assert TIER_BUDGETS["32gb"] < TIER_BUDGETS["64gb"]
        assert TIER_BUDGETS["64gb"] < TIER_BUDGETS["128gb"]

    def test_8bit_model_doubled(self) -> None:
        """8-bit 모델은 4-bit의 2배 크기로 추정되어야 합니다."""
        size_4bit = estimate_model_size_gb(
            "mlx-community/Qwen2.5-72B-Instruct-4bit"
        )
        size_8bit = estimate_model_size_gb(
            "mlx-community/Qwen2.5-72B-Instruct-8bit"
        )
        assert size_8bit == pytest.approx(size_4bit * 2.0, rel=0.01)


# ── Dynamic Config Loading Tests (server.py) ─────────────────


class TestDynamicConfigLoading:
    """server.py의 동적 프로파일 로딩 검증."""

    def test_detect_ram_tier_function_exists(self) -> None:
        """server._detect_ram_tier 함수가 존재해야 합니다."""
        # 서버 모듈을 직접 import하면 FastMCP 등의 의존성 이슈가 있으므로
        # server.py 파일에서 함수 정의만 확인
        server_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "server.py",
        )
        with open(server_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "def _detect_ram_tier()" in content
        assert "def _load_mlx_config()" in content
        assert "m4_16gb" in content
        assert "m4_64gb" in content
        assert "m4_128gb" in content

    def test_base_yaml_auto_profile(self) -> None:
        """base.yaml의 hardware_profile이 auto로 설정되어 있어야 합니다."""
        base_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "configs", "base.yaml",
        )
        with open(base_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        profile = data.get("openclaw", {}).get("hardware_profile")
        assert profile == "auto"
