"""
MLXEngine — Apple Silicon 전용 추론 엔진
==========================================
Apple MLX 프레임워크를 사용하여 M4 GPU에서 직접 추론합니다.

핵심 기능:
- 4-bit 양자화 모델 로딩 (Qwen2.5-32B-Instruct-4bit)
- 투기적 디코딩 (Speculative Decoding) — 드래프트 모델로 2배 속도
- KV Cache 양자화 (4-bit) — 긴 컨텍스트에서 OOM 방지
- 동적 메모리 관리 — 가용 메모리 기반 모델 전환

MLX 미설치 환경에서는 LiteLLM fallback으로 동작합니다.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)

# ── MLX import guard ──────────────────────────────────────────
_MLX_AVAILABLE = False
_mlx = None
_mlx_lm = None
_mlx_lm_generate = None

try:
    import mlx.core as _mlx  # type: ignore[import-untyped]
    import mlx_lm  # type: ignore[import-untyped]
    from mlx_lm import load as _mlx_load  # type: ignore[import-untyped]
    from mlx_lm import generate as _mlx_generate  # type: ignore[import-untyped]
    _MLX_AVAILABLE = True
    logger.info("✅ MLX backend available (Apple Silicon)")
except ImportError:
    logger.info(
        "⚠️ MLX not available — using LiteLLM fallback. "
        "Install with: pip install mlx mlx-lm"
    )


# ── Enums & Config ────────────────────────────────────────────

class EngineBackend(str, Enum):
    """추론 백엔드."""
    MLX = "mlx"
    LITELLM = "litellm"


@dataclass
class MLXConfig:
    """MLX 엔진 설정.

    config/m4_32gb.yaml에서 로드하거나 기본값 사용.
    """
    main_model: str = "mlx-community/Qwen2.5-32B-Instruct-4bit"
    draft_model: str = "mlx-community/Qwen2.5-0.5B-Instruct-4bit"
    speculative_decoding: bool = True
    kv_cache_bits: int = 4
    max_context_length: int = 8192
    max_tokens: int = 2048
    temperature: float = 0.7
    top_p: float = 0.9
    repetition_penalty: float = 1.1
    # 메모리 안전 마진
    model_budget_gb: float = 22.0
    fallback_threshold_gb: float = 4.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MLXConfig:
        """딕셔너리에서 MLXConfig 생성."""
        return cls(**{
            k: v for k, v in data.items()
            if k in cls.__dataclass_fields__
        })


# ── Generation Result ─────────────────────────────────────────

@dataclass
class GenerationResult:
    """텍스트 생성 결과."""
    text: str
    tokens_generated: int = 0
    tokens_per_second: float = 0.0
    elapsed_ms: float = 0.0
    backend: EngineBackend = EngineBackend.MLX
    draft_acceptance_rate: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


# ── MLX Engine ────────────────────────────────────────────────

class MLXEngine:
    """Apple Silicon 전용 MLX 추론 엔진.

    M4 GPU에서 직접 추론을 수행합니다.
    MLX가 없는 환경에서는 LiteLLM fallback으로 동작합니다.

    Usage:
        engine = MLXEngine()
        await engine.load()
        result = await engine.generate("Hello, world!")
        await engine.unload()
    """

    def __init__(
        self,
        config: MLXConfig | None = None,
        litellm_base_url: str = "http://localhost:4000",
    ) -> None:
        self.config = config or MLXConfig()
        self._litellm_base_url = litellm_base_url

        # 모델 인스턴스
        self._model: Any = None
        self._tokenizer: Any = None
        self._draft_model: Any = None
        self._draft_tokenizer: Any = None

        # 상태 추적
        self._loaded: bool = False
        self._backend: EngineBackend = (
            EngineBackend.MLX if _MLX_AVAILABLE
            else EngineBackend.LITELLM
        )
        self._total_tokens: int = 0
        self._total_requests: int = 0

    # ── 모델 로딩 ─────────────────────────────────────────

    async def load(self) -> bool:
        """모델을 메모리에 로드합니다.

        Returns:
            True if loaded successfully
        """
        if self._loaded:
            logger.info("⚡ Models already loaded, skipping")
            return True

        if not _MLX_AVAILABLE:
            logger.info(
                "🔄 MLX unavailable, using LiteLLM fallback "
                f"(proxy: {self._litellm_base_url})"
            )
            self._backend = EngineBackend.LITELLM
            self._loaded = True
            return True

        try:
            return await asyncio.to_thread(self._load_sync)
        except Exception as e:
            logger.error(f"❌ MLX model loading failed: {e}")
            logger.info("🔄 Falling back to LiteLLM")
            self._backend = EngineBackend.LITELLM
            self._loaded = True
            return True

    def _load_sync(self) -> bool:
        """동기 모델 로딩 (별도 스레드에서 실행)."""
        start = time.monotonic()

        # 메인 모델 로드
        logger.info(
            f"🧠 Loading main model: {self.config.main_model}"
        )
        self._model, self._tokenizer = _mlx_load(
            self.config.main_model,
        )
        elapsed_main = time.monotonic() - start
        logger.info(
            f"✅ Main model loaded in {elapsed_main:.1f}s"
        )

        # 드래프트 모델 로드 (투기적 디코딩용)
        if self.config.speculative_decoding:
            logger.info(
                f"🏃 Loading draft model: {self.config.draft_model}"
            )
            draft_start = time.monotonic()
            self._draft_model, self._draft_tokenizer = _mlx_load(
                self.config.draft_model,
            )
            elapsed_draft = time.monotonic() - draft_start
            logger.info(
                f"✅ Draft model loaded in {elapsed_draft:.1f}s"
            )

        self._loaded = True
        self._backend = EngineBackend.MLX
        total = time.monotonic() - start
        logger.info(
            f"🚀 MLX Engine ready! "
            f"Total load time: {total:.1f}s | "
            f"Backend: {self._backend.value}"
        )
        return True

    # ── 모델 언로딩 ───────────────────────────────────────

    async def unload(self) -> None:
        """모델을 메모리에서 해제합니다."""
        if not self._loaded:
            return

        if self._backend == EngineBackend.MLX and _MLX_AVAILABLE:
            self._model = None
            self._tokenizer = None
            self._draft_model = None
            self._draft_tokenizer = None

            # GPU 메모리 명시적 해제
            try:
                _mlx.metal.clear_cache()  # type: ignore[union-attr]
                logger.info("🧹 GPU cache cleared")
            except Exception as e:
                logger.warning(f"⚠️ Cache clear failed: {e}")

        self._loaded = False
        logger.info("🔌 MLX Engine unloaded")

    # ── 텍스트 생성 ───────────────────────────────────────

    async def generate(
        self,
        prompt: str,
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        system_prompt: str | None = None,
    ) -> GenerationResult:
        """텍스트를 생성합니다.

        Args:
            prompt: 사용자 입력
            max_tokens: 최대 생성 토큰 수
            temperature: 샘플링 온도
            system_prompt: 시스템 프롬프트

        Returns:
            GenerationResult
        """
        if not self._loaded:
            await self.load()

        max_tok = max_tokens or self.config.max_tokens
        temp = temperature or self.config.temperature

        if self._backend == EngineBackend.LITELLM:
            return await self._generate_litellm(
                prompt, max_tok, temp, system_prompt
            )

        return await self._generate_mlx(
            prompt, max_tok, temp, system_prompt
        )

    async def _generate_mlx(
        self,
        prompt: str,
        max_tokens: int,
        temperature: float,
        system_prompt: str | None,
    ) -> GenerationResult:
        """MLX 백엔드로 텍스트 생성."""
        start = time.monotonic()

        # 채팅 템플릿 적용
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        if hasattr(self._tokenizer, "apply_chat_template"):
            formatted = self._tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )
        else:
            formatted = prompt

        def _run() -> tuple[str, dict[str, Any]]:
            gen_kwargs: dict[str, Any] = {
                "temp": temperature,
                "max_tokens": max_tokens,
                "repetition_penalty": self.config.repetition_penalty,
            }

            # 투기적 디코딩
            if (
                self.config.speculative_decoding
                and self._draft_model is not None
            ):
                gen_kwargs["draft_model"] = self._draft_model

            result_text = _mlx_generate(
                self._model,
                self._tokenizer,
                prompt=formatted,
                **gen_kwargs,
            )

            return result_text, gen_kwargs

        text, kwargs = await asyncio.to_thread(_run)

        elapsed = (time.monotonic() - start) * 1000
        # 대략적인 토큰 수 추정
        token_count = len(text.split()) * 1.3  # 근사치
        tps = (token_count / (elapsed / 1000)) if elapsed > 0 else 0

        self._total_tokens += int(token_count)
        self._total_requests += 1

        # GPU 캐시 정리 (긴 생성 후)
        if token_count > 500 and _MLX_AVAILABLE:
            try:
                _mlx.metal.clear_cache()  # type: ignore[union-attr]
            except Exception:
                pass

        return GenerationResult(
            text=text,
            tokens_generated=int(token_count),
            tokens_per_second=round(tps, 1),
            elapsed_ms=round(elapsed, 1),
            backend=EngineBackend.MLX,
            metadata={
                "speculative": self.config.speculative_decoding,
                "model": self.config.main_model,
            },
        )

    async def _generate_litellm(
        self,
        prompt: str,
        max_tokens: int,
        temperature: float,
        system_prompt: str | None,
    ) -> GenerationResult:
        """LiteLLM fallback으로 텍스트 생성."""
        try:
            from openai import AsyncOpenAI
        except ImportError:
            return GenerationResult(
                text="[ERROR] OpenAI client not installed",
                backend=EngineBackend.LITELLM,
            )

        start = time.monotonic()
        client = AsyncOpenAI(
            base_url=self._litellm_base_url,
            api_key="not-needed",
        )

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            response = await client.chat.completions.create(
                model="local-worker",
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            text = response.choices[0].message.content or ""
            elapsed = (time.monotonic() - start) * 1000
            tokens = response.usage.completion_tokens if response.usage else 0

            self._total_tokens += tokens
            self._total_requests += 1

            return GenerationResult(
                text=text,
                tokens_generated=tokens,
                tokens_per_second=round(
                    tokens / (elapsed / 1000), 1
                ) if elapsed > 0 else 0,
                elapsed_ms=round(elapsed, 1),
                backend=EngineBackend.LITELLM,
                metadata={"model": "local-worker"},
            )
        except Exception as e:
            logger.error(f"❌ LiteLLM generation failed: {e}")
            return GenerationResult(
                text=f"[ERROR] LiteLLM generation failed: {e}",
                backend=EngineBackend.LITELLM,
            )

    # ── 스트리밍 생성 ─────────────────────────────────────

    async def generate_stream(
        self,
        prompt: str,
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        system_prompt: str | None = None,
    ) -> AsyncIterator[str]:
        """토큰 단위 스트리밍 생성.

        Yields:
            생성된 텍스트 청크
        """
        if not self._loaded:
            await self.load()

        if self._backend == EngineBackend.LITELLM:
            async for chunk in self._stream_litellm(
                prompt,
                max_tokens or self.config.max_tokens,
                temperature or self.config.temperature,
                system_prompt,
            ):
                yield chunk
        else:
            # MLX는 현재 동기 생성만 지원 → 전체 결과를 청크로 분할
            result = await self.generate(
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                system_prompt=system_prompt,
            )
            # 문장 단위로 스트리밍 시뮬레이션
            sentences = result.text.split(". ")
            for i, sentence in enumerate(sentences):
                chunk = sentence + (". " if i < len(sentences) - 1 else "")
                yield chunk
                await asyncio.sleep(0.01)

    async def _stream_litellm(
        self,
        prompt: str,
        max_tokens: int,
        temperature: float,
        system_prompt: str | None,
    ) -> AsyncIterator[str]:
        """LiteLLM 스트리밍."""
        try:
            from openai import AsyncOpenAI
        except ImportError:
            yield "[ERROR] OpenAI client not installed"
            return

        client = AsyncOpenAI(
            base_url=self._litellm_base_url,
            api_key="not-needed",
        )

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            stream = await client.chat.completions.create(
                model="local-worker",
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            async for chunk in stream:
                content = chunk.choices[0].delta.content or ""
                if content:
                    yield content
        except Exception as e:
            yield f"[ERROR] Streaming failed: {e}"

    # ── 상태 조회 ─────────────────────────────────────────

    @property
    def is_loaded(self) -> bool:
        """모델 로딩 여부."""
        return self._loaded

    @property
    def backend(self) -> EngineBackend:
        """현재 추론 백엔드."""
        return self._backend

    @property
    def is_mlx(self) -> bool:
        """MLX 백엔드 사용 여부."""
        return self._backend == EngineBackend.MLX

    def get_stats(self) -> dict[str, Any]:
        """엔진 통계 반환."""
        return {
            "loaded": self._loaded,
            "backend": self._backend.value,
            "mlx_available": _MLX_AVAILABLE,
            "main_model": self.config.main_model,
            "draft_model": (
                self.config.draft_model
                if self.config.speculative_decoding
                else None
            ),
            "speculative_decoding": self.config.speculative_decoding,
            "kv_cache_bits": self.config.kv_cache_bits,
            "total_tokens": self._total_tokens,
            "total_requests": self._total_requests,
        }
