"""Check MongoDB data: alerts, RCA results, validations, SOP workflows, SOP mappings, prompts, classifier match logs.

Usage:
    uv run python scripts/check_db.py              # show all
    uv run python scripts/check_db.py sop          # SOP mapping detail only
    uv run python scripts/check_db.py sop SOP_ID   # single SOP mapping detail
    uv run python scripts/check_db.py prompts      # prompt templates only
    uv run python scripts/check_db.py matchlogs    # classifier match logs only
"""

import json
import sys

from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017")
db = client["sop_alert_analytics"]

SEP = "-" * 60


def print_sop_mapping_detail(doc: dict):
    """Print full detail of a single SOP mapping record."""
    print(f"  sop_id          : {doc.get('sop_id', '')}")
    print(f"  name            : {doc.get('name', '')}")
    print(f"  application     : {doc.get('application', '')}")
    print(f"  domain          : {doc.get('domain', '')}")
    print(f"  category        : {doc.get('category', '')}")
    print(f"  severity        : {doc.get('severity', '')}")
    print(f"  doc_version     : {doc.get('sop_document_version', '—')}")
    print(f"  wf_version      : {doc.get('workflow_version', '—')}")
    print(f"  effective_at    : {doc.get('mapping_version_created_at', '—')}")
    print(f"  change_type     : {doc.get('change_type', '—')}")
    print(f"  sop_document_id : {doc.get('sop_document_id', '')}")
    print(f"  workflow_id     : {doc.get('workflow_id', '')}")
    print(f"  doc_file        : {doc.get('sop_document_file', '')}")
    print(f"  workflow_file   : {doc.get('workflow_file', '')}")
    print(f"  source          : {doc.get('source', doc.get('seeded', '?'))}")  # supports both old and new field
    print(f"  created_at      : {doc.get('created_at', '')}")

    # History count
    history_count = db.sop_mapping_history.count_documents({"sop_id": doc.get("sop_id", "")})
    if history_count:
        print(f"  history_entries : {history_count} archived version(s)")

    # Dynamic classifiers
    dcs = doc.get("dynamic_classifiers", [])
    if dcs:
        print(f"  dynamic_classifiers ({len(dcs)}):")
        for dc in dcs:
            print(f"    [{dc.get('label','')}] {dc.get('field_name','')}: {dc.get('field_value','')}")

    # Cross-reference sop_documents
    doc_id = doc.get("sop_document_id")
    if doc_id:
        from bson import ObjectId
        sop_doc = db.sop_documents.find_one({"_id": ObjectId(doc_id)})
        if sop_doc:
            print(f"  [sop_documents]  app={sop_doc.get('application','')}  domain={sop_doc.get('domain','')}  category={sop_doc.get('category','')}  severity={sop_doc.get('severity','')}")
            content_preview = str(sop_doc.get('content', ''))[:120].replace('\n', ' ')
            print(f"                   content_preview: {content_preview}...")
        else:
            print(f"  [sop_documents]  WARNING: document {doc_id} not found")

    # Cross-reference sop_workflows
    wf_id = doc.get("workflow_id")
    if wf_id:
        from bson import ObjectId
        wf = db.sop_workflows.find_one({"_id": ObjectId(wf_id)})
        if wf:
            wf_sop_id = wf.get("sop_id", "")
            steps = wf.get("triaging_steps", [])
            match = "OK" if wf_sop_id == doc.get("sop_id") else "MISMATCH"
            print(f"  [sop_workflows]  sop_id={wf_sop_id}  triaging_steps={len(steps)}  sop_id match: {match}")
            # Show alert_identifier
            ident = wf.get("alert_identifier", {})
            if ident:
                print(f"                   alert_identifier: app={ident.get('application','')}  domain={ident.get('domain','')}  category={ident.get('category','')}")
            # Show triaging steps
            if steps:
                print(f"                   --- Triaging Steps ---")
                for step in steps:
                    print(f"                   step {step.get('step_id','?')}: [{step.get('tool','')}] {step.get('action','')}")
            # Show communication steps
            comm = wf.get("communication_steps", [])
            if comm:
                channels = ", ".join(s.get("channel", "") for s in comm)
                print(f"                   communication_steps: {channels}")
        else:
            print(f"  [sop_workflows]  WARNING: workflow {wf_id} not found")


def show_sop_mappings(sop_id_filter: str = None):
    print(f"\n{'='*60}")
    print("SOP MAPPINGS (MongoDB)")    
    print(f"{'='*60}")
    query = {}
    if sop_id_filter:
        query = {"sop_id": sop_id_filter}
    docs = list(db.sop_mappings.find(query, {"_id": 0}))
    if not docs:
        print(f"  (no records{' for sop_id=' + sop_id_filter if sop_id_filter else ''})")
        return
    for doc in docs:
        print(SEP)
        print_sop_mapping_detail(doc)
    print(SEP)
    print(f"Total: {len(docs)} mapping(s)")


