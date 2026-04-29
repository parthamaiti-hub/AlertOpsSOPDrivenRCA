import logging
from datetime import UTC, datetime

from bson import ObjectId
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from backend.identifySOP.rag import index_sop_document
from backend.models.database import sop_documents_col, sop_workflows_col
from backend.models.schemas import SOPWorkflow

router = APIRouter(prefix="/api/sop", tags=["sop"])
logger = logging.getLogger(__name__)


@router.post("/upload", status_code=201)
async def upload_sop(
    file: UploadFile = File(...),
    sop_id: str = Form(...),
    name: str = Form(...),
    application: str = Form(...),
    domain: str = Form(...),
    category: str = Form(...),
    severity: str = Form(...),
):
    raw = await file.read()
    content_type = file.content_type or ""
    if "pdf" in content_type:
        from pypdf import PdfReader
        import io
        reader = PdfReader(io.BytesIO(raw))
        text = "\n".join(p.extract_text() or "" for p in reader.pages)
    elif "word" in content_type or file.filename.endswith(".docx"):
        from docx import Document
        import io
        doc = Document(io.BytesIO(raw))
        text = "\n".join(p.text for p in doc.paragraphs)
    else:
        text = raw.decode("utf-8", errors="replace")

    doc = {
        "name": name,
        "application": application,
        "domain": domain,
        "category": category,
        "severity": severity,
        "content": text,
        "created_at": datetime.now(UTC),
    }
    result = await sop_documents_col().insert_one(doc)
    doc_id = str(result.inserted_id)
    index_sop_document(sop_id, text, {
        "application": application,
        "domain": domain,
        "category": category,
        "severity": severity,
        "sop_document_id": doc_id,
    })
    return {"sop_id": sop_id, "sop_document_id": doc_id}


@router.post("/workflows", status_code=201)
async def create_workflow(workflow: SOPWorkflow):
    doc = workflow.model_dump()
    doc["created_at"] = datetime.now(UTC)
    result = await sop_workflows_col().insert_one(doc)
    return {"workflow_id": str(result.inserted_id)}


@router.get("/workflows/{workflow_id}")
async def get_workflow(workflow_id: str):
    doc = await sop_workflows_col().find_one({"_id": ObjectId(workflow_id)})
    if not doc:
        raise HTTPException(404, "Workflow not found")
    doc["_id"] = str(doc["_id"])
    return doc
