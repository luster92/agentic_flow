import asyncio
import logging
from typing import Any, Dict

import prometheus_client
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from pydantic import BaseModel, Field
from psycopg_pool import AsyncConnectionPool
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from api.graph_adapter import GraphSessionRegistry
from core.auth import create_access_token, get_password_hash, require_role, verify_password
from core.graph import get_compiled_graph
from core.redis_events import halt_manager

logger = logging.getLogger("api")
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Clawflow Enterprise HITL API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
FastAPIInstrumentor.instrument_app(app)

pg_pool: AsyncConnectionPool | None = None
graph_sessions = GraphSessionRegistry()


@app.get("/metrics", response_class=PlainTextResponse)
def metrics():
    return prometheus_client.generate_latest()


@app.on_event("startup")
async def startup_event():
    global pg_pool
    pg_pool = AsyncConnectionPool(
        conninfo="postgresql://postgres:postgres@localhost:5432/clawflow",
        max_size=20,
        kwargs={"autocommit": True},
    )
    async with pg_pool.connection() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password VARCHAR(255) NOT NULL,
                role VARCHAR(20) NOT NULL DEFAULT 'operator'
            )
            """
        )
        async with conn.cursor() as cur:
            await cur.execute("SELECT COUNT(*) FROM users")
            count = (await cur.fetchone())[0]
            if count == 0:
                await cur.executemany(
                    "INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
                    [
                        ("admin", get_password_hash("admin123"), "admin"),
                        ("operator", get_password_hash("operator123"), "operator"),
                    ],
                )
                logger.info("Seeded default users: admin, operator")

    await halt_manager.connect()
    await graph_sessions.start()


@app.on_event("shutdown")
async def shutdown_event():
    await graph_sessions.close()
    if pg_pool:
        await pg_pool.close()
    await halt_manager.close()


class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/v1/auth/login")
@limiter.limit("5/minute")
async def login(request: Request, login_data: LoginRequest):
    if pg_pool is None:
        raise HTTPException(status_code=503, detail="Database is not initialized")
    async with pg_pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT password, role FROM users WHERE username = %s",
                (login_data.username,),
            )
            user_record = await cur.fetchone()

    if not user_record or not verify_password(login_data.password, user_record[0]):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_access_token(data={"sub": login_data.username, "role": user_record[1]})
    return {"access_token": token, "token_type": "bearer"}


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)


manager = ConnectionManager()


@app.websocket("/ws/events")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


class InvokeRequest(BaseModel):
    thread_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=100_000)


@app.post("/api/v1/conversations/invoke")
@limiter.limit("30/minute")
async def invoke_conversation(
    request: Request,
    req_body: InvokeRequest,
    current_user: dict = Depends(require_role("operator")),
):
    """Execute one request through the shared policy-based LangGraph runtime."""
    try:
        result = await graph_sessions.invoke(req_body.thread_id, req_body.message)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Graph invocation failed for thread %s", req_body.thread_id)
        raise HTTPException(status_code=500, detail="Graph invocation failed") from exc

    return {
        "thread_id": req_body.thread_id,
        "response": result.get("final_response"),
        "error": result.get("error"),
        "approved": result.get("approved", True),
        "routing": result.get("routing", {}),
        "model_alias": result.get("model_alias"),
        "escalation_reason": result.get("escalation_reason"),
        "requested_by": current_user["username"],
    }


class ResumeRequest(BaseModel):
    thread_id: str
    action: str
    modified_data: Dict[str, Any] = Field(default_factory=dict)


@app.post("/api/v1/conversations/resume")
@limiter.limit("10/minute")
async def resume_workflow(
    request: Request,
    req_body: ResumeRequest,
    current_user: dict = Depends(require_role("operator")),
):
    """Resume the legacy PostgreSQL-checkpointed graph during migration."""
    if pg_pool is None:
        raise HTTPException(status_code=503, detail="Database is not initialized")
    try:
        graph = await get_compiled_graph(pg_pool)
        config = {"configurable": {"thread_id": req_body.thread_id}}
        if req_body.modified_data:
            await graph.aupdate_state(config, req_body.modified_data)
        config["tags"] = ["langsmith:nostream", f"user:{current_user['username']}"]
        asyncio.create_task(graph.ainvoke(None, config=config))
        return {"status": "resumed", "thread_id": req_body.thread_id}
    except Exception as exc:
        logger.exception("Resume failed")
        raise HTTPException(status_code=500, detail="Resume failed") from exc


class HaltRequest(BaseModel):
    thread_id: str
    reason: str = "Operator intervention"


@app.post("/api/v1/conversations/halt")
@limiter.limit("10/minute")
async def halt_workflow(
    request: Request,
    req_body: HaltRequest,
    current_user: dict = Depends(require_role("operator")),
):
    await halt_manager.broadcast_halt(req_body.thread_id, req_body.reason)
    return {
        "status": "halt_signal_sent",
        "thread_id": req_body.thread_id,
        "requested_by": current_user["username"],
    }


@app.get("/api/v1/conversations/current")
async def get_current_state(
    thread_id: str = "default_session",
    current_user: dict = Depends(require_role("operator")),
):
    """Return the real in-memory graph session state instead of a mock payload."""
    try:
        state = await graph_sessions.state(thread_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"thread_id": thread_id, "state": state, "requested_by": current_user["username"]}
