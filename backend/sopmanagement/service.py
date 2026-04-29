import json
import logging
import pathlib
from datetime import UTC, datetime

from backend.identifySOP.rag import index_sop_document, is_sop_indexed
from backend.models.database import get_sync_db
from backend.sopmanagement.version_utils import (
    get_next_valid_versions,
    is_valid_progression,
    validate_version_format,
    version_tuple,
)

logger = logging.getLogger(__name__)

DATA_DIR = pathlib.Path(__file__).parent.parent.parent / "data"
MAPPING_FILE = DATA_DIR / "sop_mappingdata.json"


def load_mappings() -> dict:
    """Load SOP mapping data from data/sop_mappingdata.json."""
    return json.loads(MAPPING_FILE.read_text())


def _read_sop_content(filepath: pathlib.Path) -> str:
    """Read SOP document content, handling both plain text and PDF files."""
    if filepath.suffix.lower() == ".pdf":
        import pypdf
        reader = pypdf.PdfReader(str(filepath))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    return filepath.read_text(encoding="utf-8", errors="replace")


def _build_dynamic_text(dynamic_classifiers: list[dict]) -> str:
    """Build text from dynamic classifiers for ChromaDB indexing."""
    if not dynamic_classifiers:
        return ""
    parts = [f"{dc['field_name']}={dc['field_value']}" for dc in dynamic_classifiers if dc.get("field_name")]
    return " | dynamic classifiers: " + ", ".join(parts) if parts else ""


def get_all_dynamic_field_names() -> list[str]:
    """Return distinct dynamic classifier field_names across all SOP mappings."""
    db = get_sync_db()
    col = db["sop_mappings"]
    pipeline = [
        {"$unwind": "$dynamic_classifiers"},
        {"$group": {"_id": "$dynamic_classifiers.field_name"}},
        {"$match": {"_id": {"$ne": ""}}},
        {"$sort": {"_id": 1}},
    ]
    return [doc["_id"] for doc in col.aggregate(pipeline)]


