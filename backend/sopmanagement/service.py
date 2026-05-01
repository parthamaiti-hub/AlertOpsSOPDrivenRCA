import json
import logging
import pathlib
from datetime import UTC, datetime

from backend.identifySOP.rag import index_sop_document, is_sop_indexed
from backend.models.database import get_sync_db

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


def _build_sop_keys_text(keys: list) -> str:
    """Build text from workflow sop_identifier_keys for ChromaDB indexing."""
    if not keys:
        return ""
    return " | sop_keys: " + ", ".join(str(k) for k in keys)


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
                wf_doc = sop_wf_col.find_one({"_id": ObjectId(existing["workflow_id"])}) if existing.get("workflow_id") else None
                wf_keys = (wf_doc.get("alert_identifier") or {}).get("sop_identifier_keys", []) if wf_doc else []
                if sop_doc:
                    try:
                        chroma_content = sop_doc["content"] + _build_dynamic_text(dynamic_classifiers) + _build_sop_keys_text(wf_keys)
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

            # Sync workflow structural changes (remediation_steps, escalation, etc.) if workflow file changed
            workflow_id = existing.get("workflow_id", "")
            if workflow_id and meta.get("workflow_file"):
                workflow_path = DATA_DIR / "sop_workflows" / meta["workflow_file"]
                if workflow_path.exists():
                    file_wf = json.loads(workflow_path.read_text())
                    from bson import ObjectId
                    stored_wf = sop_wf_col.find_one({"_id": ObjectId(workflow_id)}) if workflow_id else None
                    if stored_wf:
                        _WORKFLOW_SECTIONS = ["alert_identifier", "triaging_steps", "remediation_steps", "communication_steps", "escalation"]
                        if any(file_wf.get(s) != stored_wf.get(s) for s in _WORKFLOW_SECTIONS):
                            update_fields = {s: file_wf.get(s, stored_wf.get(s)) for s in _WORKFLOW_SECTIONS}
                            sop_wf_col.update_one({"_id": ObjectId(workflow_id)}, {"$set": update_fields})
                            logger.info("Updated workflow sections for SOP: %s", sop_id)
                            # Re-index ChromaDB with updated sop_identifier_keys from new workflow
                            wf_keys = (file_wf.get("alert_identifier") or {}).get("sop_identifier_keys", [])
                            sop_doc = sop_docs_col.find_one({"_id": ObjectId(doc_id)}) if doc_id else None
                            if sop_doc:
                                dc = existing.get("dynamic_classifiers", [])
                                chroma_content = sop_doc["content"] + _build_dynamic_text(dc) + _build_sop_keys_text(wf_keys)
                                try:
                                    index_sop_document(sop_id, chroma_content, {
                                        "application": existing.get("application", ""),
                                        "domain": existing.get("domain", ""),
                                        "category": existing.get("category", ""),
                                        "severity": existing.get("severity", ""),
                                        "sop_document_id": doc_id,
                                    })
                                except Exception as e:
                                    logger.error("Failed to re-index ChromaDB for %s: %s", sop_id, e)
                            results.append({"sop_document_file": sop_doc_filename, "sop_id": sop_id, "status": "updated_workflow"})
                            continue

            if sop_id and not is_sop_indexed(sop_id):
                logger.warning("SOP %s in MongoDB but missing from ChromaDB — re-indexing", sop_id)
                from bson import ObjectId
                sop_doc = sop_docs_col.find_one({"_id": ObjectId(doc_id)}) if doc_id else None
                if sop_doc:
                    try:
                        wf_doc = sop_wf_col.find_one({"_id": ObjectId(existing.get("workflow_id", ""))}) if existing.get("workflow_id") else None
                        wf_keys = (wf_doc.get("alert_identifier") or {}).get("sop_identifier_keys", []) if wf_doc else []
                        dc = existing.get("dynamic_classifiers", [])
                        chroma_content = sop_doc["content"] + _build_dynamic_text(dc) + _build_sop_keys_text(wf_keys)
                        index_sop_document(sop_id, chroma_content, {
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
        wf_keys = (workflow_data.get("alert_identifier") or {}).get("sop_identifier_keys", [])
        chroma_content = content + _build_dynamic_text(dynamic_classifiers) + _build_sop_keys_text(wf_keys)
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
            "created_at": datetime.now(UTC),
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


def get_mapping_by_sop_id(sop_id: str) -> dict | None:
    """Return a single mapping record by sop_id."""
    db = get_sync_db()
    col = db["sop_mappings"]
    doc = col.find_one({"sop_id": sop_id}, {"_id": 0})
    return doc


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
) -> dict:
    """Create a new SOP mapping with document, workflow, and ChromaDB entry.

    Raises ValueError if sop_id already exists in sop_mappings.
    The sop_id field in workflow_data is overridden to match the provided sop_id.
    """
    db = get_sync_db()
    sop_docs_col = db["sop_documents"]
    sop_wf_col = db["sop_workflows"]
    sop_mappings_col = db["sop_mappings"]
    dynamic_classifiers = dynamic_classifiers or []

    if sop_mappings_col.find_one({"sop_id": sop_id}):
        raise ValueError(f"SOP ID '{sop_id}' already exists")

    # Override sop_id in workflow data with the canonical value
    workflow_data = {**workflow_data, "sop_id": sop_id}

    doc = {
        "name": name,
        "application": application,
        "domain": domain,
        "category": category,
        "severity": severity,
        "content": doc_content,
        "created_at": datetime.now(UTC),
    }
    doc_result = sop_docs_col.insert_one(doc)
    doc_id = str(doc_result.inserted_id)

    wf_keys = (workflow_data.get("alert_identifier") or {}).get("sop_identifier_keys", [])
    chroma_content = doc_content + _build_dynamic_text(dynamic_classifiers) + _build_sop_keys_text(wf_keys)
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
        "created_at": datetime.now(UTC),
    }
    sop_mappings_col.insert_one(mapping_record)

    logger.info("Created SOP mapping: %s", sop_id)
    return {
        "sop_id": sop_id,
        "sop_document_id": doc_id,
        "workflow_id": workflow_id,
        "status": "created",
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
            wf_doc = db["sop_workflows"].find_one({"sop_id": sop_id})
            wf_keys = (wf_doc.get("alert_identifier") or {}).get("sop_identifier_keys", []) if wf_doc else []
            chroma_content = existing_doc.get("content", "") + _build_dynamic_text(dc) + _build_sop_keys_text(wf_keys)
            index_sop_document(sop_id, chroma_content, meta)

    updated = sop_mappings_col.find_one({"sop_id": sop_id}, {"_id": 0})
    logger.info("Updated classifier for SOP: %s", sop_id)
    return updated


def get_workflow_by_sop_id(sop_id: str) -> dict | None:
    """Return the workflow JSON dict from sop_workflows for the given sop_id."""
    db = get_sync_db()
    col = db["sop_workflows"]
    doc = col.find_one({"sop_id": sop_id})
    if not doc:
        return None
    if "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc


def update_workflow(sop_id: str, workflow_data: dict) -> None:
    """Replace the workflow document in sop_workflows for the given sop_id.

    Preserves the existing MongoDB _id. Raises ValueError if sop_id not found.
    """
    db = get_sync_db()
    col = db["sop_workflows"]

    existing = col.find_one({"sop_id": sop_id}, {"_id": 1})
    if not existing:
        raise ValueError(f"Workflow for SOP ID '{sop_id}' not found")

    # Remove _id from incoming data so it doesn't conflict
    data = {k: v for k, v in workflow_data.items() if k != "_id"}
    data["sop_id"] = sop_id  # Ensure canonical sop_id is preserved

    col.replace_one({"_id": existing["_id"]}, data)
    logger.info("Updated workflow for SOP: %s", sop_id)


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
    dc = mapping.get("dynamic_classifiers", [])
    wf_doc = db["sop_workflows"].find_one({"sop_id": sop_id})
    wf_keys = (wf_doc.get("alert_identifier") or {}).get("sop_identifier_keys", []) if wf_doc else []
    chroma_content = doc_content + _build_dynamic_text(dc) + _build_sop_keys_text(wf_keys)
    index_sop_document(sop_id, chroma_content, {
        "application": mapping.get("application", ""),
        "domain": mapping.get("domain", ""),
        "category": mapping.get("category", ""),
        "severity": mapping.get("severity", ""),
        "sop_document_id": doc_id or "",
    })
    logger.info("Updated doc file for SOP: %s", sop_id)
