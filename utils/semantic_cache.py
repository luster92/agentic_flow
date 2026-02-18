"""
Semantic Cache — 시맨틱 캐싱 레이어
=====================================
ChromaDB 기반 벡터 유사도를 활용한 응답 캐싱.

동일/유사 질문에 대해 LLM 호출 없이 즉시 응답을 반환합니다.
정적 정보(FAQ, 요금제 등)에만 캐시를 적용하고
동적 정보(코드 구현, 디버깅 등)는 bypass합니다.

핵심 원칙: "같은 질문에 두 번 생각하지 마라."
"""

import re
import logging
import uuid
from typing import Optional

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# ── 설정 ────────────────────────────────────────────────────────
CACHE_DB_DIR = "db_cache"
CACHE_COLLECTION = "response_cache"
DEFAULT_THRESHOLD = 0.95  # 코사인 유사도 임계값

# 캐싱 불가 패턴 (동적/코드 관련 요청)
NON_CACHEABLE_PATTERNS = [
    r"(코드|code|구현|implement|작성|write|debug|디버깅|fix|수정)",
    r"(파일|file|프로젝트|project).*\.(py|ts|js|yaml|json|md)",
    r"\[ESCALATE\]",
    r"(리팩토링|refactor)",
    r"^/",  # CLI 명령어
]


class SemanticCache:
    """ChromaDB 기반 시맨틱 응답 캐시.

    유사도가 threshold를 넘는 과거 응답을 즉시 반환하여
    LLM 호출을 완전히 생략합니다 (Short-Circuit).

    Attributes:
        threshold: 캐시 히트로 판정할 최소 코사인 유사도 (기본 0.95)
    """

    def __init__(
        self,
        db_dir: str = CACHE_DB_DIR,
        threshold: float = DEFAULT_THRESHOLD,
        encoder: Optional[SentenceTransformer] = None,
    ):
        self.threshold = threshold
        self._enabled = True

        try:
            self.client = chromadb.PersistentClient(path=db_dir)
            # 인코더는 외부 주입 가능 (VectorMemory와 공유)
            self.encoder = encoder or SentenceTransformer("all-MiniLM-L6-v2")
            self.collection = self.client.get_or_create_collection(
                name=CACHE_COLLECTION,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(
                f"💾 Semantic Cache 초기화 완료 "
                f"(threshold={self.threshold}, entries={self.collection.count()})"
            )
        except Exception as e:
            logger.error(f"❌ Semantic Cache 초기화 실패: {e}")
            self._enabled = False
            self.collection = None

    def get(self, query: str) -> Optional[str]:
        """캐시에서 유사한 쿼리의 응답을 조회합니다.

        Args:
            query: 사용자 입력 쿼리

        Returns:
            유사도 threshold를 넘는 캐시된 응답, 없으면 None
        """
        if not self._enabled or not self.collection:
            return None

        if not self._is_cacheable(query):
            logger.debug("🔄 Cache bypass: 동적 요청 감지")
            return None

        try:
            embedding = self.encoder.encode(query).tolist()
            results = self.collection.query(
                query_embeddings=[embedding],
                n_results=1,
            )

            if not results["ids"] or not results["ids"][0]:
                return None

            # ChromaDB는 cosine distance를 반환 (0 = 동일, 2 = 완전 반대)
            # 유사도 = 1 - distance
            distance = results["distances"][0][0]
            similarity = 1 - distance

            if similarity >= self.threshold:
                cached_response = results["documents"][0][0]
                logger.info(
                    f"✨ Cache HIT! (유사도: {similarity:.4f} ≥ {self.threshold})"
                )
                return cached_response

            logger.debug(
                f"🔄 Cache MISS (유사도: {similarity:.4f} < {self.threshold})"
            )
            return None

        except Exception as e:
            logger.error(f"❌ Cache 조회 실패: {e}")
            return None

    def put(self, query: str, response: str) -> None:
        """쿼리-응답 쌍을 캐시에 저장합니다.

        Args:
            query: 사용자 입력 쿼리
            response: LLM이 생성한 응답
        """
        if not self._enabled or not self.collection:
            return

        if not self._is_cacheable(query):
            return

        try:
            embedding = self.encoder.encode(query).tolist()
            doc_id = str(uuid.uuid4())

            self.collection.add(
                documents=[response],
                embeddings=[embedding],
                metadatas=[{"query": query[:500]}],
                ids=[doc_id],
            )
            logger.debug(f"💾 Cache stored: {doc_id}")

        except Exception as e:
            logger.error(f"❌ Cache 저장 실패: {e}")

    def _is_cacheable(self, query: str) -> bool:
        """쿼리가 캐싱 가능한지 판단합니다.

        코드 구현, 디버깅 등 동적 요청은 캐싱하지 않습니다.
        """
        for pattern in NON_CACHEABLE_PATTERNS:
            if re.search(pattern, query, re.IGNORECASE):
                return False
        return True

    def count(self) -> int:
        """캐시된 항목 수를 반환합니다."""
        if self.collection:
            return self.collection.count()
        return 0

    def clear(self) -> None:
        """캐시를 초기화합니다."""
        if self._enabled and self.client:
            self.client.delete_collection(CACHE_COLLECTION)
            self.collection = self.client.get_or_create_collection(
                name=CACHE_COLLECTION,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info("🗑️ Semantic Cache 초기화 완료")
