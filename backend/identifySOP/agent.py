import json
import logging
from datetime import UTC, datetime
from typing import Any, Optional

from bson import ObjectId
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

from backend.config.settings import settings
from backend.eventprocessing.rabbitmq import consume, publish
from backend.identifySOP.rag import search_sop
from backend.models.database import (
    alert_retry_attempts_col_sync,
    alerts_col_sync,
    classifier_match_logs_col_sync,
    retry_stage_events_col_sync,
    sop_mappings_col_sync,
    sop_workflows_col_sync,
)
from backend.prompts.loader import get_loader
from backend.utils import strip_rtf

logger = logging.getLogger(__name__)


class IdentifyState(TypedDict, total=False):
    message: dict
    classifier: dict
    dynamic_fields: dict
    sop_matches: list
    selected_sop_id: Optional[str]
    workflow_id: Optional[str]
    mapping_score: float
    classifier_match_log: dict


def _get_all_dynamic_field_names() -> list[str]:
    """Fetch distinct dynamic classifier field names from sop_mappings."""
    col = sop_mappings_col_sync()
    pipeline = [
        {"$unwind": "$dynamic_classifiers"},
        {"$group": {"_id": "$dynamic_classifiers.field_name"}},
        {"$match": {"_id": {"$ne": ""}}},
    ]
    return [doc["_id"] for doc in col.aggregate(pipeline)]


def _compute_mapping_score(alert_dynamic: dict, sop_dynamic_classifiers: list[dict]) -> tuple[float, dict]:
    """Compute mapping_score = round((matched / total) * 100, 1).

    Returns (score, detail_dict) where detail_dict has per-field match info.
    """
    if not sop_dynamic_classifiers:
        return (0.0, {})
    total = len(sop_dynamic_classifiers)
    detail = {}
    matched = 0
    for dc in sop_dynamic_classifiers:
        fn = dc.get("field_name", "")
        expected = dc.get("field_value", "").lower().strip()
        actual = str(alert_dynamic.get(fn, "")).lower().strip()
        is_match = expected != "" and actual != "" and expected == actual
        if is_match:
            matched += 1
        detail[fn] = {"expected": dc.get("field_value", ""), "actual": alert_dynamic.get(fn, ""), "match": is_match}
    score = round((matched / total) * 100, 1) if total > 0 else 0.0
    return (score, detail)