def show_prompts():
    print(f"\n{'='*60}")
    print("PROMPT TEMPLATES (MongoDB)")
    print(f"{'='*60}")
    docs = list(db.prompts.find({}, {"_id": 0}))
    if not docs:
        print("  (no records)")
        return
    for doc in docs:
        print(SEP)
        print(f"  agent      : {doc.get('agent', '')}")
        print(f"  key        : {doc.get('key', '')}")
        print(f"  version    : {doc.get('version', '')}")
        print(f"  updated_at : {doc.get('updated_at', '')}")
        template = str(doc.get('template', ''))
        preview = template[:200].replace('\n', ' ') + ('...' if len(template) > 200 else '')
        print(f"  template   : {preview}")
    print(SEP)
    print(f"Total: {len(docs)} prompt(s)")


def show_match_logs():
    print(f"\n{'='*60}")
    print("CLASSIFIER MATCH LOGS (MongoDB)")
    print(f"{'='*60}")
    docs = list(db.classifier_match_logs.find({}, {"_id": 0}).sort("created_at", -1).limit(20))
    if not docs:
        print("  (no records)")
        return
    for doc in docs:
        print(SEP)
        print(f"  alert_id       : {doc.get('alert_id', '')}")
        print(f"  alert_type     : {doc.get('alert_type', '')}")
        print(f"  sop_id         : {doc.get('sop_id', '')}")
        print(f"  mapping_score  : {doc.get('mapping_score', '')}")
        print(f"  created_at     : {doc.get('created_at', '')}")
        static = doc.get("static_classifiers", {})
        if static:
            print(f"  static         : app={static.get('application','')} domain={static.get('domain','')} cat={static.get('category','')} sev={static.get('severity','')}")
        dynamic = doc.get("dynamic_fields_extracted", {})
        if dynamic:
            print(f"  dynamic_fields : {json.dumps(dynamic)}")
        detail = doc.get("match_detail", {})
        if detail:
            for fn, info in detail.items():
                status = "MATCH" if info.get("match") else "MISS"
                print(f"    {fn}: expected={info.get('expected','')} actual={info.get('actual','')} [{status}]")
        candidates = doc.get("all_candidates", [])
        if candidates:
            cands = ", ".join(f"{c['sop_id']}({c['mapping_score']})" for c in candidates)
            print(f"  candidates     : {cands}")
    print(SEP)
    print(f"Total shown: {len(docs)} (latest 20)")


def show_all():
    print("=== Alerts ===")
    for doc in db.alerts.find({}, {"_id": 1, "status": 1, "source_application": 1, "category": 1}):
        print(f"  id={doc['_id']}  status={doc.get('status', '?')}  app={doc.get('source_application', '')}  cat={doc.get('category', '')}")

    print("\n=== RCA Results ===")
    for doc in db.rca_results.find():
        print(f"  rca_id={doc['_id']}  alert_id={doc.get('alert_id', '')}  root_cause={str(doc.get('root_cause', ''))[:80]}  confidence={doc.get('confidence_score', 'N/A')}")

    print("\n=== Validation Results ===")
    for doc in db.validation_results.find():
        print(f"  id={doc['_id']}  alert_id={doc.get('alert_id', '')}  rca_id={doc.get('rca_id', '')}  score={doc.get('confidence_score', 'N/A')}  assessment={str(doc.get('assessment', ''))[:60]}")

    print("\n=== SOP Documents ===")
    for doc in db.sop_documents.find({}, {"_id": 1, "name": 1, "application": 1, "domain": 1, "category": 1, "severity": 1}):
        print(f"  id={doc['_id']}  name={doc.get('name', '')}  app={doc.get('application', '')}  domain={doc.get('domain', '')}  category={doc.get('category', '')}  severity={doc.get('severity', '')}")

    print("\n=== SOP Workflows ===")
    for doc in db.sop_workflows.find({}, {"_id": 1, "sop_id": 1, "alert_identifier": 1}):
        ident = doc.get("alert_identifier", {})
        print(f"  id={doc['_id']}  sop_id={doc.get('sop_id', '')}  app={ident.get('application', '')}  domain={ident.get('domain', '')}")

    show_sop_mappings()
    show_prompts()
    show_match_logs()

    print(f"\nTotals: {db.alerts.count_documents({})} alerts, {db.rca_results.count_documents({})} RCAs, "
          f"{db.validation_results.count_documents({})} validations, {db.sop_documents.count_documents({})} SOP docs, "
          f"{db.sop_workflows.count_documents({})} workflows, {db.sop_mappings.count_documents({})} SOP mappings, "
          f"{db.prompts.count_documents({})} prompts, {db.classifier_match_logs.count_documents({})} match logs")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "sop":
        sop_id_filter = args[1] if len(args) > 1 else None
        show_sop_mappings(sop_id_filter)
    elif args and args[0] == "prompts":
        show_prompts()
    elif args and args[0] == "matchlogs":
        show_match_logs()
    else:
        show_all()
