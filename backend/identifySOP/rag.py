import logging
from typing import Optional

import chromadb
from langchain_openai import OpenAIEmbeddings

from backend.config.settings import settings

logger = logging.getLogger(__name__)

_client: Optional[chromadb.HttpClient] = None
_embeddings: Optional[OpenAIEmbeddings] = None

COLLECTION_NAME = "sop_documents"


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


def is_sop_indexed(sop_id: str) -> bool:
    """Return True if sop_id already exists in the ChromaDB collection.

    Does not require an OpenAI call.
    """
    try:
        col = _get_collection()
        result = col.get(ids=[sop_id])
        return len(result["ids"]) > 0
    except Exception:
        return False


def index_sop_document(sop_id: str, text: str, metadata: dict):
    emb = _get_embeddings()
    vectors = emb.embed_documents([text])
    col = _get_collection()
    col.upsert(ids=[sop_id], embeddings=vectors, documents=[text], metadatas=[metadata])
    logger.info("Indexed SOP %s in ChromaDB", sop_id)


def search_sop(query: str, filters: dict | None = None, top_k: int = 3) -> list[dict]:
    emb = _get_embeddings()
    query_vec = emb.embed_query(query)
    col = _get_collection()
    where = filters if filters else None
    results = col.query(query_embeddings=[query_vec], n_results=top_k, where=where)
    docs = []
    for i, doc_id in enumerate(results["ids"][0]):
        docs.append({
            "sop_id": doc_id,
            "document": results["documents"][0][i] if results["documents"] else "",
            "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
            "distance": results["distances"][0][i] if results["distances"] else None,
        })
    return docs