def _build_graph():
    llm = ChatOpenAI(model="gpt-4o-mini", openai_api_key=settings.openai_api_key)

    def extract_fields(state: IdentifyState) -> dict:
        msg = state["message"]
        alert_type = msg.get("alert_type", "structured")

        if alert_type == "text":
            # For text alerts, use LLM to extract classifiers
            return {"classifier": {
                "application": "",
                "domain": "",
                "category": "",
                "severity": "",
                "sop_keys": [],
            }, "dynamic_fields": {}}

        return {"classifier": {
            "application": msg.get("source_application", ""),
            "domain": msg.get("domain", ""),
            "category": msg.get("category", ""),
            "severity": msg.get("severity", ""),
            "sop_keys": msg.get("sop_identifier_keys", []),
        }, "dynamic_fields": {}}

    def llm_extract_classifiers(state: IdentifyState) -> dict:
        """Use LLM to extract classifiers from unstructured alert text."""
        msg = state["message"]
        alert_text = msg.get("alert_text", "")
        # Strip RTF if present
        plain_text = strip_rtf(alert_text)

        field_names = _get_all_dynamic_field_names()
        if not field_names:
            field_names = ["environment", "region", "host_type", "operating_system", "cloud_provider", "alert_source", "service_tier"]

        prompt = get_loader().get_prompt("identify_sop", "extract_classifiers").format_map({
            "field_names": ", ".join(field_names),
            "alert_text": plain_text,
        })
        resp = llm.invoke(prompt)
        raw = resp.content.strip()
        # Parse JSON from response
        try:
            # Handle markdown code blocks
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM classifier extraction response: %s", raw[:200])
            data = {}

        classifier = {
            "application": data.get("application", ""),
            "domain": data.get("domain", ""),
            "category": data.get("category", ""),
            "severity": data.get("severity", ""),
            "sop_keys": data.get("sop_identifier_keys", []),
        }
        dynamic_fields = data.get("dynamic_fields", {})
        return {"classifier": classifier, "dynamic_fields": dynamic_fields}

    def route_after_extract(state: IdentifyState) -> str:
        msg = state["message"]
        if msg.get("alert_type", "structured") == "text":
            return "llm_extract_classifiers"
        return "query_rag"

    def query_rag(state: IdentifyState) -> dict:
        c = state["classifier"]
        dynamic = state.get("dynamic_fields", {})
        # Build query from classifiers + dynamic fields
        parts = [c["application"], c["domain"], c["category"]]
        parts.extend(c.get("sop_keys", []))
        parts.extend(str(v) for v in dynamic.values() if v)
        query_text = " ".join(p for p in parts if p)
        results = search_sop(query_text)
        return {"sop_matches": results}

    def score_and_select_sop(state: IdentifyState) -> dict:
        matches = state.get("sop_matches", [])
        if not matches:
            return {"selected_sop_id": None, "mapping_score": 0.0, "classifier_match_log": {}}

        c = state["classifier"]
        dynamic = state.get("dynamic_fields", {})

        # Score each match against dynamic classifiers
        scored_matches = []
        for m in matches[:5]:
            sop_id = m["sop_id"]
            mapping = sop_mappings_col_sync().find_one({"sop_id": sop_id})
            dc_list = mapping.get("dynamic_classifiers", []) if mapping else []
            score, detail = _compute_mapping_score(dynamic, dc_list)
            scored_matches.append({**m, "mapping_score": score, "match_detail": detail})

        # Build match_info for LLM
        match_info_for_llm = []
        for sm in scored_matches:
            entry = {"sop_id": sm["sop_id"], "mapping_score": sm["mapping_score"]}
            if sm.get("metadata"):
                entry["metadata"] = sm["metadata"]
            match_info_for_llm.append(entry)

        prompt = get_loader().get_prompt("identify_sop", "select_sop").format_map({
            "application": c["application"],
            "domain": c["domain"],
            "category": c["category"],
            "severity": c["severity"],
            "sop_keys": c.get("sop_keys", []),
            "dynamic_fields": json.dumps(dynamic, default=str),
            "match_info": json.dumps(match_info_for_llm, default=str),
        })
        resp = llm.invoke(prompt)
        selected_id = resp.content.strip()

        valid_ids = [m["sop_id"] for m in scored_matches]
        if selected_id not in valid_ids:
            # Fall back to highest mapping_score, then first result
            scored_matches.sort(key=lambda x: x["mapping_score"], reverse=True)
            selected_id = scored_matches[0]["sop_id"]

        selected_match = next((m for m in scored_matches if m["sop_id"] == selected_id), scored_matches[0])

        log_entry = {
            "sop_id": selected_id,
            "static_classifiers": c,
            "dynamic_fields_extracted": dynamic,
            "mapping_score": selected_match["mapping_score"],
            "match_detail": selected_match.get("match_detail", {}),
            "all_candidates": [{"sop_id": m["sop_id"], "mapping_score": m["mapping_score"]} for m in scored_matches],
        }

        return {
            "selected_sop_id": selected_id,
            "mapping_score": selected_match["mapping_score"],
            "classifier_match_log": log_entry,
        }

    def log_classifier_match(state: IdentifyState) -> dict:
        log_entry = state.get("classifier_match_log", {})
        if log_entry:
            alert_id = state["message"].get("alert_id", "")
            log_entry["alert_id"] = alert_id
            log_entry["alert_type"] = state["message"].get("alert_type", "structured")
            log_entry["created_at"] = datetime.now(UTC)
            classifier_match_logs_col_sync().insert_one(log_entry)
            logger.info("Logged classifier match for alert %s: score=%s", alert_id, log_entry.get("mapping_score"))
        return {}

    graph = StateGraph(IdentifyState)
    graph.add_node("extract_fields", extract_fields)
    graph.add_node("llm_extract_classifiers", llm_extract_classifiers)
    graph.add_node("query_rag", query_rag)
    graph.add_node("score_and_select_sop", score_and_select_sop)
    graph.add_node("log_classifier_match", log_classifier_match)
    graph.set_entry_point("extract_fields")
    graph.add_conditional_edges("extract_fields", route_after_extract, {
        "llm_extract_classifiers": "llm_extract_classifiers",
        "query_rag": "query_rag",
    })
    graph.add_edge("llm_extract_classifiers", "query_rag")
    graph.add_edge("query_rag", "score_and_select_sop")
    graph.add_edge("score_and_select_sop", "log_classifier_match")
    graph.add_edge("log_classifier_match", END)
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
    if error:
        update["error_summary"] = error
        update["completed_at"] = datetime.now(UTC)
    alert_retry_attempts_col_sync().update_one(
        {"batch_id": batch_id, "alert_id": alert_id},
        {"$set": update},
    )
    stage_update: dict = {"status": state}
    if state == "running_stage1":
        stage_update["started_at"] = datetime.now(UTC)
    else:
        stage_update["completed_at"] = datetime.now(UTC)
    retry_stage_events_col_sync().update_one(
        {"batch_id": batch_id, "alert_id": alert_id, "stage": "stage1_identify"},
        {"$set": stage_update},
        upsert=True,
    )


