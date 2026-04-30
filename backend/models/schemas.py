from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class DynamicClassifier(BaseModel):
    label: str
    field_name: str = ""
    field_value: str = ""


class Alert(BaseModel):
    source_type: str = ""  # file | webhook | api
    source_ref: str = ""  # filename for file source, endpoint URL for webhook/api
    source_application: str = ""
    domain: str = ""
    category: str = ""
    severity: str = ""
    sop_identifier_keys: list[str] = []
    raw_payload: dict[str, Any] = {}
    alert_type: str = "structured"  # structured | text
    alert_text: str = ""
    status: str = "ingested"
    processing_status: str = "ingested"  # ingested | processedSuccessfully | SOPNotFound | RCANotFound | RCANotValidated | sop_workflow_processfailed
    feedback_received: bool = False
    sop_document_id: str | None = None
    sop_workflow_id: str | None = None
    sop_id: str | None = None
    # Retry metadata
    latest_retry_batch_id: str | None = None
    latest_retry_level: str | None = None
    retry_in_progress: bool = False
    retry_requested_at: datetime | None = None
    retry_attempt_count: int = 0
    latest_effective_rca_id: str | None = None
    logged_at: datetime | None = None
    processed_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TextAlert(BaseModel):
    alert_text: str
    raw_payload: dict[str, Any] = {}


class SOPDocument(BaseModel):
    name: str
    application: str
    domain: str
    category: str
    severity: str
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SOPWorkflow(BaseModel):
    sop_id: str
    alert_identifier: dict[str, str] = {}
    triaging_steps: list[dict[str, Any]] = []
    communication_steps: list[dict[str, Any]] = []
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RCAResult(BaseModel):
    alert_id: str
    sop_id: str
    workflow_id: str
    triaging_results: list[dict[str, Any]] = []
    root_cause: str = ""
    impact: str = ""
    recommendation: str = ""
    validation_assessment: str | None = None
    confidence_score: float | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ValidationResult(BaseModel):
    alert_id: str
    rca_id: str
    assessment: str
    confidence_score: float
    similar_past_rcas: list[str] = []
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Feedback(BaseModel):
    alert_id: str
    comment: str
    confidence_score: float
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Retry models
# ---------------------------------------------------------------------------

RetryLevel = Literal["level1", "level2", "level3", "level4"]
RetryAttemptState = Literal[
    "queued",
    "running_stage1",
    "running_stage2",
    "running_stage3",
    "completed",
    "failed",
    "partially_completed",
]


class RetryRequest(BaseModel):
    alert_ids: list[str]
    retry_level: RetryLevel
    reason: str | None = None


class RetryAttemptResponse(BaseModel):
    alert_id: str
    accepted: bool
    batch_id: str | None = None
    reason: str | None = None


class SOPMapping(BaseModel):
    sop_document_file: str
    workflow_file: str
    sop_id: str
    name: str
    application: str
    domain: str
    category: str
    severity: str
    dynamic_classifiers: list[DynamicClassifier] = []
    sop_document_id: str | None = None
    workflow_id: str | None = None
    seeded: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
