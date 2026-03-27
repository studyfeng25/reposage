"""ChromaDB vector store for semantic search."""
import logging
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


def _make_embedding_text(symbol: Dict) -> str:
    parts = [symbol.get("name", ""), symbol.get("type", "")]
    sig = symbol.get("signature", "")
    if sig:
        parts.append(sig)
    doc = symbol.get("doc_comment", "")
    if doc:
        parts.append(doc[:300])
    summary = symbol.get("summary", "")
    if summary:
        parts.append(summary)
    return " | ".join(p for p in parts if p)


class VectorStore:
    def __init__(self, store_path: Path, repo_name: str):
        self.store_path = store_path
        self.collection_name = f"reposage_{repo_name[:40]}"
        self._client = None
        self._collection = None

    def _get_collection(self):
        if self._collection is not None:
            return self._collection
        try:
            import chromadb
            self._client = chromadb.PersistentClient(path=str(self.store_path))
            self._collection = self._client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as e:
            logger.error(f"ChromaDB init failed: {e}")
            self._collection = None
        return self._collection

    def upsert_symbols(self, symbols: List[Dict]):
        """Add or update symbol embeddings."""
        collection = self._get_collection()
        if not collection or not symbols:
            return

        ids = [s["id"] for s in symbols]
        documents = [_make_embedding_text(s) for s in symbols]
        metadatas = [
            {
                "name": s.get("name", ""),
                "type": s.get("type", ""),
                "file": s.get("file", ""),
                "language": s.get("language", ""),
                "start_line": s.get("start_line", 0),
            }
            for s in symbols
        ]

        BATCH = 100
        for i in range(0, len(ids), BATCH):
            try:
                collection.upsert(
                    ids=ids[i:i + BATCH],
                    documents=documents[i:i + BATCH],
                    metadatas=metadatas[i:i + BATCH],
                )
            except Exception as e:
                logger.warning(f"Upsert batch {i} failed: {e}")

    def delete_symbols(self, symbol_ids: List[str]):
        collection = self._get_collection()
        if not collection or not symbol_ids:
            return
        try:
            collection.delete(ids=symbol_ids)
        except Exception as e:
            logger.warning(f"Delete failed: {e}")

    def search(self, query: str, limit: int = 10,
               language: Optional[str] = None) -> List[Dict]:
        collection = self._get_collection()
        if not collection:
            return []
        try:
            where = {"language": language} if language else None
            results = collection.query(
                query_texts=[query],
                n_results=min(limit, 50),
                where=where,
                include=["documents", "metadatas", "distances"],
            )
            output = []
            if results and results["ids"]:
                for idx, sid in enumerate(results["ids"][0]):
                    output.append({
                        "id": sid,
                        "score": 1.0 - (results["distances"][0][idx] or 0),
                        **results["metadatas"][0][idx],
                    })
            return output
        except Exception as e:
            logger.warning(f"Vector search failed: {e}")
            return []

    def count(self) -> int:
        collection = self._get_collection()
        if not collection:
            return 0
        try:
            return collection.count()
        except Exception:
            return 0
