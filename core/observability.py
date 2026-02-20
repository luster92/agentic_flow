import logging
from typing import Any, Dict
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

# Prometheus Metrics
from prometheus_client import Counter

logger = logging.getLogger(__name__)

# Prometheus Counters for Token Usage
LLM_TOKENS_IN = Counter('llm_tokens_in_total', 'Input tokens used', ['model', 'agent'])
LLM_TOKENS_OUT = Counter('llm_tokens_out_total', 'Output tokens generated', ['model', 'agent'])
LLM_COST_ESTIMATE = Counter('llm_cost_estimate_usd', 'Estimated cost in USD', ['model', 'agent'])

# ─ Cost estimation mapping (Standard Vertex / Claude defaults)
COST_MAP = {
    "gemini-1.5-pro": {"in": 0.00125 / 1000, "out": 0.00375 / 1000},
    "claude-3-opus": {"in": 0.015 / 1000, "out": 0.075 / 1000},
    "claude-3-sonnet": {"in": 0.003 / 1000, "out": 0.015 / 1000},
    "default": {"in": 0.001 / 1000, "out": 0.002 / 1000},
}

class TokenUsageTracker(BaseCallbackHandler):
    """
    LangGraph 콜백 핸들러. 
    Vertex AI 및 Claude 스트리밍 응답의 token usage 메타데이터를 캡처하여
    Prometheus 메트릭으로 익스포트합니다.
    (Vertex AI 초기화 시 stream_usage=True 필수)
    """

    def __init__(self, agent_name: str = "unknown"):
        super().__init__()
        self.agent_name = agent_name

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """LLM 호출이 종료될 때 메타데이터에서 토큰을 추출합니다."""
        if not response.llm_output:
            return

        token_usage = response.llm_output.get("token_usage", {})
        if not token_usage:
            return

        model_name = response.llm_output.get("model_name", "unknown")
        
        prompt_tokens = token_usage.get("prompt_tokens", 0)
        completion_tokens = token_usage.get("completion_tokens", 0)

        if prompt_tokens > 0:
            LLM_TOKENS_IN.labels(model=model_name, agent=self.agent_name).inc(prompt_tokens)
        if completion_tokens > 0:
            LLM_TOKENS_OUT.labels(model=model_name, agent=self.agent_name).inc(completion_tokens)

        # Estimate costs
        rates = COST_MAP.get(model_name, COST_MAP["default"])
        est_cost = (prompt_tokens * rates["in"]) + (completion_tokens * rates["out"])
        
        if est_cost > 0:
            LLM_COST_ESTIMATE.labels(model=model_name, agent=self.agent_name).inc(est_cost)

        logger.debug(f"[TokenTracker] {self.agent_name} ({model_name}): In={prompt_tokens}, Out={completion_tokens}, Cost=${est_cost:.5f}")
