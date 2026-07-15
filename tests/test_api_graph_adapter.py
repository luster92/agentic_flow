import pytest

from api.graph_adapter import GraphSessionRegistry


class DummyRuntime:
    def __init__(self, session_id):
        self.session_id = session_id
        self.calls = []

    async def invoke(self, request):
        self.calls.append(request)
        return {"final_response": f"{self.session_id}:{request}"}


class DummyRegistry(GraphSessionRegistry):
    def _create_runtime(self, session_key):
        return DummyRuntime(session_key)


@pytest.mark.asyncio
async def test_same_thread_reuses_runtime():
    registry = DummyRegistry()

    first = await registry.get("alpha")
    second = await registry.get("alpha")

    assert first is second


@pytest.mark.asyncio
async def test_different_threads_are_isolated():
    registry = DummyRegistry()

    alpha = await registry.get("alpha")
    beta = await registry.get("beta")

    assert alpha is not beta
    assert alpha.session_id == "alpha"
    assert beta.session_id == "beta"


@pytest.mark.asyncio
async def test_invoke_routes_to_normalized_thread_runtime():
    registry = DummyRegistry()

    result = await registry.invoke("team/../../secret", "hello")

    assert result["final_response"] == "team-..-..-secret:hello"
    assert "team-..-..-secret" in registry._sessions


def test_empty_thread_id_is_rejected():
    with pytest.raises(ValueError):
        GraphSessionRegistry._normalize_thread_id("///")
