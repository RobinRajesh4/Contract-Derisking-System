import os
import uuid
from typing import Any, Dict, List, Optional

import requests
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels


BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

QDRANT_DATA_PATH = os.getenv(
    "QDRANT_DATA_PATH",
    os.path.join(BASE_DIR, "qdrant_data"),
)

DEFAULT_COLLECTION = os.getenv(
    "QDRANT_COLLECTION",
    "contracts",
)

OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://127.0.0.1:11434",
).rstrip("/")

EMBEDDING_MODEL_NAME = os.getenv(
    "EMBEDDING_MODEL",
    "nomic-embed-text",
)


class RAGStore:
    def __init__(
        self,
        collection: str = DEFAULT_COLLECTION,
        embedding_model: str = EMBEDDING_MODEL_NAME,
    ) -> None:
        """
        Initialize local Qdrant storage and local Ollama embeddings.
        """

        os.makedirs(
            QDRANT_DATA_PATH,
            exist_ok=True,
        )

        self.client = QdrantClient(
            path=QDRANT_DATA_PATH
        )

        self.collection = collection
        self.embedding_model = embedding_model
        self.ollama_url = OLLAMA_URL

        # Generate one test embedding to confirm that Ollama and
        # the embedding model are available and determine dimension.
        test_vectors = self.embed(
            ["Embedding dimension test"]
        )

        if not test_vectors or len(test_vectors[0]) == 0:
            raise RuntimeError(
                "Ollama returned no embedding vector"
            )

        self.dim = len(test_vectors[0])

        self._ensure_collection()

    def _ensure_collection(self) -> None:
        """
        Create the local Qdrant collection if it does not exist.
        """

        try:
            collection_info = self.client.get_collection(
                collection_name=self.collection
            )

            existing_size = (
                collection_info
                .config
                .params
                .vectors
                .size
            )

            if existing_size != self.dim:
                raise RuntimeError(
                    "The existing Qdrant collection uses vector "
                    f"dimension {existing_size}, but "
                    f"{self.embedding_model} produces dimension "
                    f"{self.dim}. Delete the qdrant_data directory "
                    "and restart the backend."
                )

            return

        except RuntimeError:
            raise

        except Exception:
            pass

        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=qmodels.VectorParams(
                size=self.dim,
                distance=qmodels.Distance.COSINE,
            ),
        )

    def embed(
        self,
        texts: List[str],
    ) -> List[List[float]]:
        """
        Generate embeddings through the local Ollama API.

        Ollama runs entirely on localhost and does not send the
        contract text to Hugging Face or another cloud service.
        """

        clean_texts = [
            str(text or "").strip()
            for text in texts
        ]

        clean_texts = [
            text
            for text in clean_texts
            if text
        ]

        if not clean_texts:
            return []

        try:
            response = requests.post(
                f"{self.ollama_url}/api/embed",
                json={
                    "model": self.embedding_model,
                    "input": clean_texts,
                    "truncate": True,
                },
                timeout=180,
            )

            response.raise_for_status()
            data = response.json()

        except requests.RequestException as error:
            raise RuntimeError(
                "Could not generate embeddings through Ollama. "
                f"Check that Ollama is running and that "
                f"{self.embedding_model} is installed. "
                f"Details: {error}"
            ) from error

        embeddings = data.get(
            "embeddings",
            [],
        )

        if not isinstance(embeddings, list):
            raise RuntimeError(
                "Ollama returned an invalid embeddings response"
            )

        if len(embeddings) != len(clean_texts):
            raise RuntimeError(
                "Ollama returned an unexpected number of "
                "embedding vectors"
            )

        return [
            [
                float(value)
                for value in embedding
            ]
            for embedding in embeddings
        ]

    def upsert_clauses(
        self,
        analysis_id: str,
        clauses: List[Dict[str, Any]],
    ) -> None:
        """
        Add or update contract clauses in local Qdrant storage.
        """

        if not clauses:
            return

        searchable_clauses = [
            clause
            for clause in clauses
            if str(
                clause.get("text", "")
            ).strip()
        ]

        if not searchable_clauses:
            return

        texts = [
            str(
                clause.get("text", "")
            ).strip()
            for clause in searchable_clauses
        ]

        vectors = self.embed(texts)

        points = []

        for clause, vector in zip(
            searchable_clauses,
            vectors,
        ):
            clause_id = clause.get("id")

            point_id = str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{analysis_id}:{clause_id}",
                )
            )

            payload = {
                "analysis_id": analysis_id,
                "clause_id": clause_id,
                "text": str(
                    clause.get("text", "")
                ).strip(),
                "metadata": clause.get(
                    "metadata",
                    {},
                ),
            }

            points.append(
                qmodels.PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload,
                )
            )

        self.client.upsert(
            collection_name=self.collection,
            points=points,
            wait=True,
        )

    def query(
        self,
        text: str,
        top_k: int = 5,
        filter_by_analysis: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Find clauses semantically related to a question.
        """

        query_text = str(text or "").strip()

        if not query_text:
            return []

        query_vector = self.embed(
            [query_text]
        )[0]

        query_filter = None

        if filter_by_analysis:
            query_filter = qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="analysis_id",
                        match=qmodels.MatchValue(
                            value=filter_by_analysis
                        ),
                    )
                ]
            )

        limit = max(
            1,
            min(int(top_k), 20),
        )

        query_result = self.client.query_points(
            collection_name=self.collection,
            query=query_vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )

        output: List[Dict[str, Any]] = []

        for result in query_result.points:
            if float(result.score) < 0.50:
                continue

            payload = result.payload or {}

            output.append(
                {
                    "text": payload.get(
                        "text",
                        "",
                    ),
                    "analysis_id": payload.get(
                        "analysis_id"
                    ),
                    "clause_id": payload.get(
                        "clause_id"
                    ),
                    "metadata": payload.get(
                        "metadata",
                        {},
                    ),
                    "score": float(result.score),
                }
            )

        return output
