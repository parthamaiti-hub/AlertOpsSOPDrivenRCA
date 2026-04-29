# backend/identifySOP/seed.py

import chromadb
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_core.documents import Document
from backend.config import settings

def seed_sops():
    """Synchronous - ChromaDB and LangChain-Chroma don't support async"""
    
    client = chromadb.HttpClient(
        host=settings.CHROMADB_HOST,
        port=int(settings.CHROMADB_PORT),
    )
    
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    
    vector_store = Chroma(
        collection_name="sop_collection",
        embedding_function=embeddings,
        client=client,
    )
    
    sop_documents = [
        Document(
            page_content="High CPU Utilization SOP: Check top processes, identify runaway threads, restart service if needed...",
            metadata={
                "sop_id": "SOP-001",
                "title": "High CPU Utilization",
                "application": "order-service",
                "severity": "critical",
                "domain": "infrastructure",
                "category": "performance",
            }
        ),
        Document(
            page_content="Database Connection Pool Exhaustion SOP: Check active connections, kill idle sessions, increase pool size...",
            metadata={
                "sop_id": "SOP-002",
                "title": "DB Connection Pool Exhaustion",
                "application": "payment-gateway",
                "severity": "high",
                "domain": "database",
                "category": "connectivity",
            }
        ),
        Document(
            page_content="Memory Leak Detection SOP: Analyze heap dumps, identify leaking objects, apply hotfix or restart...",
            metadata={
                "sop_id": "SOP-003",
                "title": "Memory Leak Detection",
                "application": "user-auth-service",
                "severity": "warning",
                "domain": "infrastructure",
                "category": "memory",
            }
        ),
    ]
    
    vector_store.add_documents(sop_documents)
    print(f"✅ Seeded {len(sop_documents)} SOP documents into ChromaDB")


if __name__ == "__main__":
    seed_sops()