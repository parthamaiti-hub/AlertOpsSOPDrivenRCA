import json
import logging
from datetime import UTC, datetime
from typing import Any, Optional

from bson import ObjectId
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

from backend.config.settings import settings
from backend.eventprocessing.rabbitmq import consume
from backend.models.database import (
    alert_retry_attempts_col_sync,
    alerts_col_sync,
    rca_results_col_sync,
    retry_stage_events_col_sync,
    validation_results_col_sync,
)
from backend.prompts.loader import get_loader
from backend.validateRCA.rag import index_rca, search_similar_rcas

logger = logging.getLogger(__name__)


class ValidateState(TypedDict, total=False):
    message: dict
    rca: Optional[dict]
    similar_rcas: list
    validation: dict


def _build_graph():
    llm = ChatOpenAI(model="gpt-4o-mini", openai_api_key=settings.openai_api_key)

    def load_rca(state: ValidateState) -> dict:
        msg = state["message"]
        rca_id = msg.get("rca_id", "")
        rca = rca_results_col_sync().find_one({"_id": ObjectId(rca_id)})
        if rca:
            rca["_id"] = str(rca["_id"])
        return {"rca": rca}

    def query_past_rcas(state: ValidateState) -> dict:
        rca = state.get("rca")
        if not rca:
            return {"similar_rcas": []}
        query = f"{rca.get('root_cause', '')} {rca.get('impact', '')}"
        return {"similar_rcas": search_similar_rcas(query)}

    def validate(state: ValidateState) -> dict:
        rca = state.get("rca", {})
        similar = state.get("similar_rcas", [])
        similar_summary = json.dumps(similar[:3], default=str)[:2000]

        prompt = get_loader().get_prompt("validate_rca", "validate").format_map({
            "root_cause": rca.get("root_cause", "N/A"),
            "impact": rca.get("impact", "N/A"),
            "recommendation": rca.get("recommendation", "N/A"),
            "similar_summary": similar_summary,
        })
        resp = llm.invoke(prompt)
        try:
            text = resp.content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            result = json.loads(text)
        except (json.JSONDecodeError, IndexError):
            result = {"assessment": resp.content, "confidence_score": 50}

        return {"validation": result}

    graph = StateGraph(ValidateState)
    graph.add_node("load_rca", load_rca)
    graph.add_node("query_past_rcas", query_past_rcas)
    graph.add_node("validate", validate)
    graph.set_entry_point("load_rca")
    graph.add_edge("load_rca", "query_past_rcas")
    graph.add_edge("query_past_rcas", "validate")
    graph.add_edge("validate", END)
    return graph.compile()


_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        _graph = _build_graph()
    return _graph


def _update_retry_state(batch_id: str | None, alert_id: str, state: str, error: str | None = None):
    if not batch_id:
        return
    update: dict = {"state": state}
    if state in ("completed", "failed"):
        update["completed_at"] = datetime.now(UTC)
    if error:
        update["error_summary"] = error
    alert_retry_attempts_col_sync().update_one(
        {"batch_id": batch_id, "alert_id": alert_id},
        {"$set": update},
    )
    stage_update: dict = {"status": state}
    if state == "running_stage3":
        stage_update["started_at"] = datetime.now(UTC)
    else:
        stage_update["completed_at"] = datetime.now(UTC)
    retry_stage_events_col_sync().update_one(
        {"batch_id": batch_id, "alert_id": alert_id, "stage": "stage3_validate"},
        {"$set": stage_update},
        upsert=True,
    )


def _process(msg: dict):
    alert_id = msg.get("alert_id", "")
    rca_id = msg.get("rca_id", "")
    batch_id = msg.get("retry_batch_id")
    retry_level = msg.get("retry_level")
    run_kind = msg.get("run_kind", "primary")
    logger.info("ValidateRCA processing alert %s, rca %s", alert_id, rca_id)

    _update_retry_state(batch_id, alert_id, "running_stage3")

    graph = _get_graph()
    result = graph.invoke({"message": msg})

    validation = result.get("validation", {})
    rca = result.get("rca", {})

    # Store validation result with retry metadata
    val_doc: dict = {
        "alert_id": alert_id,
        "rca_id": rca_id,
        "assessment": validation.get("assessment", ""),
        "confidence_score": validation.get("confidence_score", 0),
        "similar_past_rcas": [r.get("id", "") for r in result.get("similar_rcas", [])],
        "is_active_latest": True,
        "run_kind": run_kind,
    }
    if batch_id:
        val_doc["retry_batch_id"] = batch_id
    if retry_level:
        val_doc["retry_level"] = retry_level
    validation_results_col_sync().insert_one(val_doc)

    # Update RCA with validation
    rca_results_col_sync().update_one(
        {"_id": ObjectId(rca_id)},
        {"$set": {
            "validation_assessment": validation.get("assessment", ""),
            "confidence_score": validation.get("confidence_score", 0),
        }},
    )

    # Update alert status and clear retry_in_progress
    confidence = validation.get("confidence_score", 0)
    alert_update: dict = {}
    if confidence and confidence > 0:
        alert_update = {"status": "completed", "processing_status": "processedSuccessfully"}
    else:
        alert_update = {"status": "validation_failed", "processing_status": "RCANotValidated"}
    if batch_id:
        alert_update["retry_in_progress"] = False
    alerts_col_sync().update_one({"_id": ObjectId(alert_id)}, {"$set": alert_update})

    _update_retry_state(batch_id, alert_id, "completed" if (confidence and confidence > 0) else "failed")

    # Index this RCA for future lookups
    rca_text = f"Root cause: {rca.get('root_cause', '')}. Impact: {rca.get('impact', '')}. Recommendation: {rca.get('recommendation', '')}"
    index_rca(rca_id, rca_text, {"alert_id": alert_id})

    logger.info("Alert %s validation complete (score=%s)", alert_id, validation.get("confidence_score"))


def run_worker():
    logger.info("Starting ValidateRCA worker")
    consume("stage3_validate", _process)