def seed_all() -> list[dict]:
    """Seed all SOPs from the mapping data into MongoDB and ChromaDB.

    Idempotent: skips entries already present in sop_mappings.
    Returns list of result dicts with sop_id and status.
    """
    db = get_sync_db()
    sop_docs_col = db["sop_documents"]
    sop_wf_col = db["sop_workflows"]
    sop_mappings_col = db["sop_mappings"]

    mappings = load_mappings()
    results = []

    # ── Backfill version fields on legacy sop_mappings records ─────────────
    # Idempotent: only updates records where sop_document_version is absent.
    legacy = list(sop_mappings_col.find({"sop_document_version": {"$exists": False}}))
    if legacy:
        for leg in legacy:
            created_at = leg.get("created_at", datetime.now(UTC))
            sop_mappings_col.update_one(
                {"_id": leg["_id"]},
                {"$set": {
                    "sop_document_version": "1.0",
                    "workflow_version": "1.0",
                    "mapping_version_created_at": created_at,
                    "change_type": "new_sop",
                    "changed_by": "system",
                }},
            )
        logger.info("Backfilled version fields on %d legacy sop_mappings record(s).", len(legacy))

    # ── Bootstrap sop_mapping_history for mappings with no history entry ────
    # Ensures the collection exists and every SOP has at least one history record.
    history_col = db["sop_mapping_history"]
    all_mappings = list(sop_mappings_col.find({}))
    for m in all_mappings:
        sop_id_m = m.get("sop_id", "")
        if not sop_id_m:
            continue
        if history_col.find_one({"sop_id": sop_id_m}):
            continue  # already has history
        snapshot = {k: str(v) if k == "_id" else v for k, v in m.items() if k != "_id"}
        history_col.insert_one({
            "sop_id": sop_id_m,
            "sop_document_version": m.get("sop_document_version", "1.0"),
            "workflow_version": m.get("workflow_version", "1.0"),
            "archived_at": m.get("created_at", datetime.now(UTC)),
            "change_type": "initial",
            "changed_by": "system",
            "snapshot": snapshot,
        })
    logger.info("Bootstrapped sop_mapping_history for %d SOP(s) with no prior history.", len(all_mappings))

    # Remove stale sop_mapping records whose sop_document_file is no longer in
    # sop_mappingdata.json (covers any source, including legacy records with no source field).
    known_files = set(mappings.keys())
    stale = list(sop_mappings_col.find(
        {"sop_document_file": {"$nin": list(known_files)}},
        {"sop_document_file": 1, "sop_id": 1, "sop_document_id": 1, "workflow_id": 1},
    ))
    for stale_rec in stale:
        stale_file = stale_rec.get("sop_document_file", "")
        stale_sop_id = stale_rec.get("sop_id", "")
        logger.info("Removing stale SOP mapping for renamed/deleted file: %s", stale_file)
        sop_mappings_col.delete_one({"_id": stale_rec["_id"]})
        if stale_rec.get("sop_document_id"):
            from bson import ObjectId as _OId
            sop_docs_col.delete_one({"_id": _OId(stale_rec["sop_document_id"])})
        if stale_rec.get("workflow_id"):
            from bson import ObjectId as _OId
            sop_wf_col.delete_one({"_id": _OId(stale_rec["workflow_id"])})
        results.append({"sop_document_file": stale_file, "sop_id": stale_sop_id, "status": "removed_stale"})

    # Migrate legacy records: rename 'seeded' field to 'source' (one-time, idempotent)
    sop_mappings_col.update_many(
        {"seeded": True, "source": {"$exists": False}},
        {"$set": {"source": "file"}, "$unset": {"seeded": ""}},
    )
    sop_mappings_col.update_many(
        {"seeded": False, "source": {"$exists": False}},
        {"$set": {"source": "ui"}, "$unset": {"seeded": ""}},
    )

    for sop_doc_filename, meta in mappings.items():
        existing = sop_mappings_col.find_one({"sop_document_file": sop_doc_filename})
        if existing:
            # MongoDB record exists — sync dynamic_classifiers from file, check ChromaDB
            sop_id = existing.get("sop_id", "")
            doc_id = existing.get("sop_document_id", "")
            dynamic_classifiers = meta.get("dynamic_classifiers", [])

            # Update dynamic_classifiers in MongoDB if they differ from the file
            existing_dcs = existing.get("dynamic_classifiers", [])
            if dynamic_classifiers != existing_dcs:
                sop_mappings_col.update_one(
                    {"sop_document_file": sop_doc_filename},
                    {"$set": {"dynamic_classifiers": dynamic_classifiers}},
                )
                logger.info("Updated dynamic_classifiers for SOP: %s", sop_id)
                from bson import ObjectId
                sop_doc = sop_docs_col.find_one({"_id": ObjectId(doc_id)}) if doc_id else None
                if sop_doc:
                    try:
                        chroma_content = sop_doc["content"] + _build_dynamic_text(dynamic_classifiers)
                        index_sop_document(sop_id, chroma_content, {
                            "application": existing.get("application", ""),
                            "domain": existing.get("domain", ""),
                            "category": existing.get("category", ""),
                            "severity": existing.get("severity", ""),
                            "sop_document_id": doc_id,
                        })
                        results.append({"sop_document_file": sop_doc_filename, "sop_id": sop_id, "status": "updated_classifiers"})
                    except Exception as e:
                        logger.error("Failed to re-index ChromaDB for %s: %s", sop_id, e)
                        results.append({"sop_document_file": sop_doc_filename, "sop_id": sop_id, "status": "error", "error": str(e)})
                else:
                    results.append({"sop_document_file": sop_doc_filename, "sop_id": sop_id, "status": "updated_classifiers_mongo_only"})
                continue

            if sop_id and not is_sop_indexed(sop_id):
                logger.warning("SOP %s in MongoDB but missing from ChromaDB — re-indexing", sop_id)
                from bson import ObjectId
                sop_doc = sop_docs_col.find_one({"_id": ObjectId(doc_id)}) if doc_id else None
                if sop_doc:
                    try:
                        index_sop_document(sop_id, sop_doc["content"], {
                            "application": existing.get("application", ""),
                            "domain": existing.get("domain", ""),
                            "category": existing.get("category", ""),
                            "severity": existing.get("severity", ""),
                            "sop_document_id": doc_id,
                        })
                        results.append({"sop_document_file": sop_doc_filename, "sop_id": sop_id, "status": "resynced_chroma"})
                    except Exception as e:
                        logger.error("Failed to re-index ChromaDB for %s: %s", sop_id, e)
                        results.append({"sop_document_file": sop_doc_filename, "sop_id": sop_id, "status": "error", "error": str(e)})
                else:
                    logger.error("Cannot re-index %s: sop_document not found in MongoDB (doc_id=%s)", sop_id, doc_id)
                    results.append({"sop_document_file": sop_doc_filename, "sop_id": sop_id, "status": "error", "error": "sop_document missing from MongoDB"})
            else:
                logger.info("Skipping already-seeded SOP: %s", sop_doc_filename)
                results.append({"sop_document_file": sop_doc_filename, "status": "skipped"})
            continue

        sop_file_path = DATA_DIR / "sop_documents" / sop_doc_filename
        if not sop_file_path.exists():
            logger.error("Skipping SOP '%s': file not found at %s", sop_doc_filename, sop_file_path)
            results.append({"sop_document_file": sop_doc_filename, "status": "error", "error": "file not found"})
            continue

        content = _read_sop_content(sop_file_path)
        workflow_path = DATA_DIR / "sop_workflows" / meta["workflow_file"]
        workflow_data = json.loads(workflow_path.read_text())
        workflow_sop_id = workflow_data["sop_id"]
        dynamic_classifiers = meta.get("dynamic_classifiers", [])

        # Insert SOP document
        doc = {
            "name": meta["name"],
            "application": meta["application"],
            "domain": meta["domain"],
            "category": meta["category"],
            "severity": meta["severity"],
            "content": content,
            "created_at": datetime.now(UTC),
        }
        doc_result = sop_docs_col.insert_one(doc)
        doc_id = str(doc_result.inserted_id)

        # Index in ChromaDB with canonical sop_id from workflow
        chroma_content = content + _build_dynamic_text(dynamic_classifiers)
        index_sop_document(workflow_sop_id, chroma_content, {
            "application": meta["application"],
            "domain": meta["domain"],
            "category": meta["category"],
            "severity": meta["severity"],
            "sop_document_id": doc_id,
        })

        # Insert workflow
        wf_result = sop_wf_col.insert_one(workflow_data)
        workflow_id = str(wf_result.inserted_id)

        # Persist mapping record
        now = datetime.now(UTC)
        mapping_record = {
            "sop_document_file": sop_doc_filename,
            "workflow_file": meta["workflow_file"],
            "sop_id": workflow_sop_id,
            "name": meta["name"],
            "application": meta["application"],
            "domain": meta["domain"],
            "category": meta["category"],
            "severity": meta["severity"],
            "dynamic_classifiers": dynamic_classifiers,
            "sop_document_id": doc_id,
            "workflow_id": workflow_id,
            "source": "file",
            "sop_document_version": "1.0",
            "workflow_version": "1.0",
            "mapping_version_created_at": now,
            "change_type": "new_sop",
            "changed_by": "system",
            "created_at": now,
        }
        sop_mappings_col.insert_one(mapping_record)

        logger.info("Seeded SOP: %s (sop_id=%s)", meta["name"], workflow_sop_id)
        results.append({
            "sop_document_file": sop_doc_filename,
            "sop_id": workflow_sop_id,
            "sop_document_id": doc_id,
            "workflow_id": workflow_id,
            "status": "seeded",
        })

    # Second pass: repair ChromaDB for UI-created SOPs (source='ui', not in sop_mappingdata.json)
    # These are in MongoDB sop_mappings but were never in the file-based loop above.
    ui_mappings = list(sop_mappings_col.find({"source": "ui"}))
    for mapping in ui_mappings:
        sop_id = mapping.get("sop_id", "")
        doc_id = mapping.get("sop_document_id", "")
        if not sop_id or not doc_id:
            continue
        if is_sop_indexed(sop_id):
            continue
        logger.warning("UI-created SOP %s missing from ChromaDB — re-indexing", sop_id)
        from bson import ObjectId
        sop_doc = sop_docs_col.find_one({"_id": ObjectId(doc_id)})
        if sop_doc:
            try:
                index_sop_document(sop_id, sop_doc["content"], {
                    "application": mapping.get("application", ""),
                    "domain": mapping.get("domain", ""),
                    "category": mapping.get("category", ""),
                    "severity": mapping.get("severity", ""),
                    "sop_document_id": doc_id,
                })
                results.append({"sop_id": sop_id, "status": "resynced_chroma"})
            except Exception as e:
                logger.error("Failed to re-index UI SOP %s: %s", sop_id, e)
                results.append({"sop_id": sop_id, "status": "error", "error": str(e)})
        else:
            logger.error("Cannot re-index UI SOP %s: sop_document missing (doc_id=%s)", sop_id, doc_id)
            results.append({"sop_id": sop_id, "status": "error", "error": "sop_document missing from MongoDB"})

    logger.info("seed_all complete: %d entries", len(results))
    return results


