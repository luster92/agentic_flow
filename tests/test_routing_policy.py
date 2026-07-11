import pytest

from agents.router import Router
from core.model_policy import ModelPolicy
from core.routing_schema import ExecutionTier, RoutingDecision, TaskType


def test_model_policy_respects_local_only():
    decision = RoutingDecision(
        task_type=TaskType.REASONING,
        execution_tier=ExecutionTier.CLOUD_SPECIALIST,
        local_only=True,
    )

    selection = ModelPolicy().select(decision)

    assert selection.alias == "local-quality"
    assert selection.fallback_aliases == ()


def test_model_policy_selects_specialized_cloud_alias():
    decision = RoutingDecision(
        task_type=TaskType.CODING,
        execution_tier=ExecutionTier.CLOUD_GENERAL,
    )

    selection = ModelPolicy().select(decision)

    assert selection.alias == "cloud-coding"
    assert "cloud-specialist" in selection.fallback_aliases


@pytest.mark.asyncio
async def test_router_fast_routes_simple_translation():
    decision = await Router().decide("이 문장을 영어로 번역해줘")

    assert decision.execution_tier == ExecutionTier.LOCAL_FAST
    assert decision.task_type == TaskType.GENERAL


@pytest.mark.asyncio
async def test_router_requires_approval_for_destructive_action():
    decision = await Router().decide("운영 DB 테이블을 삭제하고 바로 배포해줘")

    assert decision.requires_human_approval is True
    assert decision.requires_tools is True


@pytest.mark.asyncio
async def test_router_selects_deep_local_only_when_explicit():
    decision = await Router().decide(
        "외부 전송 금지. 느려도 로컬에서 GLM 5.2 Colibri로 심층 분석해줘"
    )

    assert decision.execution_tier == ExecutionTier.DEEP_LOCAL
    assert decision.local_only is True
    assert decision.destination == "LOCAL"


@pytest.mark.asyncio
async def test_route_keeps_backward_compatibility():
    payload = await Router().route("파이썬 코드 버그를 고쳐줘")

    assert payload["destination"] == "LOCAL"
    assert payload["task_type"] == "coding"
    assert payload["execution_tier"] == "local_quality"
