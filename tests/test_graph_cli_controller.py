import pytest

from core.cli_controller import GraphCLIController
from core.planner import SubTask, TaskPlan


class FakeHistory:
    project_name = "default"

    def get_stats(self):
        return {"project": "default", "total_messages": 2, "file_path": "history.json"}


class FakeState:
    session_id = "thread-1"
    turn_number = 1
    step = 2


class FakePersona:
    current_id = "default"

    def available_personas(self):
        return ["default", "architect"]

    def switch_persona(self, persona_id, reason):
        return type("Persona", (), {"display_name": persona_id})()


class FakeCheckpoint:
    def __init__(self):
        self.saved = []

    def save_checkpoint(self, state, checkpoint_type, label):
        self.saved.append(label)

    def list_checkpoints(self, session_id):
        return [{"step": 1, "label": "first"}]

    def rollback(self, session_id, step):
        return FakeState() if step == 1 else None


class FakeRuntime:
    def __init__(self):
        self.history = FakeHistory()
        self.state = FakeState()
        self.persona = FakePersona()
        self.checkpoint = FakeCheckpoint()
        self.invocations = []
        self.resumes = []

    async def invoke(self, request):
        self.invocations.append(request)
        return {"status": "completed", "final_response": f"done:{request}"}

    async def resume(self, action, modified_data=None):
        self.resumes.append((action, modified_data or {}))
        return {"status": "completed", "final_response": action}

    async def graph_state(self):
        return {"status": "idle"}

    def reset(self):
        self.invocations.clear()


class EmptyPlanner:
    async def create_plan(self, request):
        return None


class SequentialPlanner:
    async def create_plan(self, request):
        return TaskPlan(
            original_request=request,
            tasks=[
                SubTask(id="one", description="first"),
                SubTask(id="two", description="second", dependencies=["one"]),
            ],
        )


class FakeDebate:
    async def run(self, proposal, task):
        return type(
            "Result",
            (),
            {"approved": True, "final_proposal": proposal + " reviewed", "report": "approved"},
        )()


def controller(runtime, planner):
    return GraphCLIController(
        runtime=runtime,
        history_dir="history",
        context_window=20,
        planner=planner,
        debate=FakeDebate(),
    )


@pytest.mark.asyncio
async def test_non_command_is_not_consumed():
    result = await controller(FakeRuntime(), EmptyPlanner()).handle("hello")
    assert result.handled is False


@pytest.mark.asyncio
async def test_native_hitl_commands_resume_same_runtime():
    runtime = FakeRuntime()
    cli = controller(runtime, EmptyPlanner())

    approved = await cli.handle("/approve")
    modified = await cli.handle("/modify safer request")

    assert approved.output == "approve"
    assert modified.output == "modify"
    assert runtime.resumes == [
        ("approve", {}),
        ("modify", {"request": "safer request"}),
    ]


@pytest.mark.asyncio
async def test_planner_executes_dependency_order_through_graph():
    runtime = FakeRuntime()
    results = await controller(runtime, SequentialPlanner()).execute_request("build feature")

    assert len(results) == 2
    assert "Sub-task [one]" in runtime.invocations[0]
    assert "Sub-task [two]" in runtime.invocations[1]


@pytest.mark.asyncio
async def test_status_and_checkpoint_commands():
    runtime = FakeRuntime()
    cli = controller(runtime, EmptyPlanner())

    status = await cli.handle("/status")
    checkpoint = await cli.handle("/checkpoint release")

    assert "graph=idle" in status.output
    assert checkpoint.output.endswith("label=release")
    assert runtime.checkpoint.saved == ["release"]
