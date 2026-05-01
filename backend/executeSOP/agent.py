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
    pending_actions_col_sync,
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
    remediation_results: list
    communication_results: list
    escalation_results: list
    pending_steps: list
    selected_remediation_ids: list
    rca: dict


def _run_step(step: dict, msg: dict) -> dict:
    """Execute a single workflow step and return a result dict."""
    tool_name = step.get("tool", "")
    params = dict(step.get("tool_params", {}))
    raw_payload = msg.get("raw_payload", {})
    host = raw_payload.get("host", "unknown")
    application = msg.get("source_application", "unknown")

    for k, v in params.items():
        if isinstance(v, str):
            params[k] = v.replace("{host}", host).replace("{application}", application)

    try:
        output = execute_tool(tool_name, params)
        status = "failed" if (isinstance(output, dict) and "error" in output) else "success"
        return {
            "step_id": step.get("step_id"),
            "action": step.get("action", ""),
            "tool": tool_name,
            "tool_params": params,
            "output": output,
            "status": status,
            "error": output.get("error") if status == "failed" else None,
        }
    except Exception as exc:
        logger.exception("Tool %s failed step %s", tool_name, step.get("step_id"))
        return {
            "step_id": step.get("step_id"),
            "action": step.get("action", ""),
            "tool": tool_name,
            "tool_params": params,
            "output": None,
            "status": "failed",
            "error": str(exc),
        }


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
            return {"triaging_results": [], "pending_steps": []}

        results = []
        pending = list(state.get("pending_steps") or [])

        for step in wf.get("triaging_steps", []):
            if step.get("requires_approval"):
                pending.append({
                    "step_id": step.get("step_id"),
                    "section": "triaging",
                    "action": step.get("action", ""),
                    "tool": step.get("tool", ""),
                    "tool_params": step.get("tool_params", {}),
                    "status": "pending",
                })
                continue

            tool_name = step.get("tool", "")
            params = step.get("tool_params", {})
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

            results.append(_run_step(step, msg))

        return {"triaging_results": results, "pending_steps": pending}

    def select_remediation_steps(state: ExecuteState) -> dict:
        wf = state.get("workflow") or {}
        remediation_steps = wf.get("remediation_steps", [])
        if not remediation_steps:
            return {"selected_remediation_ids": []}

        triaging_summary = json.dumps(state.get("triaging_results", []), default=str)[:3000]
        steps_desc = json.dumps(
            [{"step_id": s.get("step_id"), "action": s.get("action"), "condition": s.get("condition", "")} for s in remediation_steps],
            default=str,
        )
        prompt = (
            f"Given these triaging results:\n{triaging_summary}\n\n"
            f"And these remediation steps with conditions:\n{steps_desc}\n\n"
            "Which step_ids should be executed? Return a JSON array of integers only, e.g. [1,2]."
        )
        resp = llm.invoke(prompt)
        try:
            text = resp.content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            ids = json.loads(text)
            if not isinstance(ids, list):
                ids = []
        except Exception:
            ids = [s.get("step_id") for s in remediation_steps]
        return {"selected_remediation_ids": ids}

    def execute_remediation(state: ExecuteState) -> dict:
        wf = state.get("workflow") or {}
        msg = state["message"]
        selected_ids = set(state.get("selected_remediation_ids") or [])
        results = []
        pending = list(state.get("pending_steps") or [])

        for step in wf.get("remediation_steps", []):
            if step.get("step_id") not in selected_ids:
                continue
            if step.get("requires_approval"):
                pending.append({
                    "step_id": step.get("step_id"),
                    "section": "remediation",
                    "action": step.get("action", ""),
                    "tool": step.get("tool", ""),
                    "tool_params": step.get("tool_params", {}),
                    "status": "pending",
                })
                continue
            results.append(_run_step(step, msg))

        return {"remediation_results": results, "pending_steps": pending}

    def generate_rca(state: ExecuteState) -> dict:
        msg = state["message"]
        triaging = state.get("triaging_results", [])
        remediation = state.get("remediation_results", [])
        results_summary = json.dumps(triaging + remediation, default=str)[:4000]

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
            text = resp.content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            rca = json.loads(text)
        except (json.JSONDecodeError, IndexError):
            rca = {"root_cause": resp.content, "impact": "See analysis above", "recommendation": "Review manually"}
        return {"rca": rca}

    def execute_communication(state: ExecuteState) -> dict:
        wf = state.get("workflow") or {}
        msg = state["message"]
        results = []
        pending = list(state.get("pending_steps") or [])

        for step in wf.get("communication_steps", []):
            if step.get("requires_approval"):
                pending.append({
                    "step_id": step.get("step_id"),
                    "section": "communication",
                    "action": step.get("action", ""),
                    "tool": step.get("tool", ""),
                    "tool_params": step.get("tool_params", {}),
                    "status": "pending",
                })
                continue
            # Only execute steps that have a tool defined (skip legacy bare-object steps)
            if step.get("tool"):
                results.append(_run_step(step, msg))

        return {"communication_results": results, "pending_steps": pending}

    def execute_escalation(state: ExecuteState) -> dict:
        wf = state.get("workflow") or {}
        msg = state["message"]
        results = []
        pending = list(state.get("pending_steps") or [])

        for step in wf.get("escalation", []):
            if step.get("requires_approval"):
                pending.append({
                    "step_id": step.get("step_id"),
                    "section": "escalation",
                    "action": step.get("action", ""),
                    "tool": step.get("tool", ""),
                    "tool_params": step.get("tool_params", {}),
                    "status": "pending",
                })
                continue
            # Only run escalation on_failure if there were triaging/remediation failures
            if step.get("condition") == "on_failure":
                has_failures = any(
                    r.get("status") == "failed"
                    for r in (state.get("triaging_results", []) + state.get("remediation_results", []))
                )
                if not has_failures:
                    continue
            if step.get("tool"):
                results.append(_run_step(step, msg))

        return {"escalation_results": results, "pending_steps": pending}

    graph = StateGraph(ExecuteState)
    graph.add_node("load_workflow", load_workflow)
    graph.add_node("execute_triaging", execute_triaging)
    graph.add_node("select_remediation_steps", select_remediation_steps)
    graph.add_node("execute_remediation", execute_remediation)
    graph.add_node("generate_rca", generate_rca)
    graph.add_node("execute_communication", execute_communication)
    graph.add_node("execute_escalation", execute_escalation)
    graph.set_entry_point("load_workflow")
    graph.add_edge("load_workflow", "execute_triaging")
    graph.add_edge("execute_triaging", "select_remediation_steps")
    graph.add_edge("select_remediation_steps", "execute_remediation")
    graph.add_edge("execute_remediation", "generate_rca")
    graph.add_edge("generate_rca", "execute_communication")
    graph.add_edge("execute_communication", "execute_escalation")
    graph.add_edge("execute_escalation", END)
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
    remediation_results = result.get("remediation_results", [])
    communication_results = result.get("communication_results", [])
    escalation_results = result.get("escalation_results", [])
    pending_steps = result.get("pending_steps", [])

    # Check if any executed step failed
    all_results = triaging_results + remediation_results
    has_failures = any(step.get("status") == "failed" for step in all_results)

    rca_doc: dict = {
        "alert_id": alert_id,
        "sop_id": msg.get("sop_document_id", ""),
        "workflow_id": msg.get("sop_workflow_id", ""),
        "triaging_results": triaging_results,
        "remediation_results": remediation_results,
        "communication_results": communication_results,
        "escalation_results": escalation_results,
        "root_cause": rca.get("root_cause", ""),
        "impact": rca.get("impact", ""),
        "recommendation": rca.get("recommendation", ""),
        "is_active_latest": True,
        "run_kind": run_kind,
        "processed_at": datetime.now(UTC),
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

    # Insert pending steps into pending_actions collection
    if pending_steps:
        now = datetime.now(UTC)
        docs = [
            {
                "alert_id": alert_id,
                "rca_id": rca_id,
                "section": s.get("section", ""),
                "step_id": s.get("step_id"),
                "action": s.get("action", ""),
                "tool": s.get("tool", ""),
                "tool_params": s.get("tool_params", {}),
                "status": "pending",
                "created_at": now,
            }
            for s in pending_steps
        ]
        pending_actions_col_sync().insert_many(docs)

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

    final_status = "pending_actions" if pending_steps else "rca_generated"
    alerts_col_sync().update_one(
        {"_id": ObjectId(alert_id)},
        {"$set": {"status": final_status, "processing_status": final_status, "processed_at": datetime.now(UTC)}},
    )
    publish("stage3_validate", {**msg, "rca_id": rca_id})
    logger.info("Alert %s RCA generated (rca_id=%s) pending_steps=%d", alert_id, rca_id, len(pending_steps))


def run_worker():
    logger.info("Starting ExecuteSOP worker")
    consume("stage2_execute", _process)
