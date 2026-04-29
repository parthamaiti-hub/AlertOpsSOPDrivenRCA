"""Idempotent backfill: set sop_document_version and workflow_version to '1.0'
on all sop_mappings records that were created before the versioning feature.

Usage:
    uv run python scripts/migrate_versions.py
"""

from datetime import UTC, datetime

from pymongo import MongoClient

from backend.config.settings import settings

client = MongoClient(settings.mongodb_uri)
db = client[settings.mongodb_db]

col = db["sop_mappings"]

query = {"sop_document_version": {"$exists": False}}
docs = list(col.find(query))

if not docs:
    print("Nothing to migrate — all sop_mappings records already have version fields.")
else:
    for doc in docs:
        created_at = doc.get("created_at", datetime.now(UTC))
        col.update_one(
            {"_id": doc["_id"]},
            {"$set": {
                "sop_document_version": "1.0",
                "workflow_version": "1.0",
                "mapping_version_created_at": created_at,
                "change_type": "new_sop",
                "changed_by": "system",
            }},
        )
    print(f"Migrated {len(docs)} sop_mappings record(s) to version 1.0.")

client.close()
