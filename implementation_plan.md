# Agentic Flow Architecture Upgrade Plan

This plan details the implementation steps to evolve the `agentic_flow` system into a highly observable, human-controlled, and production-ready multi-agent platform. It introduces Human-in-the-Loop (HITL) mechanisms, deep monitoring with OpenTelemetry and Grafana, real-time token tracking, a React-based generative UI, and robust security & deployment strategies based on the provided proposal.

## Phase 1: Persistent State & Human-in-the-Loop (HITL)
Implementation of explicit Pause (approval) and Halt (emergency stop) mechanisms.

- **Checkpointer Setup**: Configure PostgreSQL as LangGraph Durability Checkpointer (`AsyncPostgresSaver`).
- **Pause/Breakpoint Logic**:
  - Inject `interrupt_before=["billing_approval", "sales_discount"]` at compilation.
  - State Serialization: Save graph state with all conversation/agent reasoning paths.
- **Halt/Kill Switch**:
  - Setup Redis Pub/Sub listener for Halt events asynchronously.
  - Add `halt_requested` flag in State object.
  - Add Conditional Edges checking `state.get('halt_requested')` routing to `END`.
- **API & Controllers**:
  - WebSocket endpoints to broadcast "Pending" status for Paused traces.
  - `/resume` endpoint accepting `thread_id` and approval payload.
  - `/halt` endpoint to broadcast stop signal via Redis.
- **Protection**: Ensure `recursion_limit` is set in `RunnableConfig` for endless loop prevention.

## Phase 2: Observability, Monitoring & Cost Tracking
Integrating telemetry for nodes, LLM token expenditures, and cost metrics.

- **OpenTelemetry & Prometheus**:
  - Initialize OpenTelemetry SDK and Prometheus Exporter (`/metrics` endpoint).
  - Instrument LangGraph nodes with Span & Attribute tagging.
- **Micro-Tracing**: Integrate LangSmith/Langfuse for Distributed Tracing (Tree/Waterfall visualizations).
- **Vertex AI Token Tracking**:
  - Initialization: Ensure all models have `stream_usage=True` applied.
  - Implement `UsageMetadataCallbackHandler` for astream/ainvoke to capture prompt/completion tokens.
  - Export token usage metrics to Prometheus.
- **Grafana Integration**:
  - Build dashboards using 'Agent Framework Workflow Dashboard'.
  - Panels: Visual Workflow Graph, Detailed Trace Analysis, Token Burn Rate & Trends.
  - (Optional) Grafana Assistant using MCP for natural language queries on PromQL.

## Phase 3: Generative UI Frontend Transition
Replacing synchronous Streamlit UI with a real-time React application.

- **Framework**: Scaffold React (Next.js) frontend.
- **LangGraph Synchronization**: Integrate `agent-chat-ui` or `CopilotKit` for state synchronization.
- **Interactive Dashboards**: Build Scratchpad UI for HITL approximations and parameter editing before resuming.
- **Reasoning Stream Filtering**: Configure reasoning token filtering (`langsmith:nostream`) to maintain a clean chat pane while keeping internal logs intact.

## Phase 4: Security & Deployment Strategy
Hardening the system for enterprise-grade deployment.

- **Security Middleware**:
  - FastAPI JWT Authentication middleware.
  - Role-Based Access Control (RBAC) specifically restricting HITL endpoints to admins/supervisors.
  - Global Rate Limiter (Token bucket algorithm per user/session/IP).
- **Containerization**:
  - Create monolithic `docker-compose.yml` (FastAPI, Next.js, Postgres, Redis, Prometheus, Grafana).
- **Secret Management**:
  - Migrate credential management to hardened `.env` deployment.
