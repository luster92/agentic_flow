"""Command and task orchestration for the graph-native CLI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.planner import TaskPlanner
from core.runtime import GraphRuntime
from core.state import AgentState, CheckpointType
from engine.adversarial import DebateLoop
from utils.history_manager import HistoryManager


@dataclass(slots=True)
class CommandResult:
    handled: bool
    output: str = ""
    should_exit: bool = False


class GraphCLIController:
    """Legacy-compatible commands without duplicating graph execution logic."""

    def __init__(
        self,
        *,
        runtime: GraphRuntime,
        history_dir: str,
        context_window: int,
        planner: TaskPlanner,
        debate: DebateLoop,
    ) -> None:
        self.runtime = runtime
        self.history_dir = history_dir
        self.context_window = context_window
        self.planner = planner
        self.debate = debate
        self.last_response = ""

    async def execute_request(self, request: str) -> list[dict[str, Any]]:
        plan = await self.planner.create_plan(request)
        if not plan or not plan.tasks:
            result = await self.runtime.invoke(request)
            self._remember(result)
            return [result]

        results: list[dict[str, Any]] = []
        while not plan.all_completed():
            ready = plan.get_next_tasks()
            if not ready:
                raise RuntimeError("Task plan contains unresolved dependencies")
            for task in ready:
                task.status = "running"
                prompt = f"Sub-task [{task.id}]: {task.description}\n\nOriginal request:\n{request}"
                result = await self.runtime.invoke(prompt)
                results.append(result)
                if result.get("status") == "pending_approval":
                    return results
                response = result.get("final_response") or result.get("error") or ""
                task.result = response
                task.status = "failed" if response.startswith("[ERROR]") else "completed"
                self._remember(result)
        return results

    async def handle(self, raw: str) -> CommandResult:
        if not raw.startswith("/"):
            return CommandResult(False)

        parts = raw.split()
        command = parts[0].lower()
        args = parts[1:]

        if command in {"/exit", "/quit"}:
            return CommandResult(True, should_exit=True)
        if command == "/help":
            return CommandResult(True, self.help_text())
        if command == "/clear":
            self.runtime.reset()
            self.last_response = ""
            return CommandResult(True, "Session cleared.")
        if command in {"/status", "/current"}:
            return CommandResult(True, self._status_text(await self.runtime.graph_state()))
        if command == "/stats":
            stats = self.runtime.history.get_stats()
            return CommandResult(True, f"project={stats['project']} messages={stats['total_messages']} file={stats['file_path']}")
        if command == "/list":
            projects = HistoryManager.list_projects(self.history_dir)
            return CommandResult(True, "Projects: " + (", ".join(projects) or "none"))
        if command in {"/new", "/load"}:
            if not args:
                return CommandResult(True, f"Usage: {command} <project>")
            self._switch_project(args[0], clear=(command == "/new"))
            return CommandResult(True, f"Project switched: {args[0]}")
        if command == "/persona":
            if not args:
                available = ",".join(self.runtime.persona.available_personas())
                return CommandResult(True, f"active={self.runtime.persona.current_id} available={available}")
            persona = self.runtime.persona.switch_persona(args[0], reason="Graph CLI command")
            return CommandResult(True, f"Persona switched: {persona.display_name}")
        if command == "/checkpoint":
            label = " ".join(args) if args else "manual"
            self.runtime.checkpoint.save_checkpoint(self.runtime.state, CheckpointType.MILESTONE, label=label)
            return CommandResult(True, f"Checkpoint saved: step={self.runtime.state.step} label={label}")
        if command == "/rollback":
            if not args:
                checkpoints = self.runtime.checkpoint.list_checkpoints(self.runtime.state.session_id)
                text = "\n".join(f"step={cp['step']} label={cp['label']}" for cp in checkpoints)
                return CommandResult(True, text or "No checkpoints")
            restored = self.runtime.checkpoint.rollback(self.runtime.state.session_id, int(args[0]))
            if not restored:
                return CommandResult(True, "Checkpoint not found")
            self.runtime.state = restored
            return CommandResult(True, f"Rolled back to step={args[0]}")
        if command in {"/approve", "/reject"}:
            result = await self.runtime.resume(command[1:])
            self._remember(result)
            return CommandResult(True, self._response_text(result))
        if command == "/modify":
            modified_request = raw.partition(" ")[2].strip()
            if not modified_request:
                return CommandResult(True, "Usage: /modify <replacement request>")
            result = await self.runtime.resume("modify", {"request": modified_request})
            self._remember(result)
            return CommandResult(True, self._response_text(result))
        if command == "/debate":
            if not self.last_response:
                return CommandResult(True, "No response to review")
            result = await self.debate.run(proposal=self.last_response, task="Review the last response")
            if result.approved:
                self.last_response = result.final_proposal
            return CommandResult(True, result.report or self.last_response)
        return CommandResult(True, f"Unknown command: {command}\n{self.help_text()}")

    def _switch_project(self, project: str, *, clear: bool) -> None:
        history = HistoryManager(project_name=project, base_dir=self.history_dir, context_window=self.context_window)
        if clear:
            history.clear()
        self.runtime.history = history
        self.runtime.state = AgentState()
        self.runtime.graph = self.runtime._build_graph()

    def _remember(self, result: dict[str, Any]) -> None:
        response = result.get("final_response")
        if response:
            self.last_response = response

    @staticmethod
    def _response_text(result: dict[str, Any]) -> str:
        if result.get("status") == "pending_approval":
            interrupt = result.get("interrupt") or {}
            return f"Approval required: {interrupt.get('reason', 'review required')}"
        return result.get("final_response") or result.get("error") or "No response"

    def _status_text(self, graph_state: dict[str, Any]) -> str:
        return (
            f"project={self.runtime.history.project_name} session={self.runtime.state.session_id} "
            f"turn={self.runtime.state.turn_number} step={self.runtime.state.step} "
            f"persona={self.runtime.persona.current_id} graph={graph_state.get('status')}"
        )

    @staticmethod
    def help_text() -> str:
        return (
            "Commands: /new /load /list /current /stats /clear /persona "
            "/checkpoint /rollback /approve /reject /modify /debate /exit"
        )
