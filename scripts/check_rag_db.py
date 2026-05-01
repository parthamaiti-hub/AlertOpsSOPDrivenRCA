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


def _parse_document_text(doc_text: str) -> tuple[str, list[str], list[str]]:
    """Split indexed document text into (base_content, sop_keys, dynamic_classifiers).

    The service appends suffixes in this order:
      <doc_content> | dynamic classifiers: field1=val1, ... | sop_keys: key1, key2, ...
    So sop_keys is the rightmost suffix; dynamic classifiers precedes it.
    """
    sop_keys: list[str] = []
    dynamic_classifiers: list[str] = []
    base = doc_text

    sop_marker = " | sop_keys: "
    dc_marker = " | dynamic classifiers: "

    # Strip sop_keys suffix first (it is appended last, so rightmost)
    if sop_marker in base:
        idx = base.index(sop_marker)
        sop_keys = [k.strip() for k in base[idx + len(sop_marker):].split(",") if k.strip()]
        base = base[:idx]

    # Strip dynamic classifiers suffix from what remains
    if dc_marker in base:
        idx = base.index(dc_marker)
        dynamic_classifiers = [k.strip() for k in base[idx + len(dc_marker):].split(",") if k.strip()]
        base = base[:idx]

    return base, sop_keys, dynamic_classifiers


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
            extra = {k: v for k, v in meta.items() if k not in {"application", "domain", "category", "severity", "sop_document_id"}}
            for k, v in extra.items():
                print(f"    {k:<20}: {v}")
        doc_text = results["documents"][i] if results["documents"] else ""
        if doc_text:
            base, sop_keys, dynamic_classifiers = _parse_document_text(doc_text)
            print(f"  --- Indexed Enrichments ---")
            print(f"    {'sop_identifier_keys':<20}: {sop_keys if sop_keys else '(none)'}")
            if dynamic_classifiers:
                print(f"    {'dynamic_classifiers':<20}: {dynamic_classifiers}")
            preview = base[:300].replace("\n", " ") + ("..." if len(base) > 300 else "")
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

    results = col.get(include=["documents", "metadatas"])
    for i, doc_id in enumerate(results["ids"]):
        meta = results["metadatas"][i] if results["metadatas"] else {}
        doc_text = results["documents"][i] if results["documents"] else ""
        _, sop_keys, _ = _parse_document_text(doc_text)
        keys_str = ", ".join(sop_keys) if sop_keys else "(none)"
        print(f"  {doc_id:<40}  app={meta.get('application',''):<20}  sop_keys=[{keys_str}]")
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
