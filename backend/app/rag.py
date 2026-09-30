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
import time
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

_EMBED_ATTEMPTS = 3
_EMBED_BACKOFF_SEC = 2.0

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


_LEXICAL_STOPWORDS = {
    "the", "and", "for", "are", "what", "which", "does", "with", "this", "that", "from", "have", "has",
    "any", "all", "contract", "contracts", "clause", "clauses", "say", "says", "about", "more", "than",
    "less", "how", "much", "many", "there", "their", "they", "who", "when", "mentioned", "mention",
    "is", "was", "were", "been", "being", "its", "into", "our", "your", "you", "did", "do", "can",
    "agreement", "agreements", "specifically", "wrong", "please", "tell", "show", "list", "give",
}
# Added to a passage's similarity for each distinct word of the question it
# contains (capped): exact contract terms ("interest", "penalty") should
# lift a passage even when the embedding ranks a generic one higher.
_LEXICAL_BONUS = 0.1
_LEXICAL_CAP = 0.3


def _query_terms(text: str) -> List[str]:
    words = {w.strip(".%") for w in re.findall(r"[a-z0-9%.]{3,}", (text or "").lower())}
    return [w for w in words if w and w not in _LEXICAL_STOPWORDS]


def _lexical_bonus(terms: List[str], passage: str) -> float:
    if not terms:
        return 0.0
    low = (passage or "").lower()
    hits = sum(1 for t in terms if re.search(r"(?<![a-z0-9])" + re.escape(t), low))
    return min(_LEXICAL_CAP, _LEXICAL_BONUS * hits)


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

        # Ask the embedding server first: if it can't be reached, no local
        # search database is opened, so a later retry in this process
        # doesn't find the database folder still locked by this attempt.
        test_vectors = self.embed(["dimension test"], kind="document")
        if not test_vectors or not test_vectors[0]:
            raise RuntimeError("Ollama returned no embedding vector")
        self.dim = len(test_vectors[0])

        os.makedirs(QDRANT_DATA_PATH, exist_ok=True)
        with _QDRANT_LOCK:
            self.client = QdrantClient(path=QDRANT_DATA_PATH)
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

    def _post_embed(self, batch: List[str]) -> Dict[str, Any]:
        """
        One embedding request, retried: the Ollama server is shared, so a
        busy moment (timeout, connection reset, 5xx such as "model is
        loading" or out of memory) is common and usually passes within
        seconds. Bad requests (4xx) are not retried.
        """
        last_error: Optional[Exception] = None
        for attempt in range(_EMBED_ATTEMPTS):
            try:
                response = requests.post(
                    f"{self.embedding_url}/api/embed",
                    json={"model": self.embedding_model, "input": batch, "truncate": True},
                    timeout=180,
                    verify=self.verify,
                )
                if response.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {response.status_code}: {response.text[:200]}")
                response.raise_for_status()
                return response.json()
            except requests.HTTPError as error:
                last_error = error
                status = getattr(getattr(error, "response", None), "status_code", None)
                if status is not None and status < 500:
                    break
            except requests.Timeout as error:
                # Already waited the full timeout; don't wait it again.
                last_error = error
                break
            except requests.RequestException as error:
                last_error = error
            if attempt < _EMBED_ATTEMPTS - 1:
                time.sleep(_EMBED_BACKOFF_SEC * (2 ** attempt))
        raise RuntimeError(
            f"Could not get embeddings from {self.embedding_url} with "
            f"{self.embedding_model}: {last_error}"
        )

    def embed(self, texts: List[str], kind: str = "document") -> List[List[float]]:
        """kind: "document" for stored passages, "query" for questions."""
        prepared = [
            (_query_text if kind == "query" else _doc_text)(self.embedding_model, str(t or "").strip())
            for t in texts
        ]
        vectors: List[List[float]] = []
        for start in range(0, len(prepared), 16):
            batch = prepared[start:start + 16]
            data = self._post_embed(batch)
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

    def _search(
        self, vector: List[float], query_filter, limit: int, use_floor: bool = True, margin: Optional[float] = None,
        terms: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
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

        # Similarity plus a bonus for the question's own words, then the
        # usual cut-offs on that combined score.
        scored = sorted(
            ((float(h.score) + _lexical_bonus(terms or [], (h.payload or {}).get("text", "")), h) for h in hits),
            key=lambda pair: pair[0],
            reverse=True,
        )
        best = scored[0][0]
        cutoff = max(
            self.min_score if use_floor else float("-inf"),
            best - (self.relative_margin if margin is None else margin),
        )
        seen = set()
        output: List[Dict[str, Any]] = []
        for score, hit in scored:
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

    @staticmethod
    def _analysis_filter(analysis_id: str):
        return qmodels.Filter(
            must=[qmodels.FieldCondition(key="analysis_id", match=qmodels.MatchValue(value=analysis_id))]
        )

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
        return self._search(vector, query_filter, max(1, min(int(top_k), 20)), terms=_query_terms(query_text))

    def query_per_contract(
        self, text: str, analysis_ids: List[str], per_contract: int = 1
    ) -> List[Dict[str, Any]]:
        """
        The best passage(s) from *each* of the given contracts, in the
        order given. Used when a question must be answered across
        contracts: plain top-k search returns whichever few contracts
        happen to score highest, and many contracts share identical
        boilerplate, so a "which contracts ..." answer would silently
        cover only a handful of them. The question is embedded once.
        """
        query_text = str(text or "").strip()
        if not query_text or not analysis_ids:
            return []
        vector = self.embed([query_text], kind="query")[0]
        terms = _query_terms(query_text)
        output: List[Dict[str, Any]] = []
        for analysis_id in analysis_ids:
            # No absolute floor here: the question must look at every
            # contract, so each one's best passage is kept and the model
            # judges whether it says anything relevant.
            # A wider margin than normal search: the best few passages of
            # each contract, since an answer can span clauses whose scores
            # differ (regular interest vs. late-payment interest).
            output.extend(
                self._search(vector, self._analysis_filter(analysis_id), max(1, per_contract),
                             use_floor=False, margin=max(self.relative_margin, 0.3), terms=terms)
            )
        return output

    def indexed_analysis_ids(self) -> set:
        """Which contracts have at least one passage in the index."""
        ids = set()
        offset = None
        with _QDRANT_LOCK:
            while True:
                points, offset = self.client.scroll(
                    collection_name=self.collection,
                    limit=512,
                    offset=offset,
                    with_payload=["analysis_id"],
                    with_vectors=False,
                )
                ids.update((p.payload or {}).get("analysis_id") for p in points)
                if offset is None:
                    break
        ids.discard(None)
        return ids
