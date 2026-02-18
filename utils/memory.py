"""
Vector Memory Module
====================
Long-term Memory System for Agents.
Uses ChromaDB for vector storage and Sentence-Transformers for local embeddings.

Capabilities:
- Store text with metadata (Task, Solution, Confidence)
- Semantic search to retrieve relevant past experiences
- Automatic persistence
"""

import os
import logging
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
import uuid

logger = logging.getLogger(__name__)

# Constants
DB_DIR = "db"
COLLECTION_NAME = "agent_knowledge"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # Fast & Efficient for local use

class VectorMemory:
    """
    Persistent Vector Memory using ChromaDB.
    """
    
    def __init__(self, db_dir: str = DB_DIR):
        self.db_dir = db_dir
        if not os.path.exists(self.db_dir):
            os.makedirs(self.db_dir)

        try:
            # Initialize ChromaDB Client (Persistent)
            self.client = chromadb.PersistentClient(path=self.db_dir)
            
            # Initialize Embedding Model (Lazy Loading could be better, but we need it ready)
            logger.info(f"🧠 Loading Embedding Model: {EMBEDDING_MODEL} (DB: {self.db_dir})...")
            self.encoder = SentenceTransformer(EMBEDDING_MODEL)
            
            # Get or Create Collection
            self.collection = self.client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"}
            )
            logger.info(f"🧠 Vector Memory Initialized (Collection: {COLLECTION_NAME})")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize Vector Memory: {e}")
            self.client = None
            self.collection = None

    def add(self, text: str, metadata: dict | None = None) -> str:
        """
        Add a text entry to the memory.
        """
        if not self.collection:
            return ""

        try:
            doc_id = str(uuid.uuid4())
            embedding = self.encoder.encode(text).tolist()
            
            # Ensure metadata is flat and values are supported types
            safe_metadata = {}
            if metadata:
                for k, v in metadata.items():
                    if isinstance(v, (str, int, float, bool)):
                        safe_metadata[k] = v
                    else:
                        safe_metadata[k] = str(v)
            
            self.collection.add(
                documents=[text],
                embeddings=[embedding],
                metadatas=[safe_metadata],
                ids=[doc_id]
            )
            logger.debug(f"🧠 Memory stored: {doc_id}")
            return doc_id
            
        except Exception as e:
            logger.error(f"❌ Failed to add memory: {e}")
            return ""

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        """
        Search for semantically similar entries.
        """
        if not self.collection:
            return []

        try:
            query_embedding = self.encoder.encode(query).tolist()
            
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k
            )
            
            # Format results
            memories = []
            if results["ids"]:
                for i in range(len(results["ids"][0])):
                    memories.append({
                        "id": results["ids"][0][i],
                        "text": results["documents"][0][i],
                        "metadata": results["metadatas"][0][i],
                        "distance": results["distances"][0][i] if results["distances"] else 0.0
                    })
            
            # Filter by relevance (optional threshold)
            return memories
            
        except Exception as e:
            logger.error(f"❌ Failed to search memory: {e}")
            return []

    def count(self) -> int:
        if self.collection:
            return self.collection.count()
        return 0

# Global Instance
global_memory = VectorMemory()
