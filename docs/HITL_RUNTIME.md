# Native HITL Runtime

The shared orchestration graph pauses high-risk requests with `langgraph.types.interrupt`.

## Flow

1. `POST /api/v1/conversations/invoke` starts a graph thread using `thread_id`.
2. A high-risk `RoutingDecision` enters the approval node.
3. The node emits an `approval_required` interrupt and persists the checkpoint.
4. `POST /api/v1/conversations/resume` sends `Command(resume=...)` to the same thread.
5. `approve` continues execution, `reject` terminates without tool/model execution, and `modify` may replace the request before continuing.

## Persistence

FastAPI uses one shared `AsyncPostgresSaver` initialized at application startup. The API session registry may recreate an in-memory `GraphRuntime` after process restart; the LangGraph thread remains recoverable because its state is keyed by the normalized `thread_id` in PostgreSQL.

The CLI uses `InMemorySaver` unless a persistent checkpointer is injected.

## Resume payload

```json
{
  "thread_id": "change-123",
  "action": "approve",
  "modified_data": {}
}
```

Allowed actions are `approve`, `reject`, and `modify`. For `modify`, only `modified_data.request` currently changes graph execution input. Arbitrary graph-state mutation is intentionally not exposed.

## Invariants

- Resume must use the exact same normalized thread ID as invoke.
- Cloud or local execution must not occur before approval.
- Rejection must end at persistence without executing Worker or Cloud.
- Provider names remain behind LiteLLM aliases.
- Legacy `core.graph.get_compiled_graph` is no longer used by the API resume endpoint.
