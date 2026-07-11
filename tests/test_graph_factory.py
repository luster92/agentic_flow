from core.graph import create_orchestration_graph
from core.orchestration_graph import OrchestrationDependencies
from core.routing_schema import RoutingDecision


class Router:
    async def decide(self, user_message):
        return RoutingDecision()


class Worker:
    async def execute(self, task, context=None):
        return {"response": "ok", "escalated": False}


async def cloud_call(task, context, model_alias):
    return "cloud"


def test_create_orchestration_graph_returns_compiled_graph():
    graph = create_orchestration_graph(OrchestrationDependencies(
        router=Router(),
        worker=Worker(),
        cloud_call=cloud_call,
    ))
    assert hasattr(graph, "ainvoke")
