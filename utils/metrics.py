"""
Request Metrics — 에이전트 성능 메트릭 수집
============================================
각 요청에 대한 성능 데이터를 수집하고 요약합니다.
에스컬레이션 비율, 평균 응답 시간, 검증 실패율 등 KPI 추적.
"""

import json
import os
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from time import time

logger = logging.getLogger(__name__)


@dataclass
class RequestMetrics:
    """단일 요청에 대한 성능 메트릭."""
    request_id: str = ""
    timestamp: str = ""
    routing_decision: str = ""       # LOCAL / CLOUD
    routing_method: str = ""         # fast-rule / llm-router
    routing_latency_ms: float = 0.0
    worker_latency_ms: float = 0.0
    validation_retries: int = 0
    critic_result: str = ""          # PASS / REJECT / SKIP
    escalated: bool = False
    final_handler: str = ""          # local-worker / cloud-pm-*
    total_latency_ms: float = 0.0


class MetricsCollector:
    """
    성능 메트릭을 수집하고 파일로 저장합니다.
    """

    def __init__(self, metrics_dir: str = "metrics"):
        self.metrics_dir = metrics_dir
        self._metrics: list[dict] = []

        if not os.path.exists(self.metrics_dir):
            os.makedirs(self.metrics_dir)

        self.metrics_file = os.path.join(self.metrics_dir, "requests.jsonl")
        self._load()

    def record(self, m: RequestMetrics) -> None:
        """메트릭 기록."""
        if not m.timestamp:
            m.timestamp = datetime.now(timezone.utc).isoformat()
        data = asdict(m)
        self._metrics.append(data)

        # JSONL append
        try:
            with open(self.metrics_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"❌ 메트릭 저장 실패: {e}")

    def summary(self) -> dict:
        """전체 메트릭 요약."""
        total = len(self._metrics)
        if total == 0:
            return {"total_requests": 0}

        escalations = sum(1 for m in self._metrics if m.get("escalated"))
        fast_routes = sum(1 for m in self._metrics if m.get("routing_method") == "fast-rule")
        retries = sum(m.get("validation_retries", 0) for m in self._metrics)
        avg_latency = sum(m.get("total_latency_ms", 0) for m in self._metrics) / total

        return {
            "total_requests": total,
            "escalation_rate": f"{escalations / total * 100:.1f}%",
            "fast_route_rate": f"{fast_routes / total * 100:.1f}%",
            "total_retries": retries,
            "avg_latency_ms": round(avg_latency, 1),
        }

    def _load(self) -> None:
        if not os.path.exists(self.metrics_file):
            return
        try:
            with open(self.metrics_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        self._metrics.append(json.loads(line))
        except Exception as e:
            logger.error(f"❌ 메트릭 로드 실패: {e}")