def _process(msg: dict):
    alert_id = msg.get("alert_id", "")
    batch_id = msg.get("retry_batch_id")
    logger.info("IdentifySOP processing alert %s", alert_id)

    _update_retry_state(batch_id, alert_id, "running_stage1")

    graph = _get_graph()
    result = graph.invoke({"message": msg})

    sop_id = result.get("selected_sop_id")
    mapping_score = result.get("mapping_score", 0.0)
    workflow_id = None

    if sop_id:
        wf = sop_workflows_col_sync().find_one({"sop_id": sop_id})
        if wf:
            workflow_id = str(wf["_id"])

        # Stamp the classifier log with retry metadata
        if batch_id:
            latest_log = classifier_match_logs_col_sync().find_one(
                {"alert_id": alert_id, "created_at": {"$exists": True}},
                sort=[("created_at", -1)],
            )
            if latest_log:
                classifier_match_logs_col_sync().update_one(
                    {"_id": latest_log["_id"]},
                    {"$set": {"is_active_latest": True, "retry_batch_id": batch_id, "run_kind": "retry"}},
                )

        alerts_col_sync().update_one(
            {"_id": ObjectId(alert_id)},
            {"$set": {
                "status": "sop_identified",
                "processing_status": "sop_identified",
                "sop_document_id": sop_id,
                "sop_workflow_id": workflow_id,
                "sop_id": sop_id,
                "mapping_score": mapping_score,
            }},
        )

        outbound = {**msg, "sop_document_id": sop_id, "sop_workflow_id": workflow_id, "sop_id": sop_id, "mapping_score": mapping_score}
        publish("stage2_execute", outbound)
        logger.info("Alert %s matched SOP %s, workflow %s, score %s", alert_id, sop_id, workflow_id, mapping_score)
    else:
        alerts_col_sync().update_one(
            {"_id": ObjectId(alert_id)},
            {"$set": {"status": "sop_not_found", "processing_status": "SOPNotFound", "processed_at": datetime.now(UTC)}},
        )
        _update_retry_state(batch_id, alert_id, "failed", "SOP not found")
        if batch_id:
            alerts_col_sync().update_one(
                {"_id": ObjectId(alert_id)},
                {"$set": {"retry_in_progress": False}},
            )
        logger.warning("No SOP found for alert %s", alert_id)


def run_worker():
    logger.info("Starting IdentifySOP worker")
    consume("stage1_identify", _process)
