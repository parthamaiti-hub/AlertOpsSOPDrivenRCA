from backend.models.schemas import Alert, SOPDocument, SOPWorkflow, RCAResult, ValidationResult, Feedback


def test_alert_defaults():
    a = Alert(source_application="app", domain="infra", category="perf", severity="critical")
    assert a.status == "ingested"
    assert a.sop_document_id is None
    assert a.sop_id is None
    assert a.raw_payload == {}


def test_alert_sop_id():
    a = Alert(source_application="app", domain="infra", category="perf", severity="critical", sop_id="SOP_DB_CONN_POOL")
    assert a.sop_id == "SOP_DB_CONN_POOL"


def test_sop_document():
    d = SOPDocument(name="test", application="app", domain="d", category="c", severity="s", content="text")
    assert d.content == "text"


def test_sop_workflow():
    w = SOPWorkflow(sop_id="s1", triaging_steps=[{"step_id": 1, "tool": "splunk_query"}])
    assert len(w.triaging_steps) == 1


def test_rca_result():
    r = RCAResult(alert_id="a1", sop_id="s1", workflow_id="w1", root_cause="test")
    assert r.confidence_score is None


def test_validation_result():
    v = ValidationResult(alert_id="a1", rca_id="r1", assessment="ok", confidence_score=80)
    assert v.confidence_score == 80


def test_feedback():
    f = Feedback(alert_id="a1", comment="good", confidence_score=90)
    assert f.comment == "good"