def get_all_mappings() -> list[dict]:
    """Return all mapping records from the sop_mappings collection."""
    db = get_sync_db()
    col = db["sop_mappings"]
    docs = list(col.find({}, {"_id": 0}))
    return docs


def get_active_mapping(sop_id: str) -> dict | None:
    """Return the active (highest sop_document_version) mapping for sop_id."""
    db = get_sync_db()
    col = db["sop_mappings"]
    docs = list(col.find({"sop_id": sop_id}))
    if not docs:
        return None
    docs.sort(
        key=lambda d: version_tuple(d.get("sop_document_version", "1.0")),
        reverse=True,
    )
    doc = docs[0]
    doc["_id"] = str(doc["_id"])
    return doc


def get_mapping_by_sop_id(sop_id: str) -> dict | None:
    """Return the active mapping record for sop_id (highest version)."""
    mapping = get_active_mapping(sop_id)
    if mapping:
        mapping.pop("_id", None)
    return mapping


def _archive_mapping(mapping: dict, change_type: str) -> None:
    """Snapshot the given mapping into sop_mapping_history (append-only)."""
    db = get_sync_db()
    history_col = db["sop_mapping_history"]
    snapshot = {k: v for k, v in mapping.items() if k != "_id"}
    history_col.insert_one({
        "sop_id": mapping.get("sop_id", ""),
        "sop_document_version": mapping.get("sop_document_version", "1.0"),
        "workflow_version": mapping.get("workflow_version", "1.0"),
        "archived_at": datetime.now(UTC),
        "change_type": change_type,
        "changed_by": "system",
        "snapshot": snapshot,
    })


