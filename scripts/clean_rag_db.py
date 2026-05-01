"""Clear ChromaDB sop_documents collection and reseed with current SOP data.

Each SOP's indexed text is rebuilt as:
  <document_content> | sop_keys: <workflow sop_identifier_keys> | dynamic classifiers: <classifiers>

Usage:
    uv run python scripts/clean_rag_db.py              # confirm before proceeding
    uv run python scripts/clean_rag_db.py --yes        # skip confirmation
    uv run python scripts/clean_rag_db.py --check      # show current ChromaDB contents only (no changes)
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import chromadb

from backend.config.settings import settings

COLLECTION_NAME = "sop_documents"


def get_chroma_client() -> chromadb.HttpClient:
    return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)


def show_current(client: chromadb.HttpClient):
    print(f"\nCurrent ChromaDB contents ({COLLECTION_NAME}):")
    print("-" * 60)
    try:
        col = client.get_collection(name=COLLECTION_NAME)
    except Exception:
        print(f"  Collection '{COLLECTION_NAME}' does not exist.")
        return

    count = col.count()
    if count == 0:
        print("  (empty)")
        return

    results = col.get(include=["documents", "metadatas"])
    for i, doc_id in enumerate(results["ids"]):
        meta = results["metadatas"][i] if results["metadatas"] else {}
        doc_text = results["documents"][i] if results["documents"] else ""

        # Parse embedded sop_keys and dynamic classifiers from text.
        # Append order: <content> | dynamic classifiers: ... | sop_keys: ...
        # So strip sop_keys first (rightmost), then dynamic classifiers.
        sop_keys: list[str] = []
        dynamic_classifiers: list[str] = []
        base = doc_text
        sop_marker = " | sop_keys: "
        dc_marker = " | dynamic classifiers: "
        if sop_marker in base:
            idx = base.index(sop_marker)
            sop_keys = [k.strip() for k in base[idx + len(sop_marker):].split(",") if k.strip()]
            base = base[:idx]
        if dc_marker in base:
            idx = base.index(dc_marker)
            dynamic_classifiers = [k.strip() for k in base[idx + len(dc_marker):].split(",") if k.strip()]
            base = base[:idx]

        keys_str = ", ".join(sop_keys) if sop_keys else "(none)"
        app = meta.get("application", "")
        print(f"  {doc_id}")
        print(f"    application : {app}")
        print(f"    sop_keys    : [{keys_str}]")
        if dynamic_classifiers:
            print(f"    dyn_class   : {dynamic_classifiers}")
        print(f"    doc_len     : {len(base)} chars")
    print(f"\n  Total: {count} SOP(s) indexed")


def main():
    parser = argparse.ArgumentParser(description="Clear and reseed ChromaDB sop_documents collection")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    parser.add_argument("--check", action="store_true", help="Show current ChromaDB contents without making changes")
    args = parser.parse_args()

    print(f"ChromaDB: {settings.chroma_host}:{settings.chroma_port}")

    client = get_chroma_client()
    try:
        client.heartbeat()
    except Exception as e:
        print(f"ERROR: Cannot connect to ChromaDB — {e}")
        print("Make sure ChromaDB is running (docker compose up chromadb)")
        sys.exit(1)

    if args.check:
        show_current(client)
        return

    show_current(client)

    print(f"\nThis will:")
    print(f"  1. Delete the '{COLLECTION_NAME}' collection from ChromaDB")
    print(f"  2. Reseed all SOPs from MongoDB + sop_mappingdata.json")
    print(f"     Each entry will include: <doc_content> | sop_keys: ... | dynamic classifiers: ...")

    if not args.yes:
        answer = input("\nProceed? [y/N]: ").strip().lower()
        if answer != "y":
            print("Aborted.")
            sys.exit(0)

    # Delete collection
    try:
        existing = [c.name for c in client.list_collections()]
        if COLLECTION_NAME in existing:
            count = client.get_collection(COLLECTION_NAME).count()
            client.delete_collection(COLLECTION_NAME)
            print(f"\n[ChromaDB] Deleted '{COLLECTION_NAME}' ({count} documents)")
        else:
            print(f"\n[ChromaDB] Collection '{COLLECTION_NAME}' not found — nothing to delete")
    except Exception as e:
        print(f"ERROR deleting collection: {e}")
        sys.exit(1)

    # Reseed
    print("\n[Seeder] Re-seeding SOPs into ChromaDB...")
    from backend.sopmanagement.service import seed_all
    results = seed_all()

    seeded = [r for r in results if r.get("status") in ("seeded", "resynced_chroma", "updated_classifiers", "updated_workflow")]
    skipped = [r for r in results if r.get("status") == "skipped"]
    errors = [r for r in results if r.get("status") == "error"]

    for r in results:
        status = r.get("status", "?")
        sop_id = r.get("sop_id", r.get("sop_document_file", "?"))
        marker = "OK" if status not in ("error", "skipped") else status.upper()
        print(f"  [{marker}] {sop_id} — {status}")

    print(f"\nDone. {len(seeded)} seeded/synced, {len(skipped)} skipped, {len(errors)} error(s)")

    if errors:
        print("\nErrors:")
        for r in errors:
            print(f"  {r.get('sop_document_file', '?')}: {r.get('error', '?')}")

    print("\nRun 'uv run python scripts/check_rag_db.py sop' to verify indexed content.")


if __name__ == "__main__":
    main()
