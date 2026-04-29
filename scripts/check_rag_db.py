"""Check data in ChromaDB RAG databases (sop_documents and validation_rca).

Usage:
    uv run python scripts/check_rag_db.py              # show all collections
    uv run python scripts/check_rag_db.py sop          # sop_documents collection only
    uv run python scripts/check_rag_db.py sop SOP_ID   # single entry by ChromaDB ID (sop_id)
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import chromadb

from backend.config.settings import settings

COLLECTIONS = ["sop_documents", "validation_rca"]
SEP = "-" * 60


def get_client() -> chromadb.HttpClient:
    return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)


def check_collection(client: chromadb.HttpClient, name: str, sop_id_filter: str = None):
    print(f"\n{'='*60}")
    print(f"Collection: {name}")
    print(f"{'='*60}")

    try:
        col = client.get_collection(name=name)
    except Exception:
        print(f"  Collection '{name}' does not exist.")
        return

    count = col.count()
    print(f"  Total documents: {count}")

    if count == 0:
        return

    if sop_id_filter:
        # Fetch by exact ChromaDB document ID (which equals sop_id for sop_documents)
        results = col.get(ids=[sop_id_filter], include=["documents", "metadatas"])
        if not results["ids"]:
            print(f"  No entry found with ID '{sop_id_filter}'")
            return
    else:
        results = col.get(include=["documents", "metadatas"])

    for i, doc_id in enumerate(results["ids"]):
        print(f"\n  {SEP}")
        print(f"  ChromaDB ID (sop_id): {doc_id}")
        meta = results["metadatas"][i] if results["metadatas"] else {}
        if meta:
            print(f"  --- Classifier Metadata ---")
            for k in ["application", "domain", "category", "severity", "sop_document_id"]:
                print(f"    {k:<20}: {meta.get(k, '')}")
            # Show any other metadata keys not in the known list
            extra = {k: v for k, v in meta.items() if k not in {"application", "domain", "category", "severity", "sop_document_id"}}
            for k, v in extra.items():
                print(f"    {k:<20}: {v}")
        doc_text = results["documents"][i] if results["documents"] else ""
        if doc_text:
            preview = doc_text[:300].replace("\n", " ") + ("..." if len(doc_text) > 300 else "")
            print(f"  --- Document Content Preview ---")
            print(f"    {preview}")

    print(f"\n  {SEP}")
    if not sop_id_filter:
        print(f"  Showing {len(results['ids'])} of {count} entries")


def check_all_sop_ids(client: chromadb.HttpClient):
    """Print a compact list of all sop_ids in sop_documents collection."""
    print(f"\n{'='*60}")
    print("SOP IDs indexed in ChromaDB (sop_documents)")
    print(f"{'='*60}")
    try:
        col = client.get_collection(name="sop_documents")
    except Exception:
        print("  Collection 'sop_documents' does not exist.")
        return

    results = col.get(include=["metadatas"])
    for i, doc_id in enumerate(results["ids"]):
        meta = results["metadatas"][i] if results["metadatas"] else {}
        print(f"  {doc_id:<30}  app={meta.get('application',''):<20}  domain={meta.get('domain',''):<15}  category={meta.get('category',''):<15}  severity={meta.get('severity','')}")
    print(f"\n  Total: {len(results['ids'])} SOP(s) indexed")


def main():
    print(f"Connecting to ChromaDB at {settings.chroma_host}:{settings.chroma_port}")
    client = get_client()

    try:
        heartbeat = client.heartbeat()
        print(f"ChromaDB heartbeat: {heartbeat}")
    except Exception as e:
        print(f"ERROR: Cannot connect to ChromaDB - {e}")
        sys.exit(1)

    all_collections = client.list_collections()
    print(f"\nAll collections in ChromaDB: {[c.name for c in all_collections] if all_collections else '(none)'}")

    args = sys.argv[1:]
    if args and args[0] == "sop":
        sop_id_filter = args[1] if len(args) > 1 else None
        check_all_sop_ids(client)
        check_collection(client, "sop_documents", sop_id_filter)
    else:
        for name in COLLECTIONS:
            check_collection(client, name)

    print()


if __name__ == "__main__":
    main()
