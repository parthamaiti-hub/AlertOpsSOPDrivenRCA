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
from backend.models.database import (
    alert_retry_attempts_col_sync,
    alerts_col_sync,
    rca_results_col_sync,
    retry_stage_events_col_sync,
    sop_workflows_col_sync,
)
from backend.prompts.loader import get_loader
from backend.tools.registry import execute_tool

logger = logging.getLogger(__name__)


class ExecuteState(TypedDict, total=False):
    message: dict
    workflow: Optional[dict]
    triaging_results: list
    rca: dict


def _build_graph():
    llm = ChatOpenAI(model="gpt-4o-mini", openai_api_key=settings.openai_api_key)

    def load_workflow(state: ExecuteState) -> dict:
        msg = state["message"]
        workflow_id = msg.get("sop_workflow_id")
        if not workflow_id:
            return {"workflow": None}
        wf = sop_workflows_col_sync().find_one({"_id": ObjectId(workflow_id)})
        if wf:
            wf["_id"] = str(wf["_id"])
        return {"workflow": wf}

    def execute_triaging(state: ExecuteState) -> dict:
        wf = state.get("workflow")
        msg = state["message"]
        if not wf:
            return {"triaging_results": []}

        raw_payload = msg.get("raw_payload", {})
        host = raw_payload.get("host", "unknown")
        application = msg.get("source_application", "unknown")

        results = []
        for step in wf.get("triaging_steps", []):
            tool_name = step.get("tool", "")
            params = dict(step.get("tool_params", {}))

            # Validate tool_params are present and non-empty
            if not params or not tool_name:
                results.append({
                    "step_id": step.get("step_id"),
                    "action": step.get("action", ""),
                    "tool": tool_name,
                    "tool_params": params,
                    "output": None,
                    "status": "failed",
                    "error": "insufficient tool specification",
                })
                continue

            # Substitute template variables
            for k, v in params.items():
                if isinstance(v, str):
                    params[k] = v.replace("{host}", host).replace("{application}", application)

            try:
                tool_output = execute_tool(tool_name, params)
                if isinstance(tool_output, dict) and "error" in tool_output:
                    results.append({
                        "step_id": step.get("step_id"),
                        "action": step.get("action", ""),
                        "tool": tool_name,
                        "tool_params": params,
                        "output": tool_output,
                        "status": "failed",
                        "error": tool_output["error"],
                    })
                else:
                    results.append({
                        "step_id": step.get("step_id"),
                        "action": step.get("action", ""),
                        "tool": tool_name,
                        "tool_params": params,
                        "output": tool_output,
                        "status": "success",
                    })
            except Exception as exc:
                logger.exception("Tool %s failed for alert %s step %s", tool_name, msg.get("alert_id"), step.get("step_id"))
                results.append({
                    "step_id": step.get("step_id"),
                    "action": step.get("action", ""),
                    "tool": tool_name,
                    "tool_params": params,
                    "output": None,
                    "status": "failed",
                    "error": str(exc),
                })
        return {"triaging_results": results}

    def generate_rca(state: ExecuteState) -> dict:
        msg = state["message"]
        results = state.get("triaging_results", [])
        results_summary = json.dumps(results, default=str)[:4000]

        prompt = get_loader().get_prompt("execute_sop", "generate_rca").format_map({
            "source_application": msg.get("source_application", ""),
            "domain": msg.get("domain", ""),
            "category": msg.get("category", ""),
            "severity": msg.get("severity", ""),
            "raw_payload": json.dumps(msg.get("raw_payload", {})),
            "results_summary": results_summary,
        })
        resp = llm.invoke(prompt)
        try:
            # Try to parse JSON from response
            text = resp.content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            rca = json.loads(text)
        except (json.JSONDecodeError, IndexError):
            rca = {"root_cause": resp.content, "impact": "See analysis above", "recommendation": "Review manually"}
        return {"rca": rca}

    graph = StateGraph(ExecuteState)
    graph.add_node("load_workflow", load_workflow)
    graph.add_node("execute_triaging", execute_triaging)
    graph.add_node("generate_rca", generate_rca)
    graph.set_entry_point("load_workflow")
    graph.add_edge("load_workflow", "execute_triaging")
    graph.add_edge("execute_triaging", "generate_rca")
    graph.add_edge("generate_rca", END)
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
    if state == "running_stage2":
        stage_update["started_at"] = datetime.now(UTC)
    else:
        stage_update["completed_at"] = datetime.now(UTC)
    retry_stage_events_col_sync().update_one(
        {"batch_id": batch_id, "alert_id": alert_id, "stage": "stage2_execute"},
        {"$set": stage_update},
        upsert=True,
    )


