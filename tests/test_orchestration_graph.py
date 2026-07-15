import pytest

from core.orchestration_graph import OrchestrationDependencies, OrchestrationGraph
from core.routing_schema import ExecutionTier, RoutingDecision, TaskType


class FakeRouter:
    def __init__(self, decision):
        self.decision = decision
        self.calls = 0

    async def decide(self, user_message):
        self.calls += 1
        return self.decision


class FakeWorker:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    async def execute(self, task, context=None):
        self.calls += 1
        return self.result


@pytest.mark.asyncio
async def test_cache_short_circuits_router_and_worker():
    router = FakeRouter(RoutingDecision())
    worker = FakeWorker({"response": "worker", "escalated": False})

    async def cloud_call(task, context, model_alias):
        raise AssertionError("cloud must not run")

    graph = OrchestrationGraph(OrchestrationDependencies(
        router=router,
        worker=worker,
        cloud_call=cloud_call,
        cache_get=lambda _: "cached",
    )).compile()

    result = await graph.ainvoke({"request": "hello"})
    assert result["final_response"] == "cached"
    assert router.calls == 0
    assert worker.calls == 0


@pytest.mark.asyncio
async def test_local_success_finishes_without_cloud():
    router = FakeRouter(RoutingDecision(
        task_type=TaskType.CODING,
        execution_tier=ExecutionTier.LOCAL_QUALITY,
    ))
    worker = FakeWorker({
        "response": "local result",
        "escalated": False,
        "validation_passed": True,
        "critic_passed": True,
    })
    cloud_calls = []

    async def cloud_call(task, context, model_alias):
        cloud_calls.append(model_alias)
        return "cloud"

    graph = OrchestrationGraph(OrchestrationDependencies(
        router=router,
        worker=worker,
        cloud_call=cloud_call,
    )).compile()

    result = await graph.ainvoke({"request": "write code"})
    assert result["final_response"] == "local result"
    assert not cloud_calls


@pytest.mark.asyncio
async def test_worker_quality_failure_escalates_to_cloud():
    router = FakeRouter(RoutingDecision(
        task_type=TaskType.CODING,
        execution_tier=ExecutionTier.LOCAL_QUALITY,
    ))
    worker = FakeWorker({
        "response": "broken attempt",
        "escalated": True,
        "validation_passed": False,
        "critic_passed": None,
    })
    cloud_inputs = []

    async def cloud_call(task, context, model_alias):
        cloud_inputs.append((task, model_alias))
        return "recovered"

    graph = OrchestrationGraph(OrchestrationDependencies(
        router=router,
        worker=worker,
        cloud_call=cloud_call,
    )).compile()

    result = await graph.ainvoke({"request": "write code"})
    assert result["final_response"] == "recovered"
    assert result["escalation_reason"] == "validation-fail"
    assert "broken attempt" in cloud_inputs[0][0]


@pytest.mark.asyncio
async def test_human_approval_rejection_blocks_execution():
    router = FakeRouter(RoutingDecision(
        execution_tier=ExecutionTier.CLOUD_SPECIALIST,
        requires_human_approval=True,
    ))
    worker = FakeWorker({"response": "worker", "escalated": False})
    cloud_calls = []

    async def cloud_call(task, context, model_alias):
        cloud_calls.append(model_alias)
        return "cloud"

    async def reject(decision, request):
        return False

    graph = OrchestrationGraph(OrchestrationDependencies(
        router=router,
        worker=worker,
        cloud_call=cloud_call,
        approval_check=reject,
    )).compile()

    result = await graph.ainvoke({"request": "deploy production"})
    assert result["approved"] is False
    assert result["error"] == "Human approval rejected"
    assert worker.calls == 0
    assert not cloud_calls
