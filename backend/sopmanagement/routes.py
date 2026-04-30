import json
import logging
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from typing import Optional

from backend.sopmanagement.service import (
    create_sop_mapping,
    get_all_mappings,
    get_mapping_by_sop_id,
    get_workflow_by_sop_id,
    load_mappings,
    seed_all,
    update_classifier,
    update_doc_file,
    update_workflow,
)

router = APIRouter(prefix="/api/sop-management", tags=["sop-management"])
logger = logging.getLogger(__name__)


@router.post("/seed", status_code=200)
def run_seed() -> dict[str, Any]:
    """Seed all SOP documents and workflows from the mapping data file."""
    results = seed_all()
    seeded = [r for r in results if r.get("status") == "seeded"]
    skipped = [r for r in results if r.get("status") == "skipped"]
    return {"seeded": len(seeded), "skipped": len(skipped), "details": results}


@router.get("/mappings")
def list_mappings() -> list[dict]:
    """Return all SOP mapping records."""
    return get_all_mappings()


@router.get("/mappings/{sop_id}")
def get_mapping(sop_id: str) -> dict:
    """Return a single SOP mapping by sop_id (e.g. SOP_HIGH_CPU)."""
    doc = get_mapping_by_sop_id(sop_id)
    if not doc:
        raise HTTPException(404, f"Mapping not found for sop_id: {sop_id}")
    return doc


@router.get("/mapping-config")
def get_mapping_config() -> dict:
    """Return the raw mapping config from data/sop_mappingdata.json."""
    return load_mappings()


@router.post("/mappings", status_code=201)
async def create_mapping(
    sop_id: str = Form(...),
    name: str = Form(...),
    application: str = Form(...),
    domain: str = Form(...),
    category: str = Form(...),
    severity: str = Form(...),
    doc_file: UploadFile = File(...),
    workflow_file: UploadFile = File(...),
    dynamic_classifiers: Optional[str] = Form(None),
) -> dict[str, Any]:
    """Create a new SOP mapping with uploaded doc and workflow JSON files."""
    doc_content = (await doc_file.read()).decode("utf-8", errors="replace")
    workflow_raw = (await workflow_file.read()).decode("utf-8", errors="replace")
    try:
        workflow_data = json.loads(workflow_raw)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"Invalid workflow JSON: {e}")
    parsed_dcs = []
    if dynamic_classifiers:
        try:
            parsed_dcs = json.loads(dynamic_classifiers)
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"Invalid dynamic_classifiers JSON: {e}")
    try:
        result = create_sop_mapping(
            sop_id=sop_id,
            name=name,
            application=application,
            domain=domain,
            category=category,
            severity=severity,
            doc_content=doc_content,
            doc_filename=doc_file.filename or "uploaded_doc.txt",
            workflow_data=workflow_data,
            workflow_filename=workflow_file.filename or "uploaded_workflow.json",
            dynamic_classifiers=parsed_dcs,
        )
    except ValueError as e:
        raise HTTPException(409, str(e))
    return result


@router.put("/mappings/{sop_id}/classifier")
def update_sop_classifier(sop_id: str, body: dict) -> dict:
    """Update classifier metadata (name, application, domain, category, severity)."""
    try:
        return update_classifier(sop_id, body)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/mappings/{sop_id}/workflow")
def get_sop_workflow(sop_id: str) -> dict:
    """Return the workflow JSON for a given sop_id."""
    doc = get_workflow_by_sop_id(sop_id)
    if not doc:
        raise HTTPException(404, f"Workflow not found for sop_id: {sop_id}")
    return doc


@router.put("/mappings/{sop_id}/workflow")
def update_sop_workflow(sop_id: str, body: dict) -> dict[str, str]:
    """Replace the workflow JSON for a given sop_id."""
    try:
        update_workflow(sop_id, body)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"status": "updated"}


@router.post("/mappings/{sop_id}/doc-file")
async def update_sop_doc_file(sop_id: str, file: UploadFile = File(...)) -> dict[str, str]:
    """Upload a new SOP document file, updating content and re-indexing ChromaDB."""
    content = (await file.read()).decode("utf-8", errors="replace")
    try:
        update_doc_file(sop_id, content, file.filename or "uploaded_doc.txt")
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"status": "updated"}
