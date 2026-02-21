import asyncio
import logging
from typing import Any, Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Depends
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

# Prometheus & OpenTelemetry imports
import prometheus_client
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# Security & Rate Limiting
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from core.auth import get_current_user, require_role, create_access_token, verify_password, get_password_hash

from core.redis_events import halt_manager
from core.graph import get_compiled_graph
from psycopg_pool import AsyncConnectionPool

# Setup Rate Limiter
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Clawflow Enterprise HITL API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount OpenTelemetry instrumentation for ASGI
FastAPIInstrumentor.instrument_app(app)

# Prometheus /metrics endpoint
@app.get("/metrics", response_class=PlainTextResponse)
def metrics():
    return prometheus_client.generate_latest()

# Postgres connection pool (should be injected or initialized on startup)
pg_pool: AsyncConnectionPool = None

@app.on_event("startup")
async def startup_event():
    global pg_pool
    # Initialize connection pool
    pg_pool = AsyncConnectionPool(
        conninfo="postgresql://postgres:postgres@localhost:5432/clawflow",
        max_size=20,
        kwargs={"autocommit": True}
    )
    
    # Init DB and seed admin user if not exists
    async with pg_pool.connection() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password VARCHAR(255) NOT NULL,
                role VARCHAR(20) NOT NULL DEFAULT 'operator'
            )
        """)
        # Seed default admin if user table is empty
        async with conn.cursor() as cur:
            await cur.execute("SELECT COUNT(*) FROM users")
            count = (await cur.fetchone())[0]
            if count == 0:
                admin_hash = get_password_hash("admin123")
                operator_hash = get_password_hash("operator123")
                await cur.executemany(
                    "INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
                    [
                        ("admin", admin_hash, "admin"),
                        ("operator", operator_hash, "operator")
                    ]
                )
                logging.getLogger("api").info("Seeded default users: admin, operator")

    await halt_manager.connect()
    
@app.on_event("shutdown")
async def shutdown_event():
    if pg_pool:
        await pg_pool.close()
    await halt_manager.close()

# ── Auth Endpoints ──
class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/api/v1/auth/login")
@limiter.limit("5/minute")
async def login(request: Request, login_data: LoginRequest):
    async with pg_pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT password, role FROM users WHERE username = %s",
                (login_data.username,)
            )
            user_record = await cur.fetchone()
            
    if not user_record or not verify_password(login_data.password, user_record[0]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    token = create_access_token(data={"sub": login_data.username, "role": user_record[1]})
    return {"access_token": token, "token_type": "bearer"}

# ── 1. WebSocket / Pending Status ──
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
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
            data = await websocket.receive_text()
            # client can send ping or other msgs
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# ── 2. REST Endpoints for HITL ──
class ResumeRequest(BaseModel):
    thread_id: str
    action: str  # e.g., "approve", "modify"
    modified_data: Dict[str, Any] = {}

@app.post("/api/v1/conversations/resume")
@limiter.limit("10/minute")
async def resume_workflow(
    request: Request,
    req_body: ResumeRequest,
    current_user: dict = Depends(require_role("operator"))
):
    """
    일시 정지(Pause)된 워크플로우를 승인하거나 상태를 수정하여 재개합니다. (JWT Protected)
    """
    try:
        graph = await get_compiled_graph(pg_pool)
        config = {"configurable": {"thread_id": req_body.thread_id}}
        
        # Resume the graph by passing None or modified data
        # In LangGraph, passing None to stream/invoke resumes from the interrupt
        # If we need to update state before resuming:
        if req_body.modified_data:
            await graph.aupdate_state(config, req_body.modified_data)
            
        # We can kick off the task in the background, adding langsmith:nostream tag
        config["tags"] = ["langsmith:nostream", f"user:{current_user['username']}"]
        asyncio.create_task(graph.ainvoke(None, config=config))
        
        return {"status": "resumed", "thread_id": req_body.thread_id}
    except Exception as e:
        logger.error(f"Resume failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class HaltRequest(BaseModel):
    thread_id: str
    reason: str = "Operator intervention"

@app.post("/api/v1/conversations/halt")
@limiter.limit("10/minute")
async def halt_workflow(
    request: Request,
    req_body: HaltRequest,
    current_user: dict = Depends(require_role("operator"))
):
    """
    Redis Pub/Sub을 통해 특정 세션의 연산을 즉시 강제 중단(Halt)합니다. (JWT Protected)
    """
    await halt_manager.broadcast_halt(req_body.thread_id, req_body.reason)
    return {"status": "halt_signal_sent", "thread_id": req_body.thread_id}

@app.get("/api/v1/conversations/current")
async def get_current_state(thread_id: str = "default_session"):
    """
    Dashboard UI에서 폴링하기 위한 현재 에이전트 상태 Mock 엔드포인트.
    실제 구현 시 CheckpointManager나 Graph State에서 가져와야 합니다.
    """
    # 임시 반환값. 실제로는 db_dir에서 파일 읽기/DB 조회 처리
    return {
        "session_id": thread_id,
        "step": 5,
        "status": "SUSPENDED",
        "current_agent": "worker",
        "active_persona": "Senior Architect",
        "hitl_context": {
            "reason": "작업 승인 대기 중 (인터럽트)",
            "suspended_at": "2026-02-20T12:00:00Z",
            "args": {"action": "execute_code"}
        }
    }
