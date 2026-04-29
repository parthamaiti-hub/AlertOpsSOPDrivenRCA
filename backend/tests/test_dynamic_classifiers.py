import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient, ASGITransport

from backend.main import app
from backend.utils import strip_rtf
from backend.models.schemas import DynamicClassifier, TextAlert, Alert


# --- strip_rtf tests ---

def test_strip_rtf_plain_passthrough():
    text = "This is plain text alert content."
    assert strip_rtf(text) == text


def test_strip_rtf_removes_rtf_control_words():
    rtf = r"{\rtf1\ansi\deff0 {\fonttbl {\f0 Calibri;}}\f0\fs22 \b ALERT: Disk Full\b0\par Server prod-01 is at 95% disk.\par}"
    result = strip_rtf(rtf)
    assert "ALERT:" in result
    assert "Disk Full" in result
    assert "prod-01" in result
    assert "\\rtf" not in result
    assert "\\par" not in result
    assert "\\b " not in result


def test_strip_rtf_empty_string():
    assert strip_rtf("") == ""


def test_strip_rtf_multiline_plain():
    text = "Line 1\nLine 2\nLine 3"
    assert strip_rtf(text) == text


# --- DynamicClassifier model tests ---

def test_dynamic_classifier_model():
    dc = DynamicClassifier(label="1", field_name="environment", field_value="production")
    assert dc.label == "1"
    assert dc.field_name == "environment"
    assert dc.field_value == "production"


def test_dynamic_classifier_defaults():
    dc = DynamicClassifier(label="2")
    assert dc.field_name == ""
    assert dc.field_value == ""


# --- TextAlert model tests ---

def test_text_alert_model():
    ta = TextAlert(alert_text="Server disk full", raw_payload={"host": "prod-01"})
    assert ta.alert_text == "Server disk full"
    assert ta.raw_payload["host"] == "prod-01"


def test_text_alert_defaults():
    ta = TextAlert(alert_text="test")
    assert ta.raw_payload == {}


# --- Alert model with new fields ---

def test_alert_structured_defaults():
    a = Alert()
    assert a.alert_type == "structured"
    assert a.alert_text == ""
    assert a.source_application == ""
    assert a.domain == ""
    assert a.category == ""
    assert a.severity == ""


def test_alert_text_type():
    a = Alert(alert_type="text", alert_text="Disk full on prod")
    assert a.alert_type == "text"
    assert a.alert_text == "Disk full on prod"
    assert a.source_application == ""


# --- mapping_score computation ---

def test_compute_mapping_score_full_match():
    from backend.identifySOP.agent import _compute_mapping_score
    alert_dynamic = {"environment": "production", "region": "us-west-2", "host_type": "kubernetes-node"}
    sop_dc = [
        {"field_name": "environment", "field_value": "production"},
        {"field_name": "region", "field_value": "us-west-2"},
        {"field_name": "host_type", "field_value": "kubernetes-node"},
    ]
    score, detail = _compute_mapping_score(alert_dynamic, sop_dc)
    assert score == 100.0
    assert all(d["match"] for d in detail.values())


def test_compute_mapping_score_partial_match():
    from backend.identifySOP.agent import _compute_mapping_score
    alert_dynamic = {"environment": "production", "region": "eu-west-1", "host_type": "vm"}
    sop_dc = [
        {"field_name": "environment", "field_value": "production"},
        {"field_name": "region", "field_value": "us-west-2"},
        {"field_name": "host_type", "field_value": "kubernetes-node"},
    ]
    score, detail = _compute_mapping_score(alert_dynamic, sop_dc)
    assert score == pytest.approx(33.3, abs=0.1)
    assert detail["environment"]["match"] is True
    assert detail["region"]["match"] is False
    assert detail["host_type"]["match"] is False


def test_compute_mapping_score_no_match():
    from backend.identifySOP.agent import _compute_mapping_score
    alert_dynamic = {"environment": "staging"}
    sop_dc = [
        {"field_name": "environment", "field_value": "production"},
        {"field_name": "region", "field_value": "us-west-2"},
    ]
    score, detail = _compute_mapping_score(alert_dynamic, sop_dc)
    assert score == 0.0


def test_compute_mapping_score_empty_sop():
    from backend.identifySOP.agent import _compute_mapping_score
    score, detail = _compute_mapping_score({"env": "prod"}, [])
    assert score == 0.0
    assert detail == {}


# --- build_dynamic_text ---

def test_build_dynamic_text():
    from backend.sopmanagement.service import _build_dynamic_text
    dcs = [
        {"field_name": "environment", "field_value": "production"},
        {"field_name": "region", "field_value": "us-west-2"},
    ]
    result = _build_dynamic_text(dcs)
    assert "environment=production" in result
    assert "region=us-west-2" in result


