"""
History Manager (SQLite)
========================
대화 기록 관리 모듈:
- SQLite 기반 영속화 (데이터 무결성 및 검색 성능 확보)
- 프로젝트별 레코드 관리 (projects 테이블)
- 메시지 이력 관리 (messages 테이블)
- 기존 JSONL 파일 자동 마이그레이션 지원
"""

import json
import os
import glob
import logging
import sqlite3
from datetime import datetime, timezone
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_HISTORY_DIR = "history"
DEFAULT_CONTEXT_WINDOW = 20
DB_FILENAME = "agentic_flow.db"


class HistoryManager:
    """
    SQLite 기반 대화 기록 관리자.
    """

    def __init__(
        self,
        project_name: str = "default",
        base_dir: str = DEFAULT_HISTORY_DIR,
        context_window: int = DEFAULT_CONTEXT_WINDOW,
    ):
        self.project_name = project_name
        self.base_dir = base_dir
        self.context_window = context_window
        self.db_path = os.path.join(self.base_dir, DB_FILENAME)
        
        # 디렉토리 생성
        if not os.path.exists(self.base_dir):
            os.makedirs(self.base_dir)

        # DB 초기화 및 프로젝트 ID 로드
        self._init_db()
        self.project_id = self._get_or_create_project_id()
        
        # 레거시 데이터 마이그레이션 확인
        self._check_legacy_migration()

    def _init_db(self) -> None:
        """데이터베이스 테이블 스키마 초기화."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT  -- JSON string
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT, -- JSON string
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                )
            """)
            # 인덱스 추가 (조회 성능 최적화)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_project_id ON messages(project_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp)")

    def _get_or_create_project_id(self) -> int:
        """프로젝트 이름을 ID로 변환 (없으면 생성)."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT id FROM projects WHERE name = ?", (self.project_name,))
            row = cursor.fetchone()
            if row:
                return row[0]
            
            # 새 프로젝트 생성
            cursor = conn.execute(
                "INSERT INTO projects (name, metadata) VALUES (?, ?)",
                (self.project_name, "{}")
            )
            return cursor.lastrowid

    def add_message(self, role: str, content: str, metadata: dict | None = None) -> None:
        """메시지 추가."""
        ts = datetime.now(timezone.utc).isoformat()
        meta_json = json.dumps(metadata, ensure_ascii=False) if metadata else None
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO messages (project_id, role, content, timestamp, metadata)
                VALUES (?, ?, ?, ?, ?)
                """,
                (self.project_id, role, content, ts, meta_json)
            )
        logger.debug(f"📝 메시지 DB 저장 ({self.project_name}): {role}")

    def get_context(self, window_size: int | None = None) -> list[dict]:
        """최근 메시지 조회 (컨텍스트 윈도우용)."""
        limit = window_size or self.context_window
        
        with sqlite3.connect(self.db_path) as conn:
            # 최근 N개를 가져오기 위해 정렬 후 서브쿼리 활용 가능하지만,
            # 편의상 역순 조회 후 Python에서 뒤집는다.
            cursor = conn.execute(
                """
                SELECT role, content 
                FROM messages 
                WHERE project_id = ? AND role IN ('user', 'assistant', 'system')
                ORDER BY id DESC LIMIT ?
                """,
                (self.project_id, limit)
            )
            rows = cursor.fetchall()
        
        # 최신순(DESC) 결과를 시간순(ASC)으로 뒤집기
        return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

    def get_full_history(self) -> list[dict]:
        """전체 대화 기록 조회 (메타데이터 포함)."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT role, content, timestamp, metadata 
                FROM messages 
                WHERE project_id = ? 
                ORDER BY id ASC
                """,
                (self.project_id,)
            )
            rows = cursor.fetchall()
            
        result = []
        for r in rows:
            meta = json.loads(r[3]) if r[3] else None
            result.append({
                "role": r[0],
                "content": r[1],
                "timestamp": r[2],
                "metadata": meta
            })
        return result

    def clear(self) -> None:
        """현재 프로젝트의 메시지 기록 삭제 (초기화)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM messages WHERE project_id = ?", (self.project_id,))
        logger.info(f"🗑️ 대화 기록 초기화됨 ({self.project_name})")

    def get_stats(self) -> dict:
        """통계 정보 조회."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT role, COUNT(*) FROM messages WHERE project_id = ? GROUP BY role",
                (self.project_id,)
            )
            by_role = dict(cursor.fetchall())
            
            total = sum(by_role.values())
        
        return {
            "project": self.project_name,
            "total_messages": total,
            "by_role": by_role,
            "file_path": self.db_path,
        }

    @staticmethod
    def list_projects(base_dir: str = DEFAULT_HISTORY_DIR) -> list[str]:
        """DB에 저장된 프로젝트 목록 조회."""
        db_path = os.path.join(base_dir, DB_FILENAME)
        if not os.path.exists(db_path):
            return []
            
        try:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.execute("SELECT name FROM projects ORDER BY name")
                return [row[0] for row in cursor.fetchall()]
        except sqlite3.Error:
            return []

    # ── Legacy Migration ──────────────────────────────────────────

    def _check_legacy_migration(self) -> None:
        """
        동일한 이름의 .jsonl 파일이 있고 DB가 비어있다면 마이그레이션 수행.
        """
        jsonl_path = os.path.join(self.base_dir, f"{self.project_name}.jsonl")
        if not os.path.exists(jsonl_path):
            return
            
        # DB에 메시지가 이미 있는지 확인
        if self.get_stats()["total_messages"] > 0:
            return

        logger.info(f"🔄 JSONL 마이그레이션 시작: {jsonl_path} → SQLite")
        try:
            with open(jsonl_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                
            with sqlite3.connect(self.db_path) as conn:
                for line in lines:
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    meta_str = json.dumps(data.get("metadata", {}), ensure_ascii=False)
                    conn.execute(
                        """
                        INSERT INTO messages (project_id, role, content, timestamp, metadata)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (self.project_id, data["role"], data["content"], data.get("timestamp"), meta_str)
                    )
            
            # 마이그레이션 후 원본 파일 백업 (이름 변경)
            os.rename(jsonl_path, jsonl_path + ".bak")
            logger.info("✅ 마이그레이션 완료 (원본 .bak 처리됨)")
            
        except Exception as e:
            logger.error(f"❌ 마이그레이션 실패: {e}")

    # ── Semantic Context Filtering & Compression ────────────────────

    async def compress_old_memories(
        self,
        threshold_msgs: int = 40,
        compress_count: int = 20,
        base_url: str = "http://localhost:4000"
    ) -> bool:
        """
        오래된 메시지가 특정 개수(threshold_msgs)를 초과하면, 가장 오래된 N개(compress_count)를
        Dense English (의미론적 축약 언어)로 압축하여 단일 블록으로 치환합니다.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE project_id = ?",
                (self.project_id,)
            )
            total = cursor.fetchone()[0]
            
        if total <= threshold_msgs:
            return False
            
        with sqlite3.connect(self.db_path) as conn:
            # 보존할 시스템 프롬프트(최상단) 등은 정책에 따라 다를 수 있으나,
            # 여기서는 단순히 시간순으로 가장 오래된 일반 대화/도구 결과를 가져옵니다.
            cursor = conn.execute(
                "SELECT id, role, content, timestamp FROM messages WHERE project_id = ? ORDER BY id ASC LIMIT ?",
                (self.project_id, compress_count)
            )
            rows = cursor.fetchall()
            
        if not rows:
            return False
            
        # 1. 텍스트 직렬화
        text_to_compress = []
        for r in rows:
            text_to_compress.append(f"[{r[1]}] {r[2]}")
        conversation_text = "\\n".join(text_to_compress)
        
        # 2. LLM 호출 (로컬 경량 모델)
        from openai import AsyncOpenAI
        client = AsyncOpenAI(base_url=base_url, api_key="not-needed")
        
        system_prompt = (
            "You are a semantic memory compressor. "
            "Compress the following conversation log into extremely dense English shorthand. "
            "Focus only on facts, decisions, context, and constraints. "
            "Omit all conversational filler, grammar, and polite words. "
            "Use dense formats like 'req:auth|db:ok|err:timeout'. Do NOT use full sentences. "
            "Maximize token efficiency while preserving factual integrity."
        )
        
        try:
            response = await client.chat.completions.create(
                model="local-helper",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": conversation_text},
                ],
                temperature=0.1,
                max_tokens=1024,
            )
            compressed_result = response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"❌ 메모리 압축 실패: {e}")
            return False
            
        if not compressed_result:
            return False
            
        final_content = f"[COMPRESSED_MEMORY]\\n{compressed_result}"
        # 가장 최근 압축 메시지의 timestamp를 사용해 정렬 유지
        last_timestamp = rows[-1][3]
        ids_to_delete = [r[0] for r in rows]
        
        # 3. DB 교체 트랜잭션 (원래 순서를 유지하기 위해 첫 번째 행을 재활용)
        with sqlite3.connect(self.db_path) as conn:
            keep_id = ids_to_delete[0]
            delete_ids = ids_to_delete[1:]
            
            # 첫 번째 메시지를 압축 블록으로 업데이트
            conn.execute(
                "UPDATE messages SET role = ?, content = ?, timestamp = ?, metadata = ? WHERE id = ?",
                ("system", final_content, last_timestamp, None, keep_id)
            )
            
            # 나머지 병합된 메시지 삭제
            if delete_ids:
                placeholders = ",".join(["?"] * len(delete_ids))
                conn.execute(
                    f"DELETE FROM messages WHERE id IN ({placeholders})",
                    delete_ids
                )
            
        logger.info(f"🗜️ 과거 메시지 {len(ids_to_delete)}개를 1개의 의미론적 압축(Dense) 블록으로 치환했습니다.")
        return True

    def get_summarized_context(self, max_recent: int = 3) -> dict:
        """핸드오프용 요약 컨텍스트를 반환합니다.

        전체 대화 로그 대신 핵심 정보만 추려서 반환함으로써
        컨텍스트 오염을 방지하고 토큰을 절약합니다.

        Args:
            max_recent: 최근 메시지 포함 개수

        Returns:
            dict: {
                "summary": str,        # 대화 핵심 요약
                "entities": dict,      # 추출된 핵심 데이터
                "recent_messages": list # 최근 N턴 메시지
            }
        """
        full = self.get_full_history()

        # 최근 메시지 추출
        recent = full[-max_recent:] if full else []
        recent_msgs = [{"role": m["role"], "content": m["content"]} for m in recent]

        # 핵심 정보 추출: routing 및 handler 메타데이터에서 엔티티 수집
        entities: dict[str, str] = {}
        key_points: list[str] = []

        for msg in full:
            meta = msg.get("metadata") or {}

            # 라우팅 결정 기록
            if meta.get("type") == "routing":
                key_points.append(f"[Routing] {msg['content']}")

            # 핸들러 정보
            handler = meta.get("handler", "")
            if handler:
                entities["last_handler"] = handler

            # 에스컬레이션 사유
            esc_reason = meta.get("reason", "")
            if esc_reason and meta.get("handler"):
                entities["escalation_reason"] = esc_reason

        # 사용자 메시지에서 첫 요청과 마지막 요청 요약
        user_msgs = [m for m in full if m["role"] == "user"]
        if user_msgs:
            entities["first_request"] = user_msgs[0]["content"][:200]
            if len(user_msgs) > 1:
                entities["latest_request"] = user_msgs[-1]["content"][:200]

        # 요약 문자열 생성
        summary_parts = []
        if entities.get("first_request"):
            summary_parts.append(f"초기 요청: {entities['first_request'][:100]}")
        if key_points:
            summary_parts.append(f"라우팅 이력: {len(key_points)}건")
        summary_parts.append(f"총 {len(full)}턴 대화 진행")

        return {
            "summary": " | ".join(summary_parts),
            "entities": entities,
            "recent_messages": recent_msgs,
        }

    # ── Metadata Methods ──────────────────────────────────────────

    def set_metadata(self, **kwargs) -> None:
        """프로젝트 메타데이터 업데이트."""
        current = self.get_metadata()
        current.update(kwargs)
        json_str = json.dumps(current, ensure_ascii=False)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE projects SET metadata = ? WHERE id = ?",
                (json_str, self.project_id)
            )

    def get_metadata(self) -> dict:
        """프로젝트 메타데이터 조회."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT metadata FROM projects WHERE id = ?", (self.project_id,))
            row = cursor.fetchone()
            if row and row[0]:
                return json.loads(row[0])
            return {}
