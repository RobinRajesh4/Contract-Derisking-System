"""
Clause search (retrieval) over a local Qdrant store.

Embeddings come from Ollama, configured in settings.json:
  embedding_model  (default qwen3-embedding:8b)
  embedding_url    (empty = same server as ollama_url)

Each embedding model gets its own Qdrant collection
("contracts__<model>"), so changing the model never mixes vectors of
different sizes or meanings; after a change, POST /admin/reindex fills
the new collection.
"""
import os
import re
import threading
import uuid
from typing import Any, Dict, List, Optional

import requests
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from .llm_providers import get_settings, silence_insecure_warning_if_needed


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QDRANT_DATA_PATH = os.getenv("QDRANT_DATA_PATH", os.path.join(BASE_DIR, "qdrant_data"))

HEADER_ID = "header"

# Qdrant's local (on-disk) mode is not safe for concurrent use: two
# threads writing at once fail or lose points. Uploads, analysis,
# re-indexing and chat all run on worker threads, so every client call
# goes through this lock. Embedding (the slow network part) stays
# outside it.
_QDRANT_LOCK = threading.RLock()

# How each embedding model expects documents and queries to be framed.
# Both models were trained with these prefixes; leaving them off makes
# relevant and irrelevant passages score much closer together.
_QWEN3_QUERY_TASK = (
    "Given a question about one or more contracts, retrieve the contract "
    "passages that answer it"
)


def _doc_text(model: str, text: str) -> str:
    if "nomic-embed" in model:
        return f"search_document: {text}"
    return text


def _query_text(model: str, text: str) -> str:
    if "nomic-embed" in model:
        return f"search_query: {text}"
    if "qwen3-embedding" in model:
        return f"Instruct: {_QWEN3_QUERY_TASK}\nQuery:{text}"
    if "mxbai-embed" in model:
        return f"Represent this sentence for searching relevant passages: {text}"
    return text


def _default_min_score(model: str) -> float:
    # Absolute floor under the relative cut in query(). Scores are only
    # comparable within one model, so the floor is per model family.
    if "nomic-embed" in model:
        return 0.45
    return 0.30


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


