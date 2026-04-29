import logging
from typing import Optional

import chromadb
from langchain_openai import OpenAIEmbeddings

from backend.config.settings import settings

logger = logging.getLogger(__name__)

_client: Optional[chromadb.HttpClient] = None
_embeddings: Optional[OpenAIEmbeddings] = None

COLLECTION_NAME = "validation_rca"


def _get_client() -> chromadb.HttpClient:
    global _client
    if _client is None:
        _client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
    return _client


def _get_embeddings() -> OpenAIEmbeddings:
    global _embeddings
    if _embeddings is None:
        _embeddings = OpenAIEmbeddings(model="text-embedding-3-small", openai_api_key=settings.openai_api_key)
    return _embeddings


def _get_collection():
    return _get_client().get_or_create_collection(name=COLLECTION_NAME)


def index_rca(rca_id: str, text: str, metadata: dict | None = None):
    emb = _get_embeddings()
    vectors = emb.embed_documents([text])
    col = _get_collection()
    col.upsert(ids=[rca_id], embeddings=vectors, documents=[text], metadatas=[metadata or {}])
    logger.info("Indexed RCA %s in validation RAG", rca_id)


def index_feedback(alert_id: str, comment: str, confidence_score: float):
    emb = _get_embeddings()
    text = f"Alert {alert_id} feedback: {comment} (confidence: {confidence_score})"
    vectors = emb.embed_documents([text])
    col = _get_collection()
    col.upsert(
        ids=[f"feedback_{alert_id}"],
        embeddings=vectors,
        documents=[text],
        metadatas=[{"alert_id": alert_id, "confidence_score": confidence_score}],
    )
    logger.info("Indexed feedback for alert %s", alert_id)


def search_similar_rcas(query: str, top_k: int = 5) -> list[dict]:
    emb = _get_embeddings()
    query_vec = emb.embed_query(query)
    col = _get_collection()
    try:
        results = col.query(query_embeddings=[query_vec], n_results=top_k)
    except Exception:
        return []
    docs = []
    for i, doc_id in enumerate(results["ids"][0]):
        docs.append({
            "id": doc_id,
            "document": results["documents"][0][i] if results["documents"] else "",
            "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
            "distance": results["distances"][0][i] if results["distances"] else None,
        })
    return docs