def create_sop_mapping(
    sop_id: str,
    name: str,
    application: str,
    domain: str,
    category: str,
    severity: str,
    doc_content: str,
    doc_filename: str,
    workflow_data: dict,
    workflow_filename: str,
    dynamic_classifiers: list[dict] | None = None,
    sop_document_version: str = "1.0",
    workflow_version: str = "1.0",
) -> dict:
    """Create a new SOP mapping with document, workflow, and ChromaDB entry.

    Raises ValueError if sop_id already exists in sop_mappings, or if the
    provided version strings are not valid x.y format.
    The sop_id field in workflow_data is overridden to match the provided sop_id.
    """
    if not validate_version_format(sop_document_version):
        raise ValueError(f"Invalid sop_document_version '{sop_document_version}': must be x.y format")
    if not validate_version_format(workflow_version):
        raise ValueError(f"Invalid workflow_version '{workflow_version}': must be x.y format")

    db = get_sync_db()
    sop_docs_col = db["sop_documents"]
    sop_wf_col = db["sop_workflows"]
    sop_mappings_col = db["sop_mappings"]
    dynamic_classifiers = dynamic_classifiers or []

    if sop_mappings_col.find_one({"sop_id": sop_id}):
        raise ValueError(f"SOP ID '{sop_id}' already exists")

    # Override sop_id in workflow data with the canonical value
    workflow_data = {**workflow_data, "sop_id": sop_id}

    now = datetime.now(UTC)
    doc = {
        "name": name,
        "application": application,
        "domain": domain,
        "category": category,
        "severity": severity,
        "content": doc_content,
        "created_at": now,
    }
    doc_result = sop_docs_col.insert_one(doc)
    doc_id = str(doc_result.inserted_id)

    chroma_content = doc_content + _build_dynamic_text(dynamic_classifiers)
    index_sop_document(sop_id, chroma_content, {
        "application": application,
        "domain": domain,
        "category": category,
        "severity": severity,
        "sop_document_id": doc_id,
    })

    wf_result = sop_wf_col.insert_one(workflow_data)
    workflow_id = str(wf_result.inserted_id)

    mapping_record = {
        "sop_document_file": doc_filename,
        "workflow_file": workflow_filename,
        "sop_id": sop_id,
        "name": name,
        "application": application,
        "domain": domain,
        "category": category,
        "severity": severity,
        "dynamic_classifiers": dynamic_classifiers,
        "sop_document_id": doc_id,
        "workflow_id": workflow_id,
        "source": "ui",
        "sop_document_version": sop_document_version,
        "workflow_version": workflow_version,
        "mapping_version_created_at": now,
        "change_type": "new_sop",
        "changed_by": "system",
        "created_at": now,
    }
    sop_mappings_col.insert_one(mapping_record)

    logger.info("Created SOP mapping: %s (doc_v=%s wf_v=%s)", sop_id, sop_document_version, workflow_version)
    return {
        "sop_id": sop_id,
        "sop_document_id": doc_id,
        "workflow_id": workflow_id,
        "sop_document_version": sop_document_version,
        "workflow_version": workflow_version,
        "status": "created",
    }