class RAGStore:
    def __init__(self) -> None:
        settings = get_settings()
        self.embedding_model = str(settings.get("embedding_model") or "nomic-embed-text")
        self.embedding_url = str(
            settings.get("embedding_url") or settings.get("ollama_url") or "http://127.0.0.1:11434"
        ).rstrip("/")
        self.verify = bool(settings.get("ollama_verify_ssl", True))
        self.min_score = float(
            settings.get("rag_min_score") or _default_min_score(self.embedding_model)
        )
        # Keep results within this distance of the best match; a fixed
        # threshold alone let unrelated clauses through whenever
        # nothing scored well.
        self.relative_margin = float(settings.get("rag_relative_margin", 0.12))
        silence_insecure_warning_if_needed()

        slug = re.sub(r"[^a-z0-9]+", "_", self.embedding_model.lower()).strip("_")
        self.collection = f"contracts__{slug}"

        os.makedirs(QDRANT_DATA_PATH, exist_ok=True)
        with _QDRANT_LOCK:
            self.client = QdrantClient(path=QDRANT_DATA_PATH)

        test_vectors = self.embed(["dimension test"], kind="document")
        if not test_vectors or not test_vectors[0]:
            raise RuntimeError("Ollama returned no embedding vector")
        self.dim = len(test_vectors[0])
        self._ensure_collection()

    # ------------------------------------------------------------ setup

    def _ensure_collection(self) -> None:
        with _QDRANT_LOCK:
            self._ensure_collection_locked()

    def _ensure_collection_locked(self) -> None:
        if self.client.collection_exists(self.collection):
            size = self.client.get_collection(self.collection).config.params.vectors.size
            if size != self.dim:
                raise RuntimeError(
                    f"Collection {self.collection} has vectors of size {size}, but "
                    f"{self.embedding_model} produces {self.dim}. Run POST /admin/reindex "
                    "with reset_index=true."
                )
            return
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=qmodels.VectorParams(size=self.dim, distance=qmodels.Distance.COSINE),
        )

    def reset(self) -> None:
        """
        Remove every point in this model's collection (used by reindex
        and by tests). Deletes points in place rather than dropping and
        recreating the collection: on Windows, Qdrant's on-disk storage
        can fail to release a just-deleted collection's segment files
        before a same-named one is recreated on the same client, so the
        "new" collection silently keeps serving the old data and points
        pile up across resets instead of being cleared.
        """
        with _QDRANT_LOCK:
            if not self.client.collection_exists(self.collection):
                self._ensure_collection_locked()
                return
            self.client.delete(
                collection_name=self.collection,
                points_selector=qmodels.FilterSelector(filter=qmodels.Filter()),
                wait=True,
            )

    def count(self) -> int:
        with _QDRANT_LOCK:
            return self.client.count(self.collection, exact=True).count

    # ------------------------------------------------------------ embed

    def embed(self, texts: List[str], kind: str = "document") -> List[List[float]]:
        """kind: "document" for stored passages, "query" for questions."""
        prepared = [
            (_query_text if kind == "query" else _doc_text)(self.embedding_model, str(t or "").strip())
            for t in texts
        ]
        vectors: List[List[float]] = []
        for start in range(0, len(prepared), 16):
            batch = prepared[start:start + 16]
            try:
                response = requests.post(
                    f"{self.embedding_url}/api/embed",
                    json={"model": self.embedding_model, "input": batch, "truncate": True},
                    timeout=180,
                    verify=self.verify,
                )
                response.raise_for_status()
                data = response.json()
            except requests.RequestException as error:
                raise RuntimeError(
                    f"Could not get embeddings from {self.embedding_url} with "
                    f"{self.embedding_model}: {error}"
                ) from error
            embeddings = data.get("embeddings")
            if not isinstance(embeddings, list) or len(embeddings) != len(batch):
                raise RuntimeError("Ollama returned an unexpected embeddings response")
            vectors.extend([[float(v) for v in e] for e in embeddings])
        return vectors

    # ------------------------------------------------------------ write

    def delete_analysis(self, analysis_id: str) -> None:
        with _QDRANT_LOCK:
            self._delete_locked(analysis_id)

    def _delete_locked(self, analysis_id: str) -> None:
        self.client.delete(
            collection_name=self.collection,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[qmodels.FieldCondition(key="analysis_id", match=qmodels.MatchValue(value=analysis_id))]
                )
            ),
            wait=True,
        )

    def index_analysis(
        self,
        analysis_id: str,
        clauses: List[Dict[str, Any]],
        header: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Replace everything indexed for this analysis with its current
        header and clauses. Replacing (not adding) is what keeps old
        splits of the same document from lingering in search results.
        """
        entries: List[Dict[str, Any]] = []
        if header and str(header.get("text", "")).strip():
            entries.append({"id": HEADER_ID, "text": header["text"], "kind": "header", "metadata": {}})
        for clause in clauses or []:
            if str(clause.get("text", "")).strip():
                entries.append({
                    "id": clause.get("id"),
                    "text": clause["text"],
                    "kind": "clause",
                    "metadata": clause.get("metadata", {}),
                })

        if not entries:
            self.delete_analysis(analysis_id)
            return 0

        vectors = self.embed([e["text"].strip() for e in entries], kind="document")
        points = [
            qmodels.PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{analysis_id}:{e['id']}")),
                vector=vector,
                payload={
                    "analysis_id": analysis_id,
                    "clause_id": e["id"],
                    "kind": e["kind"],
                    "text": e["text"].strip(),
                    "metadata": e["metadata"],
                },
            )
            for e, vector in zip(entries, vectors)
        ]
        # Delete-then-insert under one lock, so a search never sees this
        # contract half-indexed.
        with _QDRANT_LOCK:
            self._delete_locked(analysis_id)
            self.client.upsert(collection_name=self.collection, points=points, wait=True)
        return len(points)

    # Old name, kept so nothing else breaks.
    def upsert_clauses(self, analysis_id: str, clauses: List[Dict[str, Any]]) -> None:
        self.index_analysis(analysis_id, clauses)

    # ------------------------------------------------------------ read

    def query(
        self,
        text: str,
        top_k: int = 5,
        filter_by_analysis: Optional[str] = None,
        exclude_analysis_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Passages related to a question: best match first, near-identical
        text returned once, and anything scoring far below the best
        match (or below the model's floor) dropped.
        """
        query_text = str(text or "").strip()
        if not query_text:
            return []
        vector = self.embed([query_text], kind="query")[0]

        must = []
        if filter_by_analysis:
            must.append(qmodels.FieldCondition(key="analysis_id", match=qmodels.MatchValue(value=filter_by_analysis)))
        must_not = []
        if exclude_analysis_ids:
            must_not.append(qmodels.FieldCondition(key="analysis_id", match=qmodels.MatchAny(any=list(exclude_analysis_ids))))
        query_filter = qmodels.Filter(must=must or None, must_not=must_not or None) if (must or must_not) else None

        limit = max(1, min(int(top_k), 20))
        with _QDRANT_LOCK:
            hits = self.client.query_points(
                collection_name=self.collection,
                query=vector,
                query_filter=query_filter,
                limit=limit * 4,
                with_payload=True,
            ).points
        if not hits:
            return []

        best = float(hits[0].score)
        cutoff = max(self.min_score, best - self.relative_margin)
        seen = set()
        output: List[Dict[str, Any]] = []
        for hit in hits:
            score = float(hit.score)
            if score < cutoff:
                break
            payload = hit.payload or {}
            # Same wording repeated inside one contract (e.g. a page
            # printed twice) is returned once. Identical wording in two
            # different contracts stays as two sources: each is a real,
            # separate place the answer can point to.
            text_key = _normalize(payload.get("text", ""))
            key = (payload.get("analysis_id"), text_key)
            if not text_key or key in seen:
                continue
            seen.add(key)
            output.append({
                "text": payload.get("text", ""),
                "analysis_id": payload.get("analysis_id"),
                "clause_id": payload.get("clause_id"),
                "kind": payload.get("kind", "clause"),
                "metadata": payload.get("metadata", {}),
                "score": score,
            })
            if len(output) >= limit:
                break
        return output