def _process(msg: dict):
    alert_id = msg.get("alert_id", "")
    batch_id = msg.get("retry_batch_id")
    retry_level = msg.get("retry_level")
    run_kind = msg.get("run_kind", "primary")
    logger.info("ExecuteSOP processing alert %s", alert_id)

    _update_retry_state(batch_id, alert_id, "running_stage2")

    graph = _get_graph()
    result = graph.invoke({"message": msg})

    rca = result.get("rca", {})
    triaging_results = result.get("triaging_results", [])

    # Check if any triaging step failed
    has_failures = any(step.get("status") == "failed" for step in triaging_results)

    rca_doc: dict = {
        "alert_id": alert_id,
        "sop_id": msg.get("sop_document_id", ""),
        "workflow_id": msg.get("sop_workflow_id", ""),
        "triaging_results": triaging_results,
        "root_cause": rca.get("root_cause", ""),
        "impact": rca.get("impact", ""),
        "recommendation": rca.get("recommendation", ""),
        "is_active_latest": True,
        "run_kind": run_kind,
    }
    if batch_id:
        rca_doc["retry_batch_id"] = batch_id
    if retry_level:
        rca_doc["retry_level"] = retry_level

    rca_insert = rca_results_col_sync().insert_one(rca_doc)
    rca_id = str(rca_insert.inserted_id)

    # Update alert pointer to latest RCA
    alerts_col_sync().update_one(
        {"_id": ObjectId(alert_id)},
        {"$set": {"latest_effective_rca_id": rca_id}},
    )

    if has_failures:
        alerts_col_sync().update_one(
            {"_id": ObjectId(alert_id)},
            {"$set": {"status": "sop_workflow_processfailed", "processing_status": "sop_workflow_processfailed", "processed_at": datetime.now(UTC)}},
        )
        _update_retry_state(batch_id, alert_id, "failed", "triaging step failures")
        if batch_id:
            alerts_col_sync().update_one({"_id": ObjectId(alert_id)}, {"$set": {"retry_in_progress": False}})
        logger.warning("Alert %s SOP workflow failed due to tool execution errors", alert_id)
        return

    root_cause = rca.get("root_cause", "")
    if not root_cause or root_cause == "N/A":
        alerts_col_sync().update_one({"_id": ObjectId(alert_id)}, {"$set": {"status": "rca_not_found", "processing_status": "RCANotFound", "processed_at": datetime.now(UTC)}})
        _update_retry_state(batch_id, alert_id, "failed", "RCA root cause not determined")
        if batch_id:
            alerts_col_sync().update_one({"_id": ObjectId(alert_id)}, {"$set": {"retry_in_progress": False}})
        logger.warning("Alert %s RCA could not be determined", alert_id)
        return

    alerts_col_sync().update_one({"_id": ObjectId(alert_id)}, {"$set": {"status": "rca_generated", "processing_status": "rca_generated"}})
    publish("stage3_validate", {**msg, "rca_id": rca_id})
    logger.info("Alert %s RCA generated (rca_id=%s)", alert_id, rca_id)


def run_worker():
    logger.info("Starting ExecuteSOP worker")
    consume("stage2_execute", _process)