def create_sop_version(
    sop_id: str,
    doc_content: str,
    doc_filename: str,
    workflow_data: dict,
    workflow_filename: str,
    sop_document_version: str,
    workflow_version: str,
) -> dict:
    """Upload a new version of an existing SOP mapping.

    Validates that both proposed versions are valid progressions from the
    current highest. Archives the current active mapping, then creates new
    sop_documents, sop_workflows, and sop_mappings records.
    Raises ValueError on invalid versions or if sop_id not found.
    """
    if not validate_version_format(sop_document_version):
        raise ValueError(f"Invalid sop_document_version '{sop_document_version}': must be x.y format")
    if not validate_version_format(workflow_version):
        raise ValueError(f"Invalid workflow_version '{workflow_version}': must be x.y format")

    active = get_active_mapping(sop_id)
    if not active:
        raise ValueError(f"SOP ID '{sop_id}' not found")

    current_doc_v = active.get("sop_document_version", "1.0")
    current_wf_v = active.get("workflow_version", "1.0")

    if not is_valid_progression(current_doc_v, sop_document_version):
        minor_bump, major_bump = get_next_valid_versions(current_doc_v)
        raise ValueError(
            f"Invalid sop_document_version '{sop_document_version}': "
            f"from {current_doc_v} only {minor_bump} or {major_bump} are allowed"
        )
    if not is_valid_progression(current_wf_v, workflow_version):
        minor_bump, major_bump = get_next_valid_versions(current_wf_v)
        raise ValueError(
            f"Invalid workflow_version '{workflow_version}': "
            f"from {current_wf_v} only {minor_bump} or {major_bump} are allowed"
        )

    db = get_sync_db()
    sop_docs_col = db["sop_documents"]
    sop_wf_col = db["sop_workflows"]
    sop_mappings_col = db["sop_mappings"]

    # Archive current active mapping before creating new version
    _archive_mapping(active, "new_version")

    now = datetime.now(UTC)
    # Carry forward classifier metadata from active mapping
    doc = {
        "name": active.get("name", ""),
        "application": active.get("application", ""),
        "domain": active.get("domain", ""),
        "category": active.get("category", ""),
        "severity": active.get("severity", ""),
        "content": doc_content,
        "created_at": now,
    }
    doc_result = sop_docs_col.insert_one(doc)
    doc_id = str(doc_result.inserted_id)

    dynamic_classifiers = active.get("dynamic_classifiers", [])
    chroma_content = doc_content + _build_dynamic_text(dynamic_classifiers)
    index_sop_document(sop_id, chroma_content, {
        "application": active.get("application", ""),
        "domain": active.get("domain", ""),
        "category": active.get("category", ""),
        "severity": active.get("severity", ""),
        "sop_document_id": doc_id,
    })

    wf_data = {**{k: v for k, v in workflow_data.items() if k != "_id"}, "sop_id": sop_id}
    wf_result = sop_wf_col.insert_one(wf_data)
    workflow_id = str(wf_result.inserted_id)

    mapping_record = {
        "sop_document_file": doc_filename,
        "workflow_file": workflow_filename,
        "sop_id": sop_id,
        "name": active.get("name", ""),
        "application": active.get("application", ""),
        "domain": active.get("domain", ""),
        "category": active.get("category", ""),
        "severity": active.get("severity", ""),
        "dynamic_classifiers": dynamic_classifiers,
        "sop_document_id": doc_id,
        "workflow_id": workflow_id,
        "source": active.get("source", "ui"),
        "sop_document_version": sop_document_version,
        "workflow_version": workflow_version,
        "mapping_version_created_at": now,
        "change_type": "new_version",
        "changed_by": "system",
        "created_at": now,
    }
    sop_mappings_col.insert_one(mapping_record)

    logger.info(
        "Created new version for SOP %s (doc_v=%s wf_v=%s)",
        sop_id, sop_document_version, workflow_version,
    )
    return {
        "sop_id": sop_id,
        "sop_document_id": doc_id,
        "workflow_id": workflow_id,
        "sop_document_version": sop_document_version,
        "workflow_version": workflow_version,
        "status": "new_version_created",
    }


