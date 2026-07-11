import pytest

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from core.orchestration_graph import OrchestrationDependencies, OrchestrationGraph
from core.routing_schema import ExecutionTier, RoutingDecision


class HighRiskRouter:
    async def decide(self, user_message):
        return RoutingDecision(
            execution_tier=ExecutionTier.CLOUD_SPECIALIST,
            requires_human_approval=True,
            requires_tools=True,
            reason="Production deployment requires approval",
        )


class Worker:
    async def execute(self, task, context=None):
        raise AssertionError("cloud-specialist request must skip local worker")


def build_graph(cloud_calls):
    async def cloud_call(task, context, model_alias):
        cloud_calls.append((task, model_alias))
        return "completed"

    return OrchestrationGraph(
        OrchestrationDependencies(
            router=HighRiskRouter(),
            worker=Worker(),
            cloud_call=cloud_call,
        )
    ).compile(checkpointer=InMemorySaver())


@pytest.mark.asyncio
async def test_native_approval_interrupt_then_resume():
    cloud_calls = []
    graph = build_graph(cloud_calls)
    config = {"configurable": {"thread_id": "approval-thread"}}

    paused = await graph.ainvoke({"request": "deploy production"}, config=config)
    assert paused["__interrupt__"][0].value["type"] == "approval_required"
    assert not cloud_calls

    resumed = await graph.ainvoke(
        Command(resume={"action": "approve", "modified_data": {}}),
        config=config,
    )
    assert resumed["approved"] is True
    assert resumed["approval_action"] == "approve"
    assert resumed["final_response"] == "completed"
    assert cloud_calls == [("deploy production", "cloud-specialist")]


@pytest.mark.asyncio
async def test_native_rejection_finishes_without_execution():
    cloud_calls = []
    graph = build_graph(cloud_calls)
    config = {"configurable": {"thread_id": "reject-thread"}}

    await graph.ainvoke({"request": "deploy production"}, config=config)
    resumed = await graph.ainvoke(
        Command(resume={"action": "reject", "modified_data": {}}),
        config=config,
    )

    assert resumed["approved"] is False
    assert resumed["approval_action"] == "reject"
    assert resumed["error"] == "Human approval rejected"
    assert not cloud_calls


@pytest.mark.asyncio
async def test_modify_action_replaces_request_before_execution():
    cloud_calls = []
    graph = build_graph(cloud_calls)
    config = {"configurable": {"thread_id": "modify-thread"}}

    await graph.ainvoke({"request": "deploy production now"}, config=config)
    resumed = await graph.ainvoke(
        Command(
            resume={
                "action": "modify",
                "modified_data": {"request": "produce a deployment plan only"},
            }
        ),
        config=config,
    )

    assert resumed["approved"] is True
    assert resumed["approval_action"] == "modify"
    assert cloud_calls[0][0] == "produce a deployment plan only"
