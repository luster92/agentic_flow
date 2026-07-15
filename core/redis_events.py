import asyncio
import json
import logging
import redis.asyncio as redis

logger = logging.getLogger(__name__)

class HaltManager:
    """
    Redis Pub/Sub을 활용한 실시간 워크플로우 중단(Halt) 신호 관리자
    """
    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.redis_url = redis_url
        self.redis_client = None
        self.pubsub = None
        self._listener_task = None
        # session_id -> halt_requested flag
        self.halt_flags: dict[str, bool] = {}

    async def connect(self):
        self.redis_client = redis.from_url(self.redis_url)
        self.pubsub = self.redis_client.pubsub()
        await self.pubsub.subscribe("clawflow_halt_events")
        logger.info("📡 Redis Pub/Sub connected for Halt events.")
        
        self._listener_task = asyncio.create_task(self._listen())

    async def _listen(self):
        try:
            async for message in self.pubsub.listen():
                if message["type"] == "message":
                    data = json.loads(message["data"])
                    session_id = data.get("session_id")
                    if session_id:
                        logger.warning(f"🛑 HALT RECEIVED for session: {session_id}")
                        self.halt_flags[session_id] = True
        except asyncio.CancelledError:
            logger.info("Halt listener task cancelled.")
        except Exception as e:
            logger.error(f"Halt listener error: {e}")

    async def close(self):
        if self._listener_task:
            self._listener_task.cancel()
        if self.pubsub:
            await self.pubsub.unsubscribe("clawflow_halt_events")
            await self.pubsub.close()
        if self.redis_client:
            await self.redis_client.aclose()

    def is_halt_requested(self, session_id: str) -> bool:
        """라우터 또는 노드에서 매 스텝 검사"""
        return self.halt_flags.get(session_id, False)

    def clear_halt(self, session_id: str):
        if session_id in self.halt_flags:
            del self.halt_flags[session_id]

    async def broadcast_halt(self, session_id: str, reason: str = "Operator intervention"):
        """외부 패널(API)에서 강제 중단을 요청할 때 호출"""
        if self.redis_client:
            payload = json.dumps({"session_id": session_id, "reason": reason})
            await self.redis_client.publish("clawflow_halt_events", payload)
            logger.info(f"📣 Broadcasted HALT for {session_id}")

# 글로벌 인스턴스
halt_manager = HaltManager()