def update_classifier(sop_id: str, fields: dict) -> dict:
    """Update classifier metadata (name, application, domain, category, severity) for a SOP.

    Updates sop_mappings and sop_documents, re-indexes ChromaDB with new metadata.
    Returns the updated mapping record. Raises ValueError if sop_id not found.
    """
    db = get_sync_db()
    sop_mappings_col = db["sop_mappings"]
    sop_docs_col = db["sop_documents"]

    mapping = sop_mappings_col.find_one({"sop_id": sop_id})
    if not mapping:
        raise ValueError(f"SOP ID '{sop_id}' not found")

    allowed = {"name", "application", "domain", "category", "severity", "dynamic_classifiers"}
    update_fields = {k: v for k, v in fields.items() if k in allowed}

    sop_mappings_col.update_one({"sop_id": sop_id}, {"$set": update_fields})

    doc_id = mapping.get("sop_document_id")
    if doc_id:
        from bson import ObjectId
        sop_docs_col.update_one({"_id": ObjectId(doc_id)}, {"$set": update_fields})
        existing_doc = sop_docs_col.find_one({"_id": ObjectId(doc_id)})
        if existing_doc:
            merged = {**mapping, **update_fields}
            meta = {
                "application": merged.get("application", ""),
                "domain": merged.get("domain", ""),
                "category": merged.get("category", ""),
                "severity": merged.get("severity", ""),
                "sop_document_id": doc_id,
            }
            dc = merged.get("dynamic_classifiers", [])
            chroma_content = existing_doc.get("content", "") + _build_dynamic_text(dc)
            index_sop_document(sop_id, chroma_content, meta)

    updated = sop_mappings_col.find_one({"sop_id": sop_id}, {"_id": 0})
    logger.info("Updated classifier for SOP: %s", sop_id)
    return updated


