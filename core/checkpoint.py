"""
CheckpointManager — SQLite 기반 영속적 체크포인팅
=================================================
에이전트 상태를 DB에 저장하고 특정 시점으로 롤백할 수 있습니다.

체크포인트 유형:
- TRANSACTION: 외부 도구 호출 전/후 (자동, 재시도용)
- MILESTONE: 논리적 과업 단위 (수동/자동, 복구 지점)
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

from core.state import AgentState, CheckpointType

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────
DEFAULT_DB_DIR = "history"
CHECKPOINT_DB_FILENAME = "checkpoints.db"


class CheckpointManager:
    """SQLite 기반 체크포인트 관리자.

    에이전트 상태를 직렬화하여 DB에 저장/복원합니다.
    """

    def __init__(self, db_dir: str = DEFAULT_DB_DIR) -> None:
        self.db_dir = db_dir
        if not os.path.exists(self.db_dir):
            os.makedirs(self.db_dir)

        self.db_path = os.path.join(self.db_dir, CHECKPOINT_DB_FILENAME)
        self._init_db()
        logger.info(f"💾 CheckpointManager initialized (DB: {self.db_path})")

    def _init_db(self) -> None:
        """체크포인트 테이블 스키마 초기화."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS checkpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    step_number INTEGER NOT NULL,
                    checkpoint_type TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    label TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(session_id, step_number, checkpoint_type)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_checkpoints_session
                ON checkpoints(session_id, step_number)
            """)
            conn.commit()
        finally:
            conn.close()

    def save_checkpoint(
        self,
        state: AgentState,
        checkpoint_type: CheckpointType = CheckpointType.TRANSACTION,
        label: str = "",
    ) -> int:
        """상태를 체크포인트로 저장합니다.

        Args:
            state: 저장할 에이전트 상태
            checkpoint_type: TRANSACTION 또는 MILESTONE
            label: 마일스톤 레이블 (예: '자료 조사 완료')

        Returns:
            생성된 체크포인트 ID
        """
        state_json = state.model_dump_json()
        now = datetime.now(timezone.utc).isoformat()

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                """
                INSERT OR REPLACE INTO checkpoints
                    (session_id, step_number, checkpoint_type, state_json, label, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    state.session_id,
                    state.step,
                    checkpoint_type.value,
                    state_json,
                    label,
                    now,
                ),
            )
            conn.commit()
            checkpoint_id = cursor.lastrowid or 0

            logger.info(
                f"💾 Checkpoint saved: session={state.session_id[:8]}... "
                f"step={state.step} type={checkpoint_type.value} "
                f"label='{label}' id={checkpoint_id}"
            )
            return checkpoint_id

        except Exception as e:
            logger.error(f"❌ Checkpoint save failed: {e}")
            raise
        finally:
            conn.close()

    def load_checkpoint(
        self,
        session_id: str,
        step: int | None = None,
    ) -> AgentState | None:
        """체크포인트에서 상태를 복원합니다.

        Args:
            session_id: 세션 UUID
            step: 특정 단계 (None이면 최신 상태)

        Returns:
            복원된 AgentState 또는 None
        """
        conn = sqlite3.connect(self.db_path)
        try:
            if step is not None:
                row = conn.execute(
                    """
                    SELECT state_json FROM checkpoints
                    WHERE session_id = ? AND step_number = ?
                    ORDER BY id DESC LIMIT 1
                    """,
                    (session_id, step),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT state_json FROM checkpoints
                    WHERE session_id = ?
                    ORDER BY step_number DESC, id DESC LIMIT 1
                    """,
                    (session_id,),
                ).fetchone()

            if row is None:
                logger.warning(
                    f"⚠️ No checkpoint found: session={session_id[:8]}... "
                    f"step={step}"
                )
                return None

            state = AgentState.model_validate_json(row[0])
            logger.info(
                f"📂 Checkpoint loaded: session={session_id[:8]}... "
                f"step={state.step}"
            )
            return state

        except Exception as e:
            logger.error(f"❌ Checkpoint load failed: {e}")
            return None
        finally:
            conn.close()

    def list_checkpoints(
        self,
        session_id: str,
    ) -> list[dict[str, Any]]:
        """세션의 체크포인트 목록을 반환합니다.

        Args:
            session_id: 세션 UUID

        Returns:
            체크포인트 정보 리스트 [{id, step, type, label, created_at}]
        """
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT id, step_number, checkpoint_type, label, created_at
                FROM checkpoints
                WHERE session_id = ?
                ORDER BY step_number ASC, id ASC
                """,
                (session_id,),
            ).fetchall()

            return [
                {
                    "id": r[0],
                    "step": r[1],
                    "type": r[2],
                    "label": r[3],
                    "created_at": r[4],
                }
                for r in rows
            ]

        finally:
            conn.close()

    def rollback(
        self,
        session_id: str,
        step: int,
    ) -> AgentState | None:
        """특정 단계의 체크포인트로 롤백합니다.

        해당 단계 이후의 체크포인트는 모두 삭제됩니다.

        Args:
            session_id: 세션 UUID
            step: 롤백할 단계 번호

        Returns:
            복원된 AgentState 또는 None
        """
        state = self.load_checkpoint(session_id, step)
        if state is None:
            return None

        # 롤백 대상 이후 체크포인트 삭제
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                DELETE FROM checkpoints
                WHERE session_id = ? AND step_number > ?
                """,
                (session_id, step),
            )
            conn.commit()
            logger.info(
                f"⏪ Rolled back to step {step}: "
                f"session={session_id[:8]}..."
            )
        finally:
            conn.close()

        return state

    def delete_session(self, session_id: str) -> int:
        """세션의 모든 체크포인트를 삭제합니다.

        Returns:
            삭제된 행 수
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                "DELETE FROM checkpoints WHERE session_id = ?",
                (session_id,),
            )
            conn.commit()
            deleted = cursor.rowcount
            logger.info(
                f"🗑️ Session checkpoints deleted: "
                f"session={session_id[:8]}... count={deleted}"
            )
            return deleted
        finally:
            conn.close()
