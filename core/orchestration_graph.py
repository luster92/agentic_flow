"""Dependency-injected LangGraph execution core for Clawflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from core.model_policy import ModelPolicy
from core.routing_schema import RoutingDecision


class RouterLike(Protocol):
    async def decide(self, user_message: str) -> RoutingDecision: ...


class WorkerLike(Protocol):
    async def execute(self, task: str, context: list[dict] | None = None) -> dict: ...


CloudCaller = Callable[[str, list[dict] | None, str], Awaitable[str]]
ContextProvider = Callable[[], list[dict]]
CacheGetter = Callable[[str], str | None]
CachePutter = Callable[[str, str], None]
ApprovalChecker = Callable[[RoutingDecision, str], Awaitable[bool]]
ResultHook = Callable[[dict[str, Any]], Awaitable[None]]


class OrchestrationState(TypedDict, total=False):
    request: str
    context: list[dict]
    routing: dict[str, Any]
    model_alias: str
    cached_response: str
    worker_result: dict[str, Any]
    final_response: str
    escalation_reason: str
    approved: bool
    approval_action: str
    error: str


@dataclass(slots=True)
class OrchestrationDependencies:
    router: RouterLike
    worker: WorkerLike
    cloud_call: CloudCaller
    context_provider: ContextProvider = lambda: []
    cache_get: CacheGetter | None = None
    cache_put: CachePutter | None = None
    approval_check: ApprovalChecker | None = None
    result_hook: ResultHook | None = None
    policy: ModelPolicy = field(default_factory=ModelPolicy)


class OrchestrationGraph:
    """Reusable state machine shared by CLI, API, and web transports."""

    def __init__(self, deps: OrchestrationDependencies):
        self.deps = deps

    async def cache_lookup(self, state: OrchestrationState) -> dict[str, Any]:
        if not self.deps.cache_get:
            return {}
        cached = self.deps.cache_get(state["request"])
        return {"cached_response": cached, "final_response": cached} if cached else {}

    async def classify(self, state: OrchestrationState) -> dict[str, Any]:
        decision = await self.deps.router.decide(state["request"])
        selection = self.deps.policy.select(decision)
        return {
            "routing": decision.model_dump(mode="json"),
            "model_alias": selection.alias,
            "context": self.deps.context_provider(),
        }

    async def approval_gate(self, state: OrchestrationState) -> dict[str, Any]:
        decision = RoutingDecision.model_validate(state["routing"])
        if not decision.requires_human_approval:
            return {"approved": True, "approval_action": "not-required"}

        # Compatibility path for deterministic unit tests and embedded callers.
        if self.deps.approval_check is not None:
            approved = await self.deps.approval_check(decision, state["request"])
            return {
                "approved": approved,
                "approval_action": "approve" if approved else "reject",
                "error": "Human approval rejected" if not approved else "",
            }

        resume_payload = interrupt(
            {
                "type": "approval_required",
                "request": state["request"],
                "routing": state["routing"],
                "reason": decision.reason or "High-risk operation requires approval",
                "allowed_actions": ["approve", "reject", "modify"],
            }
        )
        payload = resume_payload if isinstance(resume_payload, dict) else {"action": resume_payload}
        action = str(payload.get("action", "reject")).lower()
        approved = action in {"approve", "modify"}
        update: dict[str, Any] = {
            "approved": approved,
            "approval_action": action,
            "error": "Human approval rejected" if not approved else "",
        }
        modified = payload.get("modified_data") or {}
        if approved and isinstance(modified, dict) and isinstance(modified.get("request"), str):
            update["request"] = modified["request"]
        return update

    async def local_execute(self, state: OrchestrationState) -> dict[str, Any]:
        result = await self.deps.worker.execute(state["request"], context=state.get("context"))
        update: dict[str, Any] = {"worker_result": result}
        if result.get("escalated"):
            if result.get("critic_passed") is False:
                update["escalation_reason"] = "critic-reject"
            elif result.get("validation_passed") is False:
                update["escalation_reason"] = "validation-fail"
            else:
                update["escalation_reason"] = "worker-escalation"
        else:
            update["final_response"] = result.get("response", "")
        return update

    async def cloud_execute(self, state: OrchestrationState) -> dict[str, Any]:
        task = state["request"]
        if state.get("worker_result"):
            task = (
                f"Previous local worker analysis:\n{state['worker_result'].get('response', '')}\n\n"
                f"Original request:\n{state['request']}"
            )
        response = await self.deps.cloud_call(task, state.get("context"), state["model_alias"])
        return {"final_response": response}

    async def persist(self, state: OrchestrationState) -> dict[str, Any]:
        response = state.get("final_response", "")
        if self.deps.cache_put and response and not response.startswith("[ERROR]"):
            self.deps.cache_put(state["request"], response)
        if self.deps.result_hook:
            await self.deps.result_hook(dict(state))
        return {}

    @staticmethod
    def after_cache(state: OrchestrationState) -> Literal["persist", "classify"]:
        return "persist" if state.get("cached_response") else "classify"

    @staticmethod
    def after_classify(state: OrchestrationState) -> Literal["approval", "local", "cloud"]:
        decision = RoutingDecision.model_validate(state["routing"])
        if decision.requires_human_approval:
            return "approval"
        return "cloud" if decision.destination == "CLOUD" else "local"

    @staticmethod
    def after_approval(state: OrchestrationState) -> Literal["local", "cloud", "persist"]:
        if not state.get("approved"):
            return "persist"
        decision = RoutingDecision.model_validate(state["routing"])
        return "cloud" if decision.destination == "CLOUD" else "local"

    @staticmethod
    def after_local(state: OrchestrationState) -> Literal["cloud", "persist"]:
        return "cloud" if state.get("escalation_reason") else "persist"

    def build(self):
        graph = StateGraph(OrchestrationState)
        graph.add_node("cache", self.cache_lookup)
        graph.add_node("classify", self.classify)
        graph.add_node("approval", self.approval_gate)
        graph.add_node("local", self.local_execute)
        graph.add_node("cloud", self.cloud_execute)
        graph.add_node("persist", self.persist)
        graph.add_edge(START, "cache")
        graph.add_conditional_edges("cache", self.after_cache)
        graph.add_conditional_edges("classify", self.after_classify)
        graph.add_conditional_edges("approval", self.after_approval)
        graph.add_conditional_edges("local", self.after_local)
        graph.add_edge("cloud", "persist")
        graph.add_edge("persist", END)
        return graph

    def compile(self, *, checkpointer=None):
        return self.build().compile(checkpointer=checkpointer)