def get_workflow_by_sop_id(sop_id: str) -> dict | None:
    """Return the workflow JSON for the active (highest-version) mapping of sop_id."""
    active = get_active_mapping(sop_id)
    if not active:
        return None
    workflow_id = active.get("workflow_id")
    if not workflow_id:
        return None
    from bson import ObjectId
    db = get_sync_db()
    doc = db["sop_workflows"].find_one({"_id": ObjectId(workflow_id)})
    if not doc:
        return None
    doc["_id"] = str(doc["_id"])
    return doc


def update_workflow(sop_id: str, workflow_data: dict) -> str:
    """Save edited workflow JSON, auto-incrementing workflow minor version.

    Archives the current active mapping to sop_mapping_history, inserts a new
    sop_workflows record with the bumped version, and updates the mapping record.
    Returns the new workflow version string.
    Raises ValueError if sop_id not found.
    """
    active = get_active_mapping(sop_id)
    if not active:
        raise ValueError(f"Workflow for SOP ID '{sop_id}' not found")

    current_wf_v = active.get("workflow_version", "1.0")
    minor_bump, _ = get_next_valid_versions(current_wf_v)
    new_wf_version = minor_bump

    # Archive current active mapping
    _archive_mapping(active, "workflow_edit")

    db = get_sync_db()
    sop_wf_col = db["sop_workflows"]
    sop_mappings_col = db["sop_mappings"]

    # Insert new workflow document
    wf_data = {**{k: v for k, v in workflow_data.items() if k != "_id"}, "sop_id": sop_id}
    wf_result = sop_wf_col.insert_one(wf_data)
    new_workflow_id = str(wf_result.inserted_id)

    # Update the active mapping record in-place (it remains the highest version)
    from bson import ObjectId
    now = datetime.now(UTC)
    sop_mappings_col.update_one(
        {"_id": ObjectId(active["_id"])},
        {"$set": {
            "workflow_version": new_wf_version,
            "workflow_id": new_workflow_id,
            "mapping_version_created_at": now,
            "change_type": "workflow_edit",
        }},
    )

    logger.info("Updated workflow for SOP %s: wf_v %s -> %s", sop_id, current_wf_v, new_wf_version)
    return new_wf_version


def get_mapping_history(sop_id: str) -> list[dict]:
    """Return archived mapping history for sop_id, newest first."""
    db = get_sync_db()
    col = db["sop_mapping_history"]
    docs = list(
        col.find({"sop_id": sop_id}, {"_id": 0}).sort("archived_at", -1)
    )
    return docs


def update_doc_file(sop_id: str, doc_content: str, doc_filename: str) -> None:
    """Update the SOP document content and re-index ChromaDB.

    Raises ValueError if sop_id not found in sop_mappings.
    """
    db = get_sync_db()
    sop_mappings_col = db["sop_mappings"]
    sop_docs_col = db["sop_documents"]

    mapping = sop_mappings_col.find_one({"sop_id": sop_id})
    if not mapping:
        raise ValueError(f"SOP ID '{sop_id}' not found")

    doc_id = mapping.get("sop_document_id")
    if doc_id:
        from bson import ObjectId
        sop_docs_col.update_one(
            {"_id": ObjectId(doc_id)},
            {"$set": {"content": doc_content, "source_filename": doc_filename}},
        )

    sop_mappings_col.update_one({"sop_id": sop_id}, {"$set": {"sop_document_file": doc_filename}})

    # Re-index ChromaDB with updated content
    index_sop_document(sop_id, doc_content, {
        "application": mapping.get("application", ""),
        "domain": mapping.get("domain", ""),
        "category": mapping.get("category", ""),
        "severity": mapping.get("severity", ""),
        "sop_document_id": doc_id or "",
    })
    logger.info("Updated doc file for SOP: %s", sop_id)