def test_build_dynamic_text_empty():
    from backend.sopmanagement.service import _build_dynamic_text
    assert _build_dynamic_text([]) == ""


# --- POST /api/alerts/text route ---

@pytest.fixture
def mock_text_alert_db():
    with patch("backend.routes.alerts.alerts_col") as mock_alerts, \
         patch("backend.routes.alerts.publish") as mock_publish:
        col = MagicMock()
        mock_alerts.return_value = col
        yield {"alerts_col": col, "publish": mock_publish}


@pytest.mark.asyncio
async def test_create_text_alert(mock_text_alert_db):
    mock_result = MagicMock()
    mock_result.inserted_id = "text123"
    mock_text_alert_db["alerts_col"].insert_one = AsyncMock(return_value=mock_result)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/alerts/text", json={
            "alert_text": "ALERT: Disk full on prod-k8s-node-07",
            "raw_payload": {"host": "prod-k8s-node-07"},
        })
        assert resp.status_code == 201
        assert resp.json()["alert_id"] == "text123"
        mock_text_alert_db["publish"].assert_called_once()
        call_args = mock_text_alert_db["publish"].call_args
        assert call_args[0][0] == "alert_ingest"
        msg = call_args[0][1]
        assert msg["alert_type"] == "text"
        assert msg["alert_text"] == "ALERT: Disk full on prod-k8s-node-07"


# --- POST /api/webhooks/alerts/text route ---

@pytest.fixture
def mock_webhook_text_db():
    with patch("backend.routes.webhooks.alerts_col") as mock_alerts, \
         patch("backend.routes.webhooks.publish") as mock_publish:
        col = MagicMock()
        mock_alerts.return_value = col
        yield {"alerts_col": col, "publish": mock_publish}


@pytest.mark.asyncio
async def test_webhook_text_alert(mock_webhook_text_db):
    mock_result = MagicMock()
    mock_result.inserted_id = "wh_text456"
    mock_webhook_text_db["alerts_col"].insert_one = AsyncMock(return_value=mock_result)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/webhooks/alerts/text", json={
            "alert_text": "Server disk at 95%",
        })
        assert resp.status_code == 201
        assert resp.json()["alert_id"] == "wh_text456"


# --- sop_mappingdata.json structure ---

def test_sop_mapping_data_has_dynamic_classifiers():
    import pathlib
    mapping_file = pathlib.Path(__file__).parent.parent.parent / "data" / "sop_mappingdata.json"
    data = json.loads(mapping_file.read_text())
    for filename, meta in data.items():
        assert "dynamic_classifiers" in meta, f"{filename} missing dynamic_classifiers"
        dcs = meta["dynamic_classifiers"]
        assert len(dcs) == 7, f"{filename} should have 7 dynamic classifiers, got {len(dcs)}"
        for dc in dcs:
            assert "label" in dc
            assert "field_name" in dc
            assert "field_value" in dc


def test_disk_space_sop_in_mapping():
    import pathlib
    mapping_file = pathlib.Path(__file__).parent.parent.parent / "data" / "sop_mappingdata.json"
    data = json.loads(mapping_file.read_text())
    assert "disk_space_full_linux.txt" in data
    disk = data["disk_space_full_linux.txt"]
    assert disk["application"] == "container-platform"
    assert disk["severity"] == "critical"
    assert disk["workflow_file"] == "disk_space_full_linux_workflow.json"


# --- Sample data files exist ---

def test_sample_data_files_exist():
    import pathlib
    data_dir = pathlib.Path(__file__).parent.parent.parent / "data"
    assert (data_dir / "sample_alerts" / "disk_space_rtf_alert.json").exists()
    assert (data_dir / "sample_alerts" / "disk_space_text_alert.json").exists()
    assert (data_dir / "sop_documents" / "disk_space_full_linux.txt").exists()
    assert (data_dir / "sop_workflows" / "disk_space_full_linux_workflow.json").exists()


def test_sample_rtf_alert_has_rtf():
    import pathlib
    f = pathlib.Path(__file__).parent.parent.parent / "data" / "sample_alerts" / "disk_space_rtf_alert.json"
    data = json.loads(f.read_text())
    assert "alert_text" in data
    assert data["alert_text"].strip().startswith("{\\rtf")


def test_sample_text_alert_is_plain():
    import pathlib
    f = pathlib.Path(__file__).parent.parent.parent / "data" / "sample_alerts" / "disk_space_text_alert.json"
    data = json.loads(f.read_text())
    assert "alert_text" in data
    assert not data["alert_text"].strip().startswith("{\\rtf")
