import pytest

from core.orchestration_graph import OrchestrationDependencies, OrchestrationGraph
from core.routing_schema import ExecutionTier, RoutingDecision, TaskType


class Router:
    async def decide(self, user_message):
        return RoutingDecision(
            task_type=TaskType.REASONING,
            execution_tier=ExecutionTier.CLOUD_GENERAL,
        )


class Worker:
    async def execute(self, task, context=None):
        raise AssertionError("cloud routing must skip the local worker")


@pytest.mark.asyncio
async def test_policy_alias_is_passed_to_cloud_adapter():
    aliases = []

    async def cloud_call(task, context, model_alias):
        aliases.append(model_alias)
        return "ok"

    graph = OrchestrationGraph(
        OrchestrationDependencies(
            router=Router(),
            worker=Worker(),
            cloud_call=cloud_call,
        )
    ).compile()

    result = await graph.ainvoke({"request": "reason about this architecture"})

    assert result["final_response"] == "ok"
    assert result["model_alias"] == "cloud-reasoning"
    assert aliases == ["cloud-reasoning"]
