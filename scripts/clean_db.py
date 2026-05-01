"""Clean MongoDB and ChromaDB data for the SOP Alert Analytics system.

Modes:
  all         - Delete everything: operational data + SOP data + ChromaDB.
                Prompts are preserved unless --include-prompts is also passed.
  operational - Delete operational data only (alerts, RCA, feedback, classifier logs).
                Does NOT touch SOPs, workflows, mappings, or prompts.
  sop         - Delete SOP data only (sop_documents, sop_workflows, sop_mappings + ChromaDB sop_documents).
                Use this to force a clean re-seed.
  stale       - Remove only sop_mapping records whose sop_document_file is not in sop_mappingdata.json.
                Also removes linked sop_documents and sop_workflows records. Safe to run without full wipe.
  alerts      - Delete alerts and related RCA/feedback/classifier-match data only.
  rca         - Delete rca_results and validation_results only.

Usage:
    uv run python scripts/clean_db.py --mode stale --yes
    uv run python scripts/clean_db.py --mode all
    uv run python scripts/clean_db.py --mode all --include-prompts
    uv run python scripts/clean_db.py --mode operational
    uv run python scripts/clean_db.py --mode sop
    uv run python scripts/clean_db.py --mode alerts
    uv run python scripts/clean_db.py --mode rca
    uv run python scripts/clean_db.py --mode all --yes   # skip confirmation
"""

import json
import pathlib
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import chromadb
from pymongo import MongoClient

from backend.config.settings import settings

MONGO_DB = settings.mongodb_db
CHROMA_COLLECTIONS = ["sop_documents", "validation_rca"]

OPERATIONAL_COLS = ["alerts", "rca_results", "validation_results", "feedback", "classifier_match_logs", "pending_actions"]
SOP_COLS = ["sop_documents", "sop_workflows", "sop_mappings"]
PROMPT_COLS = ["prompts"]


def get_mongo_db():
    client = MongoClient(settings.mongodb_uri)
    return client[MONGO_DB]


def get_chroma_client():
    return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)


def remove_stale_sop_mappings(db) -> int:
    """Remove sop_mapping records whose sop_document_file is not in sop_mappingdata.json."""
    mapping_file = pathlib.Path(__file__).parent.parent / "data" / "sop_mappingdata.json"
    known_files = set(json.loads(mapping_file.read_text()).keys())
    sop_mappings = db["sop_mappings"]
    sop_docs = db["sop_documents"]
    sop_wfs = db["sop_workflows"]
    stale = list(sop_mappings.find(
        {"sop_document_file": {"$nin": list(known_files)}},
        {"sop_document_file": 1, "sop_id": 1, "sop_document_id": 1, "workflow_id": 1},
    ))
    removed = 0
    for rec in stale:
        print(f"  [MongoDB] Removing stale mapping: {rec.get('sop_document_file', '?')} (sop_id={rec.get('sop_id', '?')})")
        sop_mappings.delete_one({"_id": rec["_id"]})
        if rec.get("sop_document_id"):
            from bson import ObjectId
            sop_docs.delete_one({"_id": ObjectId(rec["sop_document_id"])})
        if rec.get("workflow_id"):
            from bson import ObjectId
            sop_wfs.delete_one({"_id": ObjectId(rec["workflow_id"])})
        removed += 1
    if removed == 0:
        print("  [MongoDB] No stale SOP mappings found.")
    return removed


def drop_mongo_collections(db, collections: list):
    for col_name in collections:
        count = db[col_name].count_documents({})
        db[col_name].drop()
        print(f"  [MongoDB] Dropped '{col_name}' ({count} documents)")


def drop_chroma_collections(client, collections: list):
    existing = [c.name for c in client.list_collections()]
    for name in collections:
        if name in existing:
            count = client.get_collection(name).count()
            client.delete_collection(name)
            print(f"  [ChromaDB] Deleted collection '{name}' ({count} documents)")
        else:
            print(f"  [ChromaDB] Collection '{name}' not found, skipping")


def confirm(prompt: str) -> bool:
    answer = input(f"{prompt} [y/N]: ").strip().lower()
    return answer == "y"


def main():
    parser = argparse.ArgumentParser(description="Clean MongoDB and ChromaDB data")
    parser.add_argument(
        "--mode",
        choices=["all", "operational", "sop", "stale", "alerts", "rca"],
        required=True,
        help="What to delete (see module docstring for details)",
    )
    parser.add_argument(
        "--include-prompts",
        action="store_true",
        help="Also delete the prompts collection (only applies to --mode all)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )
    args = parser.parse_args()

    if args.mode == "stale":
        # Targeted removal — no ChromaDB needed, no full collection drop
        print("\nClean mode  : stale (sop_mapping records not in sop_mappingdata.json)")
        if not args.yes:
            if not confirm("\nProceed? This cannot be undone"):
                print("Aborted.")
                sys.exit(0)
        n = remove_stale_sop_mappings(get_mongo_db())
        print(f"\nDone. Removed {n} stale record(s).")
        print("\nNote: run 'POST /api/sop-management/seed' to re-seed SOP data.")
        return

    mongo_cols: list = []
    chroma_cols: list = []

    if args.mode == "alerts":
        mongo_cols = ["alerts", "rca_results", "validation_results", "feedback", "classifier_match_logs"]
    elif args.mode == "rca":
        mongo_cols = ["rca_results", "validation_results"]
    elif args.mode == "operational":
        mongo_cols = OPERATIONAL_COLS[:]
    elif args.mode == "sop":
        mongo_cols = SOP_COLS[:]
        chroma_cols = ["sop_documents"]
    elif args.mode == "all":
        mongo_cols = OPERATIONAL_COLS + SOP_COLS
        if args.include_prompts:
            mongo_cols += PROMPT_COLS
        chroma_cols = CHROMA_COLLECTIONS[:]

    print(f"\nClean mode  : {args.mode}")
    if mongo_cols:
        print(f"  MongoDB   : {', '.join(mongo_cols)}")
    if chroma_cols:
        print(f"  ChromaDB  : {', '.join(chroma_cols)}")
    if not mongo_cols and not chroma_cols:
        print("  Nothing to do.")
        return

    if not args.yes:
        if not confirm("\nProceed? This cannot be undone"):
            print("Aborted.")
            sys.exit(0)

    if mongo_cols:
        print("\nCleaning MongoDB...")
        drop_mongo_collections(get_mongo_db(), mongo_cols)

    if chroma_cols:
        print("\nCleaning ChromaDB...")
        try:
            drop_chroma_collections(get_chroma_client(), chroma_cols)
        except Exception as e:
            print(f"  [ChromaDB] ERROR: {e}")
            print("  Make sure ChromaDB is running (docker-compose up chromadb)")
            sys.exit(1)

    print("\nDone.")
    if args.mode in ("sop", "all"):
        print("\nNote: run 'POST /api/sop-management/seed' or")
        print("      'uv run python -m backend.identifySOP.seed' to re-seed SOP data.")


if __name__ == "__main__":
    main()
